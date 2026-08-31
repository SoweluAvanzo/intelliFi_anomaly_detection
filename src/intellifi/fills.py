"""On-chain order-fill reconstruction via Dune (Phase 3 prototype).

Why this exists
---------------
The Data API ``/trades`` feed is the taker leg of the ~4000 most recent fills
per market. Every fill on Polymarket is also an on-chain event: the CTF
Exchange and the NegRisk CTF Exchange emit ``OrderFilled(orderHash, maker,
taker, makerAssetId, takerAssetId, makerAmountFilled, takerAmountFilled, fee)``
once per *maker order* matched, plus one record for the *taker order* itself
(whose ``taker`` field is the exchange contract). Reconstructing fills from
these events gives what the feed structurally cannot: the whole lifetime of a
market, both legs of every fill with counterparty identity, and exact block
timestamps. Dune decodes the events into
``polymarket_polygon.CTFExchange_evt_OrderFilled`` and
``polymarket_polygon.NegRiskCtfExchange_evt_OrderFilled``.

Reliability contract
--------------------
Nothing here assumes the decoding is right: :func:`reconcile_fills` tests
three invariants against data already on disk and reports them —

1. **Taker reconciliation.** Every Data API trade row must match exactly one
   taker-order record with the same ``tx_hash``, wallet, token, shares and
   price. Anything below ~100 % means a decoding or semantic error.
2. **Conservation.** Within a transaction the maker records' shares (and
   USDC) must sum to the taker-order record's.
3. **Coverage gain.** Per market: fills recovered vs sampled trades, first
   fill vs first sampled trade, unique wallets, maker-leg share — the numbers
   that say whether the reconstruction actually widens the sample.
4. **Completeness.** Gamma's ``volumeClob`` equals the sum of taker-order
   *shares* (verified to 1.000 on four complete histories, 2026-08-29): it is
   share volume at $1 face value, not USDC paid. ``share_volume_vs_gamma``
   close to 1 therefore certifies that a market's whole fill history was
   recovered; well below 1 flags missing sub-windows or a third exchange.

Storage: raw Dune rows -> ``data/raw/dune/fills/<execution_id>.jsonl``;
normalised fills -> ``data/parquet/fills/condition_id=<cid>/part.parquet``
(idempotent per market). Exchange addresses live in :data:`EXCHANGES`;
the taker-order flag is verified empirically by invariant 2, not assumed.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb
import polars as pl
import requests
from dateutil import parser as dtparser

from . import config

log = logging.getLogger(__name__)

# Polymarket exchange contracts on Polygon (lowercase). The taker-order record
# of every fill carries the exchange as `taker`; :func:`reconcile_fills`
# reports the most frequent `taker` values so a wrong address is caught
# immediately (2026-08-29: the NegRisk address was verified empirically —
# 874 taker records = 874 feed rows on the first market fetched).
EXCHANGES: dict[str, str] = {
    "ctf": "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",
    "negrisk": "0xc5d563a36ae78145c45a50134d48a1215220f80a",
}
USDC_DECIMALS = 6      # collateral and CTF shares are both 6-decimal fixed point
FILLS_DIR = config.PARQUET_DIR / "fills"
RAW_DIR = config.RAW_DIR / "dune" / "fills"

FILLS_SCHEMA: dict[str, pl.DataType] = {
    "exchange": pl.Utf8, "block_number": pl.Int64, "ts_utc": pl.Datetime("us", "UTC"),
    "tx_hash": pl.Utf8, "evt_index": pl.Int64, "order_hash": pl.Utf8,
    "maker": pl.Utf8, "taker": pl.Utf8,
    "maker_asset_id": pl.Utf8, "taker_asset_id": pl.Utf8,
    "maker_amount_raw": pl.Int64, "taker_amount_raw": pl.Int64, "fee_raw": pl.Int64,
    "token_id": pl.Utf8, "condition_id": pl.Utf8, "outcome_index": pl.Int32,
    "maker_side": pl.Utf8, "usdc": pl.Float64, "shares": pl.Float64, "price": pl.Float64,
    "is_taker_order": pl.Boolean,
}


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

FILLS_SQL_TEMPLATE = """\
-- OrderFilled events on both Polymarket exchanges for a set of outcome tokens.
-- Parameters: token_ids (comma-separated uint256 as text), start_time, end_time.
-- Free-tier friendly: uint256 semi-join (no per-row casts), no server-side sort;
-- callers keep the time window narrow (one market, chunked) to stay under 2 min.
WITH ids AS (
    SELECT CAST(trim(x) AS uint256) AS id FROM UNNEST(split('{{token_ids}}', ',')) AS t(x)
),
ctf AS (
    SELECT 'ctf' AS exchange, evt_block_time, evt_block_number, evt_tx_hash, evt_index,
           orderHash AS order_hash, maker, taker,
           CAST(makerAssetId AS varchar)       AS maker_asset_id,
           CAST(takerAssetId AS varchar)       AS taker_asset_id,
           CAST(makerAmountFilled AS varchar)  AS maker_amount_raw,
           CAST(takerAmountFilled AS varchar)  AS taker_amount_raw,
           CAST(fee AS varchar)                AS fee_raw
    FROM polymarket_polygon.CTFExchange_evt_OrderFilled
    WHERE evt_block_time >= TIMESTAMP '{{start_time}}'
      AND evt_block_time <  TIMESTAMP '{{end_time}}'
      AND (makerAssetId IN (SELECT id FROM ids) OR takerAssetId IN (SELECT id FROM ids))
),
neg AS (
    SELECT 'negrisk' AS exchange, evt_block_time, evt_block_number, evt_tx_hash, evt_index,
           orderHash AS order_hash, maker, taker,
           CAST(makerAssetId AS varchar), CAST(takerAssetId AS varchar),
           CAST(makerAmountFilled AS varchar), CAST(takerAmountFilled AS varchar), CAST(fee AS varchar)
    FROM polymarket_polygon.NegRiskCtfExchange_evt_OrderFilled
    WHERE evt_block_time >= TIMESTAMP '{{start_time}}'
      AND evt_block_time <  TIMESTAMP '{{end_time}}'
      AND (makerAssetId IN (SELECT id FROM ids) OR takerAssetId IN (SELECT id FROM ids))
)
SELECT * FROM ctf
UNION ALL
SELECT * FROM neg
"""

QUERY_PARAMETERS = [
    {"key": "token_ids", "type": "text", "value": "0"},
    {"key": "start_time", "type": "text", "value": "2025-01-01 00:00:00"},
    {"key": "end_time", "type": "text", "value": "2026-12-31 00:00:00"},
]


# ---------------------------------------------------------------------------
# Dune API client (requests-based; free tier compatible)
# ---------------------------------------------------------------------------

class DuneError(RuntimeError):
    pass


@dataclass
class DuneClient:
    api_key: str | None = None
    base: str = config.DUNE_API
    page_size: int = 20000
    poll_seconds: float = 4.0
    timeout: float = 60.0

    def __post_init__(self) -> None:
        self.api_key = self.api_key or config.DUNE_API_KEY
        if not self.api_key:
            raise DuneError("DUNE_API_KEY not set — create a free key at dune.com/settings/api "
                            "and put DUNE_API_KEY=... in the repo's .env")
        self._s = requests.Session()
        self._s.headers.update({"X-Dune-API-Key": self.api_key,
                                "User-Agent": config.USER_AGENT})

    def _req(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        url = f"{self.base}{path}"
        for attempt in range(config.HTTP_RETRIES):
            r = self._s.request(method, url, timeout=self.timeout, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                wait = config.HTTP_BACKOFF_BASE ** attempt
                log.warning("Dune %s %s -> %s, retry in %.1fs", method, path, r.status_code, wait)
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                raise DuneError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
            return r.json()
        raise DuneError(f"{method} {path}: retries exhausted")

    def create_query(self, name: str, sql: str, params: list[dict[str, Any]],
                     private: bool = False) -> int:
        """Create a saved query (needs a plan that allows query CRUD via API)."""
        body = {"name": name, "query_sql": sql, "parameters": params, "is_private": private}
        return int(self._req("POST", "/query", json=body)["query_id"])

    def update_query(self, query_id: int, sql: str, params: list[dict[str, Any]]) -> int:
        body = {"query_sql": sql, "parameters": params}
        return int(self._req("PATCH", f"/query/{query_id}", json=body)["query_id"])

    def execute(self, query_id: int, params: dict[str, Any], performance: str | None = None) -> str:
        # The free tier rejects an explicit performance tier; only send it when asked.
        body: dict[str, Any] = {"query_parameters": params}
        if performance:
            body["performance"] = performance
        return self._req("POST", f"/query/{query_id}/execute", json=body)["execution_id"]

    def wait(self, execution_id: str, max_wait: float = 1800.0) -> dict[str, Any]:
        t0 = time.time()
        while True:
            st = self._req("GET", f"/execution/{execution_id}/status")
            state = st.get("state")
            if state == "QUERY_STATE_COMPLETED":
                return st
            if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_EXPIRED"):
                raise DuneError(f"execution {execution_id} ended in {state}: {st.get('error')}")
            if time.time() - t0 > max_wait:
                raise DuneError(f"execution {execution_id} still {state} after {max_wait}s")
            time.sleep(self.poll_seconds)

    def results(self, execution_id: str) -> Iterable[dict[str, Any]]:
        offset = 0
        while True:
            page = self._req("GET", f"/execution/{execution_id}/results",
                             params={"limit": self.page_size, "offset": offset})
            rows = page.get("result", {}).get("rows", [])
            yield from rows
            nxt = page.get("next_offset")
            if not rows or nxt is None:
                return
            offset = nxt

    def run(self, query_id: int, params: dict[str, Any],
            performance: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        ex = self.execute(query_id, params, performance=performance)
        log.info("Dune execution %s started (query %s)", ex, query_id)
        self.wait(ex)
        rows = list(self.results(ex))
        log.info("Dune execution %s: %d rows", ex, len(rows))
        return ex, rows


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _hex(x: Any) -> str | None:
    """Canonical lowercase 0x-hex (addresses, hashes); case must never matter."""
    if x is None:
        return None
    s = str(x).strip()
    return s.lower() if s[:2].lower() == "0x" else s


def _ts(x: Any) -> datetime | None:
    if x is None:
        return None
    if isinstance(x, datetime):
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    d = dtparser.parse(str(x).replace(" UTC", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def token_map(markets: pl.DataFrame) -> dict[str, tuple[str, int]]:
    """token_id -> (condition_id, outcome_index) from ``markets.clob_token_ids``."""
    out: dict[str, tuple[str, int]] = {}
    for cid, toks in zip(markets["condition_id"], markets["clob_token_ids"]):
        for i, t in enumerate(list(toks) if toks is not None else []):
            out[str(t)] = (cid, i)
    return out


def normalise_fills(rows: Iterable[dict[str, Any]], tmap: dict[str, tuple[str, int]]) -> pl.DataFrame:
    """Dune ``OrderFilled`` rows -> canonical fills frame (see ``FILLS_SCHEMA``)."""
    scale = 10 ** USDC_DECIMALS
    exch = set(EXCHANGES.values())
    recs: list[dict[str, Any]] = []
    for r in rows:
        ma, ta = str(r["maker_asset_id"]), str(r["taker_asset_id"])
        m_amt, t_amt = int(r["maker_amount_raw"]), int(r["taker_amount_raw"])
        if ma == "0" and ta == "0":
            continue  # not a token fill
        maker_buys = ma == "0"                     # maker gives USDC, receives shares
        token_id = ta if maker_buys else ma
        usdc_raw, share_raw = (m_amt, t_amt) if maker_buys else (t_amt, m_amt)
        cid, oi = tmap.get(token_id, (None, None))
        shares = share_raw / scale
        recs.append({
            "exchange": r.get("exchange"),
            "block_number": int(r["evt_block_number"]),
            "ts_utc": _ts(r["evt_block_time"]),
            "tx_hash": _hex(r["evt_tx_hash"]),
            "evt_index": int(r["evt_index"]),
            "order_hash": _hex(r.get("order_hash")),
            "maker": _hex(r["maker"]), "taker": _hex(r["taker"]),
            "maker_asset_id": ma, "taker_asset_id": ta,
            "maker_amount_raw": m_amt, "taker_amount_raw": t_amt,
            "fee_raw": int(r.get("fee_raw") or 0),
            "token_id": token_id, "condition_id": cid, "outcome_index": oi,
            "maker_side": "BUY" if maker_buys else "SELL",
            "usdc": usdc_raw / scale, "shares": shares,
            "price": (usdc_raw / share_raw) if share_raw else None,
            "is_taker_order": _hex(r["taker"]) in exch,
        })
    return pl.DataFrame(recs, schema=FILLS_SCHEMA, orient="row" if recs else None)


def write_raw(rows: list[dict[str, Any]], execution_id: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    p = RAW_DIR / f"{execution_id}.jsonl"
    with p.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")
    return p


def write_fills(df: pl.DataFrame, out_root: Path = FILLS_DIR) -> list[Path]:
    """Persist one partition per condition_id (unmapped tokens -> '_unmapped')."""
    written = []
    for cid, part in df.with_columns(pl.col("condition_id").fill_null("_unmapped")).partition_by(
            "condition_id", as_dict=True).items():
        key = cid[0] if isinstance(cid, tuple) else cid
        d = out_root / f"condition_id={key}"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "part.parquet"
        (part.drop("condition_id").sort(["block_number", "evt_index"])
             .write_parquet(p, compression="zstd"))
        written.append(p)
    return written


def fetched_markets(out_root: Path = FILLS_DIR) -> set[str]:
    return {p.name.split("=", 1)[1] for p in out_root.glob("condition_id=*") if (p / "part.parquet").exists()}


def market_windows(market: dict[str, Any], window_days: int, pad_days: int = 1) -> list[tuple[str, str]]:
    """Chunk one market's trading life (created_at-pad .. close+pad) into sub-windows."""
    start = market["created_at"] - timedelta(days=pad_days)
    close = market.get("closed_time") or market["end_date"]
    end = close + timedelta(days=pad_days)
    fmt = "%Y-%m-%d %H:%M:%S"
    out: list[tuple[str, str]] = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=window_days), end)
        out.append((cur.strftime(fmt), nxt.strftime(fmt)))
        cur = nxt
    return out


