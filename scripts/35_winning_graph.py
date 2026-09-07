#!/usr/bin/env python
"""Winning-cluster / syndicate graph among the top winners.

Are the top winners independent sharp individuals, or a smaller number of coordinated,
cross-market operations? Build a graph over the top-K winning EOAs with two edge types:
  * FUNDING  — share a non-hub USDC funder (from scripts/34 phase fetch).
  * COTRADE  — repeatedly take the SAME market on the SAME side on the SAME day
               (co-occurrence >= --cotrade-min), the classic coordination signature.
Cluster (connected components), then characterise each cluster: size, total realised PnL,
how much of it is funding-linked vs cotrade-linked, and cross-market breadth.

Defensive: skips gracefully if inputs are missing. MEMORY-SAFE: the archive scan is
restricted to the top-K winner wallets (a small join), cotrade groups are size-capped.

  python scripts/35_winning_graph.py --graph-k 6000 --cotrade-min 3 --out docs/winning_graph.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from intellifi import config as _cfg                       # noqa: E402

ENT = _cfg.DATA_DIR / "parquet" / "entity"
WIN = ENT / "top_winners.parquet"
FUND = ENT / "funding"
USDC_E = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
USDC_NATIVE = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--graph-k", type=int, default=6000)
    ap.add_argument("--cotrade-min", type=int, default=3, help="min shared (market,side,day) co-occurrences for an edge")
    ap.add_argument("--group-cap", type=int, default=40, help="skip (market,side,day) groups with more winners than this")
    ap.add_argument("--hub-thresh", type=int, default=5)
    ap.add_argument("--memory-limit", default="3GB")
    ap.add_argument("--out", default="docs/winning_graph.json")
    args = ap.parse_args()
    if not WIN.exists():
        print(f"missing {WIN}; run scripts/34 --phase winners first"); return 0
    import polars as pl, numpy as np, networkx as nx, duckdb
    from intellifi.archive import register_archive_views

    wins = pl.read_parquet(WIN).head(args.graph_k)
    wset = wins["wallet"].to_list(); pnl = dict(zip(wset, wins["pnl"].to_list()))
    wsetl = set(wset)

    tmp = _cfg.DATA_DIR / "_s35_tmp"; import shutil; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='40GB'")
    register_archive_views(con)
    con.execute("CREATE TABLE W(w VARCHAR)")
    con.executemany("INSERT INTO W VALUES (?)", [(x,) for x in wset])

    # COTRADE: winner trades grouped by (condition, side, day); emit within-group pairs (capped)
    con.execute("""CREATE TABLE tr AS
        SELECT taker AS w, condition_id AS m, taker_direction AS side,
               CAST(block_timestamp/86400 AS BIGINT) AS day
        FROM arc_raw WHERE taker IN (SELECT w FROM W)
          AND winning_outcome_label IS NOT NULL AND taker_direction IN ('BUY','SELL')""")
    # pairs via self-join within (m,side,day); cap group size to bound the join
    con.execute(f"""CREATE TABLE grp AS
        SELECT m, side, day, count(*) c FROM (SELECT DISTINCT w,m,side,day FROM tr) GROUP BY m,side,day
        HAVING count(*) BETWEEN 2 AND {args.group_cap}""")
    pairs = con.sql(f"""
        SELECT a.w w1, b.w w2, count(*) n FROM
          (SELECT DISTINCT w,m,side,day FROM tr) a
          JOIN (SELECT DISTINCT w,m,side,day FROM tr) b
            ON a.m=b.m AND a.side=b.side AND a.day=b.day AND a.w < b.w
          JOIN grp g ON g.m=a.m AND g.side=a.side AND g.day=a.day
        GROUP BY a.w,b.w HAVING count(*) >= {args.cotrade_min}""").df()
    con.close(); shutil.rmtree(tmp, ignore_errors=True)

    # FUNDING edges: winners sharing a non-hub USDC funder
    files = glob.glob(str(FUND / "*.parquet"))
    f2w: dict = {}
    if files:
        fr = pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed")
        for row in fr.iter_rows(named=True):
            if row["wallet"] in wsetl:
                f2w.setdefault(row["funder"], set()).add(row["wallet"])
    hubs = {f for f, ws in f2w.items() if len(ws) > args.hub_thresh or f in (USDC_E, USDC_NATIVE, "0x0000000000000000000000000000000000000000")}
    fund_edges = set()
    for f, ws in f2w.items():
        if f in hubs:
            continue
        ws = sorted(ws)
        for i in range(len(ws)):
            for j in range(i + 1, len(ws)):
                fund_edges.add((ws[i], ws[j]))

    # build graph
    G = nx.Graph(); G.add_nodes_from(wset)
    for r in pairs.itertuples():
        G.add_edge(r.w1, r.w2, cotrade=int(r.n))
    n_cot = G.number_of_edges()
    for a, b in fund_edges:
        if G.has_edge(a, b):
            G[a][b]["funding"] = 1
        else:
            G.add_edge(a, b, funding=1)
    comps = [c for c in nx.connected_components(G) if len(c) > 1]
    comps.sort(key=lambda c: -sum(pnl.get(w, 0) for w in c))
    clusters = []
    for c in comps[:30]:
        sub = G.subgraph(c)
        cot = sum(1 for _, _, d in sub.edges(data=True) if "cotrade" in d)
        fnd = sum(1 for _, _, d in sub.edges(data=True) if d.get("funding"))
        clusters.append({"n_wallets": len(c), "total_pnl": float(sum(pnl.get(w, 0) for w in c)),
                         "cotrade_edges": cot, "funding_edges": fnd,
                         "both_edges": sum(1 for _, _, d in sub.edges(data=True) if "cotrade" in d and d.get("funding"))})
    rep = {"graph_k": len(wset), "cotrade_min": args.cotrade_min,
           "n_cotrade_pairs": int(n_cot), "n_funding_pairs": len(fund_edges),
           "n_funders": len(f2w), "n_hub_funders": len(hubs),
           "n_multi_wallet_clusters": len(comps),
           "wallets_in_clusters": int(sum(len(c) for c in comps)),
           "largest_cluster_wallets": [len(c) for c in comps[:10]],
           "top_clusters_by_pnl": clusters,
           "note": "COTRADE edge = >=cotrade-min shared (market,side,day); FUNDING edge = shared non-hub USDC "
                   "funder. Multi-wallet clusters that combine BOTH funding and cotrade edges are the strongest "
                   "coordinated-operation (syndicate) candidates. Funding data present for %d wallets." % (
                       len({w for ws in f2w.values() for w in ws}))}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True); Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({k: rep[k] for k in ("graph_k", "n_cotrade_pairs", "n_funding_pairs",
          "n_multi_wallet_clusters", "wallets_in_clusters", "largest_cluster_wallets")}, indent=1))
    if clusters:
        print("top clusters (wallets / pnl / cotrade / funding / both edges):")
        for c in clusters[:10]:
            print(f"  n={c['n_wallets']:>3} pnl={c['total_pnl']:>+12,.0f} cot={c['cotrade_edges']} fnd={c['funding_edges']} both={c['both_edges']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
