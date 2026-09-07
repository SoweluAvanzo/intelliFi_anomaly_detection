#!/usr/bin/env python
"""T1 — entity-level concentration via the on-chain USDC funding graph.

The who-profits papers (Akey 2026, Gomez-Cram 2026) measure concentration at the WALLET
level. Polymarket trading wallets are EOAs (onchain.py: 100% EOA in the top-trader sample),
so beneficial ownership is inferred from **shared USDC funding** (the established method here,
CLAUDE.md). We collapse the concentration TAIL (top winners) to entities and re-measure.

Phases (idempotent; run --phase winners, then fetch, then cluster):
  winners  — top-K winning EOAs (taker+maker realised net PnL) from the archive -> parquet.
  fetch    — inbound USDC.e + native-USDC transfers for each (Polygonscan); the SENDERS are
             the funders. Skip-if-exists; penalty-aware; vetted keys only.
  cluster  — funder->wallet bipartite graph; DROP hub funders (CEX/bridge/relayer: degree >
             --hub-thresh); link wallets sharing a low-degree funder + direct wallet<->wallet
             USDC transfers; connected components = entities. Re-measure top-K concentration
             at the entity level vs the wallet level.

PoC / correctness: run with a small --top-k first, inspect cluster sizes and the funder
degree distribution, confirm EOAs and that hubs are being excluded, THEN scale.

MEMORY-SAFE: phase `winners` is a group-by over the archive (file-backed DuckDB, spill);
`fetch`/`cluster` are network/graph (light). Launch `winners` inside systemd-run -p MemoryMax.

  python scripts/34_entity_funding.py --phase winners --top-k 500
  python scripts/34_entity_funding.py --phase fetch   --top-k 500
  python scripts/34_entity_funding.py --phase cluster --top-k 500 --hub-thresh 5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from intellifi import config as _cfg                       # noqa: E402

ENT = _cfg.DATA_DIR / "parquet" / "entity"
FUND = ENT / "funding"
WIN = ENT / "top_winners.parquet"
USDC_E = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"       # bridged USDC.e (Polygon)
USDC_NATIVE = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"  # native USDC (Polygon)


def phase_winners(top_k: int, mem: str) -> None:
    import duckdb
    from intellifi.archive import register_archive_views
    ENT.mkdir(parents=True, exist_ok=True)
    tmp = _cfg.DATA_DIR / "_s34_tmp"; import shutil; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{mem}'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='60GB'")
    register_archive_views(con)
    RES = ("winning_outcome_label IS NOT NULL AND price>0 AND price<1 AND shares>0 "
           "AND taker_direction IN ('BUY','SELL')")
    WON = "(CASE WHEN outcome_label = winning_outcome_label THEN 1 ELSE 0 END)"
    PAY = f"(CASE WHEN taker_direction='BUY' THEN ({WON}-price)*shares ELSE (price-{WON})*shares END)"
    # combined per-wallet net PnL across BOTH roles (taker:+PAY, maker:-PAY)
    con.execute(f"""CREATE TABLE wp AS
        SELECT w, SUM(p) pnl FROM (
          SELECT taker w, {PAY} p FROM arc_raw WHERE {RES}
          UNION ALL SELECT maker w, -({PAY}) p FROM arc_raw WHERE {RES} AND maker IS NOT NULL) GROUP BY w""")
    con.execute(f"COPY (SELECT w AS wallet, pnl FROM wp WHERE w IS NOT NULL ORDER BY pnl DESC LIMIT {top_k}) "
                f"TO '{WIN.as_posix()}' (FORMAT PARQUET)")
    n = con.sql(f"SELECT count(*) FROM read_parquet('{WIN.as_posix()}')").fetchone()[0]
    print(f"wrote {WIN} : top {n} winners (combined taker+maker net PnL)")
    con.close(); shutil.rmtree(tmp, ignore_errors=True)


def phase_fetch(top_k: int, max_pages: int) -> None:
    import polars as pl
    from intellifi.onchain import Polygonscan, PolygonRPC, resolve_controller
    rem = Polygonscan.penalty_active()
    if rem > 0:
        print(f"IP penalty active ({rem:.0f} min left) — refusing to fetch. Delete data/logs/.ip_penalty to force."); return
    import os
    FUND.mkdir(parents=True, exist_ok=True)
    wins = pl.read_parquet(WIN).head(top_k)["wallet"].to_list()
    # CRAWL_KEYS are env NAMES (vetted-valid allowlist); resolve to values
    keys = [os.getenv(name) for name in _cfg.CRAWL_KEYS]
    keys = [k for k in keys if k]
    if not keys:
        print("no vetted keys in env (CRAWL_KEYS)"); return
    print(f"using {len(keys)} vetted key(s); fetching funders for {len(wins)} winners")
    rpc = PolygonRPC()
    n_eoa = n_contract = fetched = skipped = 0
    for i, w in enumerate(wins):
        out = FUND / f"{w}.parquet"
        if out.exists():
            skipped += 1; continue
        os.environ["POLYGONSCAN_API_KEY"] = keys[i % len(keys)]
        cli = Polygonscan.from_env()
        rows = []
        try:
            for c in (USDC_E, USDC_NATIVE):
                for t in cli.erc20_transfers_all(w, contract_address=c, max_pages=max_pages):
                    if t.get("to", "").lower() == w.lower():        # INBOUND only -> `from` is a funder
                        rows.append({"wallet": w, "funder": t["from"].lower(), "token": c,
                                     "value": float(t.get("value", 0)) / 1e6, "block": int(t["blockNumber"])})
            if i < 10:   # spot-check EOA vs contract on the first few
                code = rpc.get_code(w)
                n_eoa += int(code in ("0x", "0x0", "")); n_contract += int(code not in ("0x", "0x0", ""))
        except Exception as e:
            print(f"  {w[:10]}.. error: {e}")
            continue
        pl.DataFrame(rows, schema={"wallet": pl.Utf8, "funder": pl.Utf8, "token": pl.Utf8,
                                   "value": pl.Float64, "block": pl.Int64}).write_parquet(out)
        fetched += 1
        if i % 50 == 0:
            print(f"  {i+1}/{len(wins)}  fetched={fetched} skipped={skipped}", flush=True)
    print(f"fetch done: fetched={fetched} skipped={skipped}; EOA spot-check first-10: {n_eoa} EOA / {n_contract} contract")


def phase_cluster(top_k: int, hub_thresh: int, out: str) -> None:
    import polars as pl, numpy as np, networkx as nx, glob
    from collections import Counter
    wins = pl.read_parquet(WIN).head(top_k)
    wset = set(wins["wallet"].to_list())
    files = glob.glob(str(FUND / "*.parquet"))
    fr = pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed") if files else pl.DataFrame()
    # funder -> set of our winner-wallets it funded
    f2w: dict = {}
    for row in fr.iter_rows(named=True):
        if row["wallet"] in wset:
            f2w.setdefault(row["funder"], set()).add(row["wallet"])
    deg = {f: len(ws) for f, ws in f2w.items()}
    hubs = {f for f, d in deg.items() if d > hub_thresh or f in (USDC_E, USDC_NATIVE) or f == "0x0000000000000000000000000000000000000000"}
    G = nx.Graph(); G.add_nodes_from(wset)
    linked_edges = 0
    for f, ws in f2w.items():
        if f in hubs:
            continue
        ws = list(ws)
        for a in range(len(ws)):
            for b in range(a + 1, len(ws)):
                G.add_edge(ws[a], ws[b]); linked_edges += 1
    comps = list(nx.connected_components(G))
    sizes = sorted((len(c) for c in comps), reverse=True)
    # concentration re-measure: winnings at wallet vs entity level
    pnl = dict(zip(wins["wallet"].to_list(), wins["pnl"].to_list()))
    ent_pnl = [sum(pnl.get(w, 0) for w in c) for c in comps]
    rep = {"top_k": int(len(wins)), "n_wallets": len(wset), "n_entities": len(comps),
           "n_multi_wallet_entities": int(sum(1 for s in sizes if s > 1)),
           "wallets_in_multi_entities": int(sum(s for s in sizes if s > 1)),
           "frac_winner_diversity_that_is_sybil": float(1 - len(comps) / max(len(wset), 1)),
           "largest_entity_wallets": sizes[:10],
           "n_funders_total": len(deg), "n_hub_funders_excluded": len(hubs),
           "hub_thresh": hub_thresh, "funder_degree_top": Counter(deg).most_common(10),
           "linkage_edges": linked_edges,
           "top_entities_by_pnl": sorted(
               [{"n_wallets": len(c), "entity_pnl": float(p)} for c, p in zip(comps, ent_pnl)],
               key=lambda r: -r["entity_pnl"])[:15],
           "note": "funder=shared USDC sender (inbound). Hubs (CEX/bridge/relayer, degree>thresh) excluded. "
                   "Multi-wallet entities => the wallet-level winner count OVERSTATES independent winners; "
                   "frac_sybil = 1 - n_entities/n_wallets is the collapse."}
    Path(out).parent.mkdir(parents=True, exist_ok=True); Path(out).write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({k: rep[k] for k in ("top_k", "n_wallets", "n_entities", "n_multi_wallet_entities",
          "wallets_in_multi_entities", "frac_winner_diversity_that_is_sybil", "largest_entity_wallets",
          "n_hub_funders_excluded")}, indent=1))
    print(f"wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=["winners", "fetch", "cluster"], required=True)
    ap.add_argument("--top-k", type=int, default=500)
    ap.add_argument("--hub-thresh", type=int, default=5)
    ap.add_argument("--max-pages", type=int, default=4)
    ap.add_argument("--memory-limit", default="7GB")
    ap.add_argument("--out", default="docs/entity_concentration.json")
    args = ap.parse_args()
    if args.phase == "winners":
        phase_winners(args.top_k, args.memory_limit)
    elif args.phase == "fetch":
        phase_fetch(args.top_k, args.max_pages)
    else:
        phase_cluster(args.top_k, args.hub_thresh, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