def batch_window(markets: pl.DataFrame, pad_days: int = 1) -> tuple[str, str]:
    start = markets["created_at"].min() - timedelta(days=pad_days)
    end = (markets["closed_time"].fill_null(markets["end_date"]).max()) + timedelta(days=pad_days)
    fmt = "%Y-%m-%d %H:%M:%S"
    return start.strftime(fmt), end.strftime(fmt)


# ---------------------------------------------------------------------------
# Reconciliation against the Data API sample
# ---------------------------------------------------------------------------

def register_fills_view(con: duckdb.DuckDBPyConnection, fills_root: Path = FILLS_DIR) -> None:
    glob = (fills_root / "condition_id=*" / "part.parquet").as_posix()
    exch = ",".join(f"'{a}'" for a in EXCHANGES.values())
    # is_taker_order is re-derived here so partitions written before an
    # exchange-address correction stay valid.
    con.execute(f"""
        CREATE OR REPLACE VIEW fills AS
        SELECT * REPLACE (taker IN ({exch}) AS is_taker_order)
        FROM read_parquet('{glob}', hive_partitioning = true)
        WHERE condition_id <> '_unmapped';
    """)


def reconcile_fills(con: duckdb.DuckDBPyConnection, *, tol_shares: float = 1e-6,
                    tol_price: float = 1e-6) -> dict[str, pl.DataFrame]:
    """Run the three invariants; returns {'taker_match','conservation','per_market','per_wallet'}."""
    taker_match = con.sql(f"""
        WITH t AS (
            -- only markets for which fills have been fetched (partial fetches are normal)
            SELECT tx_hash, lower(proxy_wallet) AS wallet, asset_id, side, size, price, condition_id
            FROM trades
            WHERE condition_id IN (SELECT DISTINCT condition_id FROM fills)
        ),
        f AS (
            SELECT tx_hash, maker AS wallet, token_id, maker_side, shares, price
            FROM fills WHERE is_taker_order
        ),
        j AS (
            SELECT t.condition_id,
                   f.tx_hash IS NOT NULL                                           AS found,
                   f.tx_hash IS NOT NULL AND ABS(f.shares - t.size) <= {tol_shares}
                     AND ABS(f.price - t.price) <= {tol_price} AND f.maker_side = t.side AS exact
            FROM t LEFT JOIN f ON f.tx_hash = t.tx_hash AND f.wallet = t.wallet AND f.token_id = t.asset_id
        )
        SELECT condition_id, COUNT(*) AS n_trades,
               SUM(found::INT) AS n_found, SUM(exact::INT) AS n_exact,
               SUM(found::INT) / COUNT(*) AS found_rate, SUM(exact::INT) / COUNT(*) AS exact_rate
        FROM j GROUP BY 1 ORDER BY found_rate, condition_id
    """).pl()
    # A taker order can be matched against maker orders on the SAME token
    # (normal match) or on the COMPLEMENTARY token at 1 - p (mint / merge
    # match), so shares are conserved per (tx, market), not per token.
    conservation = con.sql(f"""
        WITH per_tx AS (
            SELECT tx_hash, condition_id,
                   SUM(CASE WHEN is_taker_order THEN shares END)      AS taker_shares,
                   SUM(CASE WHEN NOT is_taker_order THEN shares END)  AS maker_shares,
                   SUM(is_taker_order::INT)                            AS n_taker_records,
                   SUM((NOT is_taker_order)::INT)                      AS n_maker_records
            FROM fills GROUP BY 1, 2
        )
        SELECT COUNT(*) AS n_tx,
               SUM((n_taker_records = 1)::INT) / COUNT(*)                               AS one_taker_record_rate,
               SUM((n_taker_records = 1 AND ABS(taker_shares - maker_shares) <= {tol_shares})::INT)
                 / NULLIF(SUM((n_taker_records = 1)::INT), 0)                            AS shares_conserved_rate,
               SUM((n_taker_records = 0)::INT)                                           AS n_tx_without_taker_record,
               SUM((n_taker_records > 1)::INT)                                           AS n_tx_multiple_taker_records
        FROM per_tx
    """).pl()
    per_market = con.sql("""
        WITH f AS (
            SELECT condition_id,
                   COUNT(*) FILTER (WHERE NOT is_taker_order)                AS n_maker_fills,
                   COUNT(*) FILTER (WHERE is_taker_order)                    AS n_taker_orders,
                   -- taker-side notional: the same convention as the Data API feed
                   SUM(usdc) FILTER (WHERE is_taker_order)                   AS usdc_volume,
                   -- taker-side share volume: what Gamma reports as volumeClob
                   SUM(shares) FILTER (WHERE is_taker_order)                 AS share_volume,
                   MIN(ts_utc) AS first_fill, MAX(ts_utc) AS last_fill,
                   COUNT(DISTINCT maker)                                     AS n_wallets
            FROM fills GROUP BY 1
        ),
        t AS (
            SELECT condition_id, COUNT(*) AS n_sampled_trades, SUM(notional_usdc) AS sampled_notional,
                   MIN(ts_utc) AS first_sampled, COUNT(DISTINCT lower(proxy_wallet)) AS n_sampled_wallets
            FROM trades GROUP BY 1
        )
        SELECT m.slug, f.*, t.n_sampled_trades, t.sampled_notional, t.first_sampled, t.n_sampled_wallets,
               t.n_sampled_trades / NULLIF(f.n_taker_orders, 0)        AS taker_order_coverage,
               t.sampled_notional / NULLIF(f.usdc_volume, 0)           AS notional_coverage,
               f.share_volume / NULLIF(m.volume_clob, 0)               AS share_volume_vs_gamma,
               DATE_DIFF('hour', f.first_fill, t.first_sampled)        AS hours_of_history_recovered
        FROM f JOIN markets m USING (condition_id) LEFT JOIN t USING (condition_id)
        ORDER BY m.volume_clob DESC NULLS LAST
    """).pl()
    per_wallet = con.sql("""
        WITH u AS (SELECT lower(proxy_wallet) AS wallet FROM read_parquet('%s')),
        f AS (
            SELECT maker AS wallet,
                   COUNT(*) FILTER (WHERE is_taker_order)      AS fills_as_taker,
                   COUNT(*) FILTER (WHERE NOT is_taker_order)  AS fills_as_maker,
                   SUM(usdc)                                   AS usdc_total
            FROM fills GROUP BY 1
        ),
        s AS (SELECT lower(proxy_wallet) AS wallet, COUNT(*) AS sampled_rows FROM trades GROUP BY 1)
        SELECT u.wallet, f.fills_as_taker, f.fills_as_maker, f.usdc_total, s.sampled_rows,
               s.sampled_rows / NULLIF(f.fills_as_taker + f.fills_as_maker, 0) AS visibility_in_feed
        FROM u LEFT JOIN f USING (wallet) LEFT JOIN s USING (wallet)
        ORDER BY f.usdc_total DESC NULLS LAST
    """ % (config.PARQUET_DIR / "universe.parquet").as_posix()).pl()
    taker_addresses = con.sql("""
        SELECT taker, COUNT(*) AS n, COUNT(DISTINCT tx_hash) AS n_tx
        FROM fills GROUP BY 1 ORDER BY n DESC LIMIT 5
    """).pl().with_columns(pl.col("taker").is_in(list(EXCHANGES.values())).alias("is_known_exchange"))
    return {"taker_match": taker_match, "conservation": conservation,
            "per_market": per_market, "per_wallet": per_wallet, "taker_addresses": taker_addresses}


