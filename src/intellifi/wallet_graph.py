"""Wallet entity resolution: pick a universe, pull on-chain transfers, build
an entity graph, run community detection, and report.

Definitions used throughout:

* **universe** — the set of proxy wallets we care about, e.g. the union of
  top-50 by trade notional + top-50 by realised PnL + top-50 by Bayesian
  calibration gap. Typically ~100-130 wallets after deduplication.
* **direct edge** — an on-chain USDC or ERC-1155 transfer where both source
  and destination are in the universe. Strong evidence of relationship.
* **common-neighbor edge** — both A and B interact with the same external
  address X, where X is *not* a "popular" wallet (CEX, bridge, Polymarket
  internal). Weaker evidence — score by the rarity of X.

The output is a NetworkX graph + a per-cluster summary. Communities are
detected with python-louvain (Blondel et al. 2008), which has the right
trade-offs for our scale (~100 nodes, <10k edges).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import duckdb
import networkx as nx
import polars as pl

from . import config
from .onchain import POPULAR_ADDRESSES, Polygonscan, USDC_E, USDC_NATIVE

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Universe selection
# ---------------------------------------------------------------------------

def select_universe(
    con: duckdb.DuckDBPyConnection,
    *,
    top_n_notional: int = 50,
    top_n_pnl: int = 50,
    top_n_skill: int = 50,
    min_skill_trades: int = 20,
) -> pl.DataFrame:
    """Union of three top-N lists. Returns a wide table with all three ranks."""
    # Build the bets view if it doesn't exist (skill module dependency)
    from .skill import build_bets_view
    build_bets_view(con)

    sql = f"""
    WITH notional AS (
        SELECT proxy_wallet,
               SUM(notional_usdc)         AS total_notional,
               COUNT(*)                   AS n_trades,
               COUNT(DISTINCT condition_id) AS n_markets
        FROM trades
        WHERE proxy_wallet IS NOT NULL AND notional_usdc > 0
        GROUP BY 1
    ),
    pnl AS (
        SELECT t.proxy_wallet,
               SUM(CASE
                 WHEN t.side = 'BUY'  AND t.outcome_index = w.winning_outcome_index THEN (1.0 - t.price) * t.size
                 WHEN t.side = 'BUY'                                                THEN -t.price * t.size
                 WHEN t.side = 'SELL' AND t.outcome_index <> w.winning_outcome_index THEN t.price * t.size
                 WHEN t.side = 'SELL'                                               THEN (t.price - 1.0) * t.size
               END) AS realised_pnl
        FROM trades t JOIN winning_outcomes w USING (condition_id)
        WHERE t.proxy_wallet IS NOT NULL AND t.price BETWEEN 0 AND 1 AND t.size > 0
        GROUP BY 1
    ),
    skill AS (
        SELECT proxy_wallet,
               COUNT(*)                                AS n_bets,
               SUM(size * won) / NULLIF(SUM(size), 0)  AS realised_hit_rate,
               SUM(size * implied_p) / NULLIF(SUM(size), 0) AS mean_implied_p,
               SUM(size * won) / NULLIF(SUM(size), 0)
                 - SUM(size * implied_p) / NULLIF(SUM(size), 0) AS calibration_gap
        FROM bets
        WHERE implied_p IS NOT NULL AND won IS NOT NULL AND proxy_wallet IS NOT NULL
        GROUP BY 1
        HAVING COUNT(*) >= {min_skill_trades}
    ),
    top_notional AS (
        SELECT proxy_wallet, total_notional,
               row_number() OVER (ORDER BY total_notional DESC) AS rk_notional
        FROM notional
        ORDER BY total_notional DESC LIMIT {top_n_notional}
    ),
    top_pnl AS (
        SELECT proxy_wallet, realised_pnl,
               row_number() OVER (ORDER BY realised_pnl DESC) AS rk_pnl
        FROM pnl
        ORDER BY realised_pnl DESC LIMIT {top_n_pnl}
    ),
    top_skill AS (
        SELECT proxy_wallet, calibration_gap,
               row_number() OVER (ORDER BY calibration_gap DESC) AS rk_skill
        FROM skill
        ORDER BY calibration_gap DESC LIMIT {top_n_skill}
    ),
    members AS (
        SELECT proxy_wallet FROM top_notional
        UNION SELECT proxy_wallet FROM top_pnl
        UNION SELECT proxy_wallet FROM top_skill
    )
    SELECT m.proxy_wallet,
           n.total_notional, n.n_trades, n.n_markets,
           p.realised_pnl,
           s.n_bets, s.realised_hit_rate, s.mean_implied_p, s.calibration_gap,
           tn.rk_notional, tp.rk_pnl, ts.rk_skill
    FROM members m
    LEFT JOIN notional n     ON n.proxy_wallet = m.proxy_wallet
    LEFT JOIN pnl p          ON p.proxy_wallet = m.proxy_wallet
    LEFT JOIN skill s        ON s.proxy_wallet = m.proxy_wallet
    LEFT JOIN top_notional tn ON tn.proxy_wallet = m.proxy_wallet
    LEFT JOIN top_pnl tp     ON tp.proxy_wallet = m.proxy_wallet
    LEFT JOIN top_skill ts   ON ts.proxy_wallet = m.proxy_wallet
    ORDER BY COALESCE(n.total_notional, 0) DESC;
    """
    return con.sql(sql).pl()


# ---------------------------------------------------------------------------
# Transfer ingestion → parquet
# ---------------------------------------------------------------------------

TRANSFERS_DIR = config.PARQUET_DIR / "onchain_transfers"


def transfers_path(address: str, kind: str) -> Path:
    return TRANSFERS_DIR / kind / f"{address.lower()}.parquet"


def fetch_universe_transfers(
    addresses: Iterable[str],
    *,
    client: Polygonscan,
    overwrite: bool = False,
    max_pages: int = 10,
) -> dict[str, dict[str, int]]:
    """For each address, pull and persist USDC + ERC-1155 transfer history.

    Returns ``{address: {usdc_e: N, usdc_native: N, erc1155: N}}``. Idempotent:
    if a per-kind parquet already exists for a wallet it is not re-fetched.
    ``max_pages`` caps pagination depth per (wallet, endpoint) — see
    ``Polygonscan.erc20_transfers_all``.
    """
    TRANSFERS_DIR.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict[str, int]] = {}

    addresses = list(addresses)
    for i, addr in enumerate(addresses, 1):
        addr_l = addr.lower()
        per_addr: dict[str, int] = {}
        for kind, contract in (
            ("usdc_e", USDC_E),
            ("usdc_native", USDC_NATIVE),
        ):
            path = transfers_path(addr_l, kind)
            if path.exists() and not overwrite:
                per_addr[kind] = int(pl.scan_parquet(path).select(pl.len()).collect().item())
                continue
            rows = client.erc20_transfers_all(
                addr_l, contract_address=contract, max_pages=max_pages
            )
            df = _erc20_to_frame(rows, owner=addr_l, token=kind)
            path.parent.mkdir(parents=True, exist_ok=True)
            df.write_parquet(path, compression="zstd")
            per_addr[kind] = df.height

        path = transfers_path(addr_l, "erc1155")
        if path.exists() and not overwrite:
            per_addr["erc1155"] = int(pl.scan_parquet(path).select(pl.len()).collect().item())
        else:
            rows = client.erc1155_transfers_all(addr_l, max_pages=max_pages)
            df = _erc1155_to_frame(rows, owner=addr_l)
            path.parent.mkdir(parents=True, exist_ok=True)
            df.write_parquet(path, compression="zstd")
            per_addr["erc1155"] = df.height

        summary[addr_l] = per_addr
        log.info("[%d/%d] %s: usdc_e=%d usdc_native=%d erc1155=%d (calls=%d)",
                 i, len(addresses), addr_l,
                 per_addr["usdc_e"], per_addr["usdc_native"], per_addr["erc1155"],
                 client.calls_made)

    return summary


_ERC20_SCHEMA: dict[str, pl.DataType] = {
    "owner": pl.Utf8, "token": pl.Utf8, "contract_address": pl.Utf8,
    "block_number": pl.Int64, "ts_utc": pl.Datetime("us", "UTC"),
    "tx_hash": pl.Utf8, "from_address": pl.Utf8, "to_address": pl.Utf8,
    "value": pl.Float64, "token_symbol": pl.Utf8, "token_decimal": pl.Int32,
}

_ERC1155_SCHEMA: dict[str, pl.DataType] = {
    "owner": pl.Utf8, "contract_address": pl.Utf8,
    "block_number": pl.Int64, "ts_utc": pl.Datetime("us", "UTC"),
    "tx_hash": pl.Utf8, "from_address": pl.Utf8, "to_address": pl.Utf8,
    "token_id": pl.Utf8, "token_value": pl.Float64,
}


def _erc20_to_frame(rows: list[dict], *, owner: str, token: str) -> pl.DataFrame:
    from datetime import UTC, datetime
    cleaned = []
    for r in rows:
        try:
            decimals = int(r.get("tokenDecimal", "0"))
        except Exception:
            decimals = 0
        raw = r.get("value", "0")
        try:
            value = float(int(raw)) / (10 ** decimals) if decimals else float(int(raw))
        except Exception:
            value = None
        ts = r.get("timeStamp")
        ts_utc = datetime.fromtimestamp(int(ts), tz=UTC) if ts else None
        cleaned.append({
            "owner": owner,
            "token": token,
            "contract_address": (r.get("contractAddress") or "").lower() or None,
            "block_number": int(r["blockNumber"]) if r.get("blockNumber") else None,
            "ts_utc": ts_utc,
            "tx_hash": r.get("hash"),
            "from_address": (r.get("from") or "").lower() or None,
            "to_address": (r.get("to") or "").lower() or None,
            "value": value,
            "token_symbol": r.get("tokenSymbol"),
            "token_decimal": decimals,
        })
    return pl.DataFrame(cleaned, schema=_ERC20_SCHEMA, orient="row" if cleaned else None)


def _erc1155_to_frame(rows: list[dict], *, owner: str) -> pl.DataFrame:
    from datetime import UTC, datetime
    cleaned = []
    for r in rows:
        ts = r.get("timeStamp")
        ts_utc = datetime.fromtimestamp(int(ts), tz=UTC) if ts else None
        try:
            value = float(int(r.get("tokenValue", "0")))
        except Exception:
            value = None
        cleaned.append({
            "owner": owner,
            "contract_address": (r.get("contractAddress") or "").lower() or None,
            "block_number": int(r["blockNumber"]) if r.get("blockNumber") else None,
            "ts_utc": ts_utc,
            "tx_hash": r.get("hash"),
            "from_address": (r.get("from") or "").lower() or None,
            "to_address": (r.get("to") or "").lower() or None,
            "token_id": r.get("tokenID"),
            "token_value": value,
        })
    return pl.DataFrame(cleaned, schema=_ERC1155_SCHEMA, orient="row" if cleaned else None)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

@dataclass
class GraphConfig:
    """Tunable thresholds for the relationship inference."""

    # Minimum USDC amount (in dollars) to count a transfer as an edge.
    # USDC has 6 decimals, parsed value is already in dollars.
    min_usdc_transfer: float = 100.0

    # Common-neighbor heuristic. An external address X is an *uninformative*
    # connector if it shows up as a counterparty for >= this many universe
    # members (probably a CEX deposit / bridge / aggregator).
    popular_neighbor_threshold: int = 5

    # Minimum number of shared non-popular neighbors for a common-neighbor
    # edge to be drawn between A and B.
    min_shared_neighbors: int = 1

    # When set, common-neighbor edges use a Jaccard-like weight on the shared
    # neighbor set so a pair sharing many narrow connections beats a pair
    # sharing one moderately-narrow connector.
    weight_common_by_neighbor_rarity: bool = True

    # Whether to include ERC-1155 transfers in direct edges. Outcome-share
    # transfers between addresses are very high-signal (no economic reason to
    # send shares to a stranger).
    include_erc1155: bool = True


@dataclass
class GraphResult:
    graph: nx.Graph
    direct_edges: list[tuple[str, str, dict]] = field(default_factory=list)
    common_edges: list[tuple[str, str, dict]] = field(default_factory=list)
    popular_addresses: set[str] = field(default_factory=set)


def build_entity_graph(
    universe: list[str],
    *,
    cfg: GraphConfig | None = None,
) -> GraphResult:
    """Construct the entity graph from the persisted on-chain transfers.

    Reads ``data/parquet/onchain_transfers/{usdc_e,usdc_native,erc1155}/<addr>.parquet``
    written by ``fetch_universe_transfers``.
    """
    cfg = cfg or GraphConfig()
    universe_set = {a.lower() for a in universe}

    # 1) Build per-address counterparty sets and load direct edges (universe ↔ universe)
    direct: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"usdc_total": 0.0, "erc1155_count": 0, "tx_count": 0}
    )
    neighbors: dict[str, set[str]] = {a: set() for a in universe_set}

    for addr in universe_set:
        # USDC.e and USDC native
        for token in ("usdc_e", "usdc_native"):
            path = transfers_path(addr, token)
            if not path.exists():
                continue
            df = pl.read_parquet(path)
            if df.height == 0:
                continue
            for from_a, to_a, value in df.select(
                ["from_address", "to_address", "value"]
            ).iter_rows():
                if value is None or value < cfg.min_usdc_transfer:
                    continue
                from_a = (from_a or "").lower()
                to_a = (to_a or "").lower()
                # neighbor record: every counterparty observed
                if from_a == addr and to_a:
                    neighbors[addr].add(to_a)
                elif to_a == addr and from_a:
                    neighbors[addr].add(from_a)
                # direct edge if both endpoints are in the universe
                if from_a in universe_set and to_a in universe_set and from_a != to_a:
                    key = tuple(sorted((from_a, to_a)))
                    direct[key]["usdc_total"] += value
                    direct[key]["tx_count"] += 1

        # ERC-1155 (outcome shares)
        if cfg.include_erc1155:
            path = transfers_path(addr, "erc1155")
            if path.exists():
                df = pl.read_parquet(path)
                for from_a, to_a, val in df.select(
                    ["from_address", "to_address", "token_value"]
                ).iter_rows():
                    from_a = (from_a or "").lower()
                    to_a = (to_a or "").lower()
                    # Skip mint/burn (transfers from/to 0x000…0)
                    zero = "0x" + "0" * 40
                    if from_a == zero or to_a == zero:
                        continue
                    if from_a == addr and to_a:
                        neighbors[addr].add(to_a)
                    elif to_a == addr and from_a:
                        neighbors[addr].add(from_a)
                    if from_a in universe_set and to_a in universe_set and from_a != to_a:
                        key = tuple(sorted((from_a, to_a)))
                        direct[key]["erc1155_count"] += 1
                        direct[key]["tx_count"] += 1

    # 2) Identify "popular" external neighbors (likely CEX / bridge / Polymarket).
    neighbor_counts: dict[str, int] = defaultdict(int)
    for addr, ns in neighbors.items():
        for n in ns:
            if n in universe_set:
                continue  # in-universe is direct, not "common"
            if n in POPULAR_ADDRESSES:
                continue
            neighbor_counts[n] += 1
    popular = {n for n, c in neighbor_counts.items() if c >= cfg.popular_neighbor_threshold}
    popular |= POPULAR_ADDRESSES
    log.info("popular addresses suppressed: %d (threshold=%d)",
             len(popular), cfg.popular_neighbor_threshold)

    # 3) Common-neighbor edges: for each pair of universe wallets, count
    #    shared neighbors that are not popular.
    common: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"shared": 0, "weight": 0.0, "examples": []}
    )
    universe_list = sorted(universe_set)
    for i, a in enumerate(universe_list):
        for b in universe_list[i + 1:]:
            shared = (neighbors[a] & neighbors[b]) - popular
            if len(shared) < cfg.min_shared_neighbors:
                continue
            if cfg.weight_common_by_neighbor_rarity:
                w = sum(1.0 / max(1, neighbor_counts.get(n, 1)) for n in shared)
            else:
                w = float(len(shared))
            common[(a, b)] = {
                "shared": len(shared),
                "weight": w,
                "examples": list(shared)[:5],
            }

    # 4) Assemble NetworkX graph (undirected, weighted).
    g = nx.Graph()
    for a in universe_set:
        g.add_node(a)
    direct_edges = []
    for (a, b), meta in direct.items():
        direct_edges.append((a, b, dict(meta)))
        weight = meta["usdc_total"] / 1e4 + meta["erc1155_count"] * 5.0
        g.add_edge(a, b, kind="direct", weight=weight, **meta)
    common_edges = []
    for (a, b), meta in common.items():
        common_edges.append((a, b, dict(meta)))
        if g.has_edge(a, b):
            # Direct edges dominate; still record the shared count.
            g[a][b]["shared_neighbors"] = meta["shared"]
            continue
        g.add_edge(a, b, kind="common", weight=meta["weight"],
                   shared_neighbors=meta["shared"], examples=meta["examples"])

    return GraphResult(graph=g,
                       direct_edges=direct_edges,
                       common_edges=common_edges,
                       popular_addresses=popular)


# ---------------------------------------------------------------------------
# Community detection
# ---------------------------------------------------------------------------

def detect_communities(g: nx.Graph, *, resolution: float = 1.0,
                       random_state: int | None = 42) -> dict[str, int]:
    """Louvain partitioning. Returns ``{node: community_id}``.

    Uses ``python-louvain`` (community-louvain), which expects edge weights
    via the ``weight`` attribute.
    """
    import community as community_louvain  # type: ignore[import-not-found]
    if g.number_of_edges() == 0:
        return {n: i for i, n in enumerate(g.nodes)}
    return community_louvain.best_partition(
        g, weight="weight", resolution=resolution, random_state=random_state
    )


def community_summary(
    universe_df: pl.DataFrame,
    partition: dict[str, int],
    graph: nx.Graph,
) -> pl.DataFrame:
    """One row per community: size, total notional/pnl, members."""
    by_comm: dict[int, dict] = defaultdict(
        lambda: {"members": [], "n_direct_edges": 0, "n_common_edges": 0}
    )
    for node, comm in partition.items():
        by_comm[comm]["members"].append(node)

    for u, v, data in graph.edges(data=True):
        if partition.get(u) == partition.get(v):
            if data.get("kind") == "direct":
                by_comm[partition[u]]["n_direct_edges"] += 1
            elif data.get("kind") == "common":
                by_comm[partition[u]]["n_common_edges"] += 1

    rows = []
    for comm, info in by_comm.items():
        members = info["members"]
        sub = universe_df.filter(pl.col("proxy_wallet").is_in(members))
        rows.append({
            "community_id": comm,
            "n_members": len(members),
            "n_direct_edges": info["n_direct_edges"],
            "n_common_edges": info["n_common_edges"],
            "total_notional": float(sub["total_notional"].sum() or 0.0),
            "total_pnl":      float(sub["realised_pnl"].sum() or 0.0),
            "members":        members,
        })
    return pl.DataFrame(rows).sort("total_notional", descending=True, nulls_last=True)