# ---------------------------------------------------------------------------
# Etherscan backend: per-wallet OrderFilled logs (free tier; no per-row billing)
# ---------------------------------------------------------------------------

ORDER_FILLED_TOPIC = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"
# OrderFilled(bytes32 indexed orderHash, address indexed maker, address indexed taker,
#             uint256 makerAssetId, uint256 takerAssetId, uint256 makerAmountFilled,
#             uint256 takerAmountFilled, uint256 fee)
# topics = [signature, orderHash, maker, taker]; data = 5 words (verified 2026-08-29
# on a live response: 4 topics, 5 data words).
TOPIC_MAKER, TOPIC_TAKER = 2, 3
WALLET_FILLS_DIR = config.PARQUET_DIR / "wallet_fills"
RAW_ES_DIR = config.RAW_DIR / "etherscan" / "fills"
EXCHANGE_DEPLOY_BLOCK = 30_000_000     # both exchanges post-date this Polygon block
LOG_CAP = 1000                         # Etherscan getLogs hard cap per call


def _topic_address(addr: str) -> str:
    return "0x" + "0" * 24 + addr.lower()[2:]


def decode_order_filled(log: dict[str, Any], exchange: str) -> dict[str, Any]:
    """Etherscan log -> raw row with the same keys the Dune query returns."""
    t = log["topics"]
    data = log["data"][2:]
    words = [int(data[i * 64:(i + 1) * 64], 16) for i in range(5)]
    li = log.get("logIndex") or "0x0"
    return {
        "exchange": exchange,
        "evt_block_time": datetime.fromtimestamp(int(log["timeStamp"], 16), tz=timezone.utc),
        "evt_block_number": int(log["blockNumber"], 16),
        "evt_tx_hash": log["transactionHash"],
        "evt_index": int(li, 16) if li != "0x" else 0,
        "order_hash": t[1],
        "maker": "0x" + t[2][-40:],
        "taker": "0x" + t[3][-40:],
        "maker_asset_id": str(words[0]), "taker_asset_id": str(words[1]),
        "maker_amount_raw": str(words[2]), "taker_amount_raw": str(words[3]),
        "fee_raw": str(words[4]),
    }


def fetch_logs_bisect(client, address: str, topic_pos: int, topic_val: str,
                      from_block: int, to_block: int) -> list[dict[str, Any]]:
    """All OrderFilled logs on ``address`` with topic ``topic_pos`` == value.

    Etherscan returns at most 1,000 logs per call; a full page means the range
    may be truncated, so it is split in half recursively until every leaf is
    below the cap (a two-block leaf that is still full is paged instead).
    Complete by construction; cost ≈ 2 × fills / 1,000 calls.
    """
    params = {"module": "logs", "action": "getLogs", "address": address,
              "fromBlock": from_block, "toBlock": to_block, "page": 1, "offset": LOG_CAP}
    if topic_pos == 0:                       # bare event filter (topic_val is the signature)
        params["topic0"] = topic_val
    else:
        params.update({"topic0": ORDER_FILLED_TOPIC, f"topic{topic_pos}": topic_val,
                       f"topic0_{topic_pos}_opr": "and"})
    res = client._get(params) or []
    if len(res) < LOG_CAP:
        return res
    if to_block <= from_block:
        # Single block still above the cap: page, with a hard cap and duplicate
        # detection — Etherscan repeats the last page beyond its paging window,
        # which otherwise loops forever (bug found 2026-08-30 on the v2 tape).
        rows, page, seen = list(res), 2, {(l["transactionHash"], l.get("logIndex")) for l in res}
        while page <= 10:
            more = client._get({**params, "page": page}) or []
            new = [l for l in more if (l["transactionHash"], l.get("logIndex")) not in seen]
            if not new:
                break
            rows += new
            seen.update((l["transactionHash"], l.get("logIndex")) for l in new)
            if len(more) < LOG_CAP:
                break
            page += 1
        else:
            log.warning("block %d exceeds 10 pages of logs; results may be truncated", from_block)
        return rows
    mid = (from_block + to_block) // 2
    return (fetch_logs_bisect(client, address, topic_pos, topic_val, from_block, mid)
            + fetch_logs_bisect(client, address, topic_pos, topic_val, mid + 1, to_block))


def _page_single_block(client, address: str | None, topic0: str, block: int) -> list[dict[str, Any]]:
    """Page one block that holds >= 1,000 logs (duplicate-guarded, 10-page cap)."""
    params = {"module": "logs", "action": "getLogs", "fromBlock": block, "toBlock": block,
              "topic0": topic0, "page": 1, "offset": LOG_CAP}
    if address:
        params["address"] = address
    rows: list[dict[str, Any]] = []
    seen: set = set()
    for page in range(1, 11):
        res = client._get({**params, "page": page}) or []
        new = [l for l in res if (l["transactionHash"], l.get("logIndex")) not in seen]
        if not new:
            break
        rows += new
        seen.update((l["transactionHash"], l.get("logIndex")) for l in new)
        if len(res) < LOG_CAP:
            break
    else:
        log.warning("block %d exceeds 10 pages of logs; results may be truncated", block)
    return rows


def latest_block(client) -> int:
    return int(_proxy_block_number(client), 16)


def _proxy_block_number(client) -> str:
    # proxy endpoints return {"jsonrpc":..,"result":"0x.."} without a status field
    import requests
    r = requests.get(client.base_url, params={"module": "proxy", "action": "eth_blockNumber",
                                             "apikey": client.api_key, "chainid": client.chain_id},
                     timeout=client.timeout).json()
    client.calls_made += 1
    return r["result"]


def fetch_wallet_fills(client, wallet: str, tmap: dict[str, tuple[str, int]], *,
                       from_block: int = EXCHANGE_DEPLOY_BLOCK, to_block: int | None = None,
                       out_root: Path = WALLET_FILLS_DIR, raw_root: Path = RAW_ES_DIR) -> pl.DataFrame:
    """Every OrderFilled record involving ``wallet`` (as maker or taker, both
    exchanges), persisted raw then as ``wallet_fills/<wallet>.parquet``."""
    wallet = wallet.lower()
    to_block = to_block or latest_block(client)
    logs: dict[tuple[str, int], dict[str, Any]] = {}
    for name, address in EXCHANGES.items():
        for pos in (TOPIC_MAKER, TOPIC_TAKER):
            for lg in fetch_logs_bisect(client, address, pos, _topic_address(wallet), from_block, to_block):
                row = decode_order_filled(lg, name)
                logs[(row["evt_tx_hash"].lower(), row["evt_index"])] = row
    rows = sorted(logs.values(), key=lambda r: (r["evt_block_number"], r["evt_index"]))
    raw_root.mkdir(parents=True, exist_ok=True)
    with (raw_root / f"{wallet}.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")
    df = normalise_fills(rows, tmap).with_columns(pl.lit(wallet).alias("wallet"))
    out_root.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out_root / f"{wallet}.parquet", compression="zstd")
    return df


def validate_wallet_fills_against_dune(con: duckdb.DuckDBPyConnection, wallet: str,
                                       df: pl.DataFrame) -> dict[str, Any]:
    """Compare a wallet's Etherscan fills with the Dune ``fills`` view on the
    markets Dune has covered: same (tx, log index) set, same amounts."""
    wallet = wallet.lower()
    covered = [r[0] for r in con.execute("SELECT DISTINCT condition_id FROM fills").fetchall()]
    dune = con.sql(f"""
        SELECT tx_hash, evt_index, maker, taker, maker_asset_id, taker_asset_id,
               maker_amount_raw, taker_amount_raw
        FROM fills WHERE (maker = '{wallet}' OR taker = '{wallet}')
    """).pl()
    es = df.filter(pl.col("condition_id").is_in(covered)).select(
        "tx_hash", "evt_index", "maker", "taker", "maker_asset_id", "taker_asset_id",
        "maker_amount_raw", "taker_amount_raw")
    k = ["tx_hash", "evt_index"]
    kd, ke = set(map(tuple, dune.select(k).rows())), set(map(tuple, es.select(k).rows()))
    j = es.join(dune, on=k, suffix="_d")
    same = j.filter((pl.col("maker") == pl.col("maker_d")) & (pl.col("taker") == pl.col("taker_d"))
                    & (pl.col("maker_asset_id") == pl.col("maker_asset_id_d"))
                    & (pl.col("maker_amount_raw") == pl.col("maker_amount_raw_d"))
                    & (pl.col("taker_amount_raw") == pl.col("taker_amount_raw_d"))).height
    return {"wallet": wallet, "etherscan_rows_total": df.height, "in_covered_markets": es.height,
            "dune_rows": dune.height, "only_etherscan": len(ke - kd), "only_dune": len(kd - ke),
            "matched": len(ke & kd), "identical": same}


# ---------------------------------------------------------------------------
# Polymarket v2 (2026-04-28 →): new exchanges, new event layout
# ---------------------------------------------------------------------------

EXCHANGES_V2: dict[str, str] = {
    # labelled `CTFExchange` on Blockscout; pUSD collateral 0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB
    "v2_a": "0xe111180000d2663c0091e4f400237545b87b996b",
    "v2_b": "0xe2222d279d744050d28e00520010520000310f59",
}
from eth_hash.auto import keccak as _keccak
ORDER_FILLED_V2_TOPIC = "0x" + _keccak(
    b"OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)").hex()
ORDERS_MATCHED_V2_TOPIC = "0x" + _keccak(b"OrdersMatched(bytes32,address,uint8,uint256,uint256,uint256)").hex()
FEE_CHARGED_TOPIC = "0x" + _keccak(b"FeeCharged(address,uint256)").hex()
V2_GENESIS_BLOCK = 88_000_000        # safely before 2026-04-28 on Polygon (~2.1 s blocks)
TAPE_V2_DIR = config.PARQUET_DIR / "tape_v2"
RAW_V2_DIR = config.RAW_DIR / "etherscan" / "tape_v2"


def decode_v2_log(log: dict[str, Any], exchange: str) -> dict[str, Any] | None:
    """Decode a v2 OrderFilled / OrdersMatched / FeeCharged log into one row.

    v2 OrderFilled: topics = [sig, orderHash, maker, taker]; data =
    side(uint8: 0 = BUY, 1 = SELL), tokenId, makerAmountFilled,
    takerAmountFilled, fee, builder, metadata. The taker-order record again has
    the exchange as `taker`. BUY: maker pays pUSD (makerAmountFilled) for
    shares (takerAmountFilled); SELL: the reverse.
    """
    t = log["topics"]; d = log[  "data"][2:]
    words = [int(d[i * 64:(i + 1) * 64], 16) for i in range(len(d) // 64)]
    li = log.get("logIndex") or "0x0"
    base = {"exchange": exchange, "block_number": int(log["blockNumber"], 16),
            "ts_utc": datetime.fromtimestamp(int(log["timeStamp"], 16), tz=timezone.utc),
            "tx_hash": log["transactionHash"].lower(), "evt_index": int(li, 16) if li != "0x" else 0}
    sig = t[0].lower()
    if sig == ORDER_FILLED_V2_TOPIC:
        side = "BUY" if words[0] == 0 else "SELL"
        m_amt, t_amt = words[2], words[3]
        usdc_raw, share_raw = (m_amt, t_amt) if side == "BUY" else (t_amt, m_amt)
        return {**base, "event": "OrderFilled", "order_hash": t[1], "maker": "0x" + t[2][-40:],
                "taker": "0x" + t[3][-40:], "side": side, "token_id": str(words[1]),
                "maker_amount_raw": m_amt, "taker_amount_raw": t_amt, "fee_raw": words[4],
                "builder": "0x" + f"{words[5]:064x}", "metadata": "0x" + f"{words[6]:064x}",
                "usdc": usdc_raw / 10 ** USDC_DECIMALS, "shares": share_raw / 10 ** USDC_DECIMALS,
                "price": (usdc_raw / share_raw) if share_raw else None,
                "is_taker_order": ("0x" + t[3][-40:]) in EXCHANGES_V2.values()
                                  or ("0x" + t[3][-40:]) == log["address"].lower()}
    if sig == ORDERS_MATCHED_V2_TOPIC:
        return {**base, "event": "OrdersMatched", "order_hash": t[1], "maker": "0x" + t[2][-40:],
                "taker": None, "side": "BUY" if words[0] == 0 else "SELL", "token_id": str(words[1]),
                "maker_amount_raw": words[2], "taker_amount_raw": words[3], "fee_raw": 0,
                "builder": None, "metadata": None, "usdc": None, "shares": None, "price": None,
                "is_taker_order": None}
    if sig == FEE_CHARGED_TOPIC:
        return {**base, "event": "FeeCharged", "order_hash": None, "maker": "0x" + t[1][-40:],
                "taker": None, "side": None, "token_id": None, "maker_amount_raw": words[0],
                "taker_amount_raw": 0, "fee_raw": words[0], "builder": None, "metadata": None,
                "usdc": words[0] / 10 ** USDC_DECIMALS, "shares": None, "price": None,
                "is_taker_order": None}
    return None


TAPE_V2_SCHEMA: dict[str, pl.DataType] = {
    "exchange": pl.Utf8, "block_number": pl.Int64, "ts_utc": pl.Datetime("us", "UTC"),
    "tx_hash": pl.Utf8, "evt_index": pl.Int64, "event": pl.Utf8, "order_hash": pl.Utf8,
    "maker": pl.Utf8, "taker": pl.Utf8, "side": pl.Utf8, "token_id": pl.Utf8,
    "maker_amount_raw": pl.Int64, "taker_amount_raw": pl.Int64, "fee_raw": pl.Int64,
    "builder": pl.Utf8, "metadata": pl.Utf8, "usdc": pl.Float64, "shares": pl.Float64,
    "price": pl.Float64, "is_taker_order": pl.Boolean,
}


V2_TOPICS = {"OrderFilled": ORDER_FILLED_V2_TOPIC, "OrdersMatched": ORDERS_MATCHED_V2_TOPIC,
             "FeeCharged": FEE_CHARGED_TOPIC}


def fetch_logs_cursor(client, address: str | None, topic0: str, from_block: int, to_block: int,
                      init_window: int = 200, target: int = 900) -> list[dict[str, Any]]:
    """Walk a block range forward with an adaptive window (≈1.1 calls per 1,000 logs).

    Each call requests [cur, cur + window]. If the 1,000-log cap is hit, only
    logs from blocks strictly before the last returned block are kept (that
    block may be truncated) and the walk resumes from it; the window is
    resized to the observed density. A single block that alone exceeds the
    cap is paged via :func:`fetch_logs_bisect` (which pages single blocks).
    Complete by construction: every block in the range is covered exactly once.
    """
    out: list[dict[str, Any]] = []
    cur, window = from_block, init_window
    while cur <= to_block:
        end = min(cur + window - 1, to_block)
        params = {"module": "logs", "action": "getLogs", "fromBlock": cur, "toBlock": end,
                  "topic0": topic0, "page": 1, "offset": LOG_CAP}
        if address:                       # None = signature-only query (all emitters)
            params["address"] = address
        res = client._get(params) or []
        if len(res) < LOG_CAP:
            out += res
            cur = end + 1
            window = min(max(window * 2, 1), 20_000) if len(res) < LOG_CAP // 4 else window
            continue
        last_block = max(int(l["blockNumber"], 16) for l in res)
        if last_block == cur:                     # one block holds ≥ 1,000 logs: page it
            out += _page_single_block(client, address, topic0, cur)
            cur += 1
            continue
        kept = [l for l in res if int(l["blockNumber"], 16) < last_block]
        out += kept
        density = len(kept) / max(last_block - cur, 1)          # logs per block
        window = max(1, int(target / max(density, 1e-6)))
        cur = last_block
    return out


def fetch_v2_range(client, from_block: int, to_block: int,
                   events: tuple[str, ...] = ("OrderFilled", "OrdersMatched", "FeeCharged")) -> pl.DataFrame:
    """v2 events on both exchanges for a block range (bisected).

    ``OrderFilled`` alone is sufficient for the tape: the taker-order record
    (taker = exchange) reproduces ``OrdersMatched``, and each fill carries its
    ``fee``. Measured 2026-08-29 on the first 2,000 v2 blocks (~70 min):
    166,576 OrderFilled / 64,377 OrdersMatched (= taker-order records) /
    62,562 FeeCharged, 297 distinct builders — i.e. ~3.4 M fills per day.
    """
    rows = []
    by_addr = {a: n for n, a in EXCHANGES_V2.items()}
    unknown: dict[str, int] = {}
    for topic in (V2_TOPICS[e] for e in events):
        # One signature-only stream for both exchanges (pages stay full). Any
        # other emitter of the same signature is KEPT with exchange =
        # 'other:<address>' so nothing is lost (2026-08-30: a third Polymarket
        # contract named `Exchange`, 0xe3333700…, emits it — dust self-trades in
        # June; analyses select exchange IN EXCHANGES_V2 explicitly).
        for lg in fetch_logs_cursor(client, None, topic, from_block, to_block):
            addr = lg["address"].lower()
            name = by_addr.get(addr)
            if name is None:
                unknown[addr] = unknown.get(addr, 0) + 1
                name = f"other:{addr}"
            r = decode_v2_log(lg, name)
            if r:
                rows.append(r)
    if unknown:
        log.info("v2 signature from non-exchange addresses kept as other:*: %s", unknown)
    return pl.DataFrame(rows, schema=TAPE_V2_SCHEMA, orient="row" if rows else None).sort(["block_number", "evt_index"])
