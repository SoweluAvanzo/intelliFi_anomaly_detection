#!/usr/bin/env python
"""Behavioural ACTOR taxonomy — classify Polymarket traders by FUNCTION, not just on-chain type.

The on-chain account type is ~uniformly a proxy wallet (Gnosis Safe = email users,
Polymarket proxy = browser users, few EOAs, no AMMs, LLM-agents not on-chain-identifiable),
so bot-vs-human must come from BEHAVIOUR. Per wallet (archive, maker+taker) this computes:
  * maker_share      = maker fills / all fills           (liquidity provider vs directional)
  * n_fills, n_markets, n_categories, active_days, fills_per_active_day
  * hour_entropy     = entropy of hour-of-day activity    (24/7 automation vs human hours)
and assigns a heuristic functional label:
  market_maker (maker_share>=.7), hft_bot (fills/day>=40 & hour_entropy>=.9*max),
  arbitrageur-ish (many categories, high churn), active_trader, retail_casual, one_shot.
Then characterises each type: n, PnL, win-rate, and (if scripts/37 codes exist) account-type mix.

Heuristic + descriptive (survivorship). MEMORY-SAFE: wallet-hash bucketed (memory_limit 3GB,
spill). Launch inside systemd-run -p MemoryMax.

  python scripts/39_actor_taxonomy.py --out docs/actor_taxonomy.json --buckets 8 --memory-limit 3GB
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                              # noqa: E402
from intellifi.archive import register_archive_views      # noqa: E402
from intellifi import config as _cfg                       # noqa: E402

CODES = _cfg.DATA_DIR / "parquet" / "entity" / "codes.parquet"
HMAX = math.log(24)


def main() -> int:
    import numpy as np  # bind np at function start (a stray inner import shadows the module-level one)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/actor_taxonomy.json")
    ap.add_argument("--buckets", type=int, default=8)
    ap.add_argument("--min-fills", type=int, default=20)
    ap.add_argument("--memory-limit", default="3GB")
    args = ap.parse_args()
    NB = args.buckets

    tmp = _cfg.DATA_DIR / "_s39_tmp"; import shutil; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='60GB'")
    register_archive_views(con)

    RES = ("winning_outcome_label IS NOT NULL AND price>0 AND price<1 AND shares>0 "
           "AND taker_direction IN ('BUY','SELL')")
    WON = "(CASE WHEN outcome_label = winning_outcome_label THEN 1 ELSE 0 END)"
    PAY = f"(CASE WHEN taker_direction='BUY' THEN ({WON}-price)*shares ELSE (price-{WON})*shares END)"
    # role rows: taker (M=0) and maker (M=1)
    UNION = (f"SELECT taker w, 0 ism, condition_id m, category cat, block_timestamp bt, {PAY} pay FROM arc_raw WHERE {RES} "
             f"UNION ALL SELECT maker, 1, condition_id, category, block_timestamp, -({PAY}) FROM arc_raw WHERE {RES} AND maker IS NOT NULL")

    feats = {k: [] for k in ("w", "maker_share", "n_fills", "n_markets", "n_cat", "active_days", "hour_entropy", "pnl")}
    t0 = time.time()
    for b in range(NB):
        con.execute(f"""CREATE OR REPLACE TABLE f AS SELECT * FROM ({UNION}) t WHERE (hash(w)%{NB})={b}""")
        sc = con.sql(f"""SELECT w, avg(ism) maker_share, count(*) n_fills, count(DISTINCT m) n_markets,
                    count(DISTINCT cat) n_cat, count(DISTINCT (bt//86400)) active_days, sum(pay) pnl
                    FROM f GROUP BY w HAVING count(*)>={args.min_fills}""").df()
        # hour-of-day entropy per wallet (only for the kept wallets)
        con.execute(f"CREATE OR REPLACE TABLE keep AS SELECT w FROM f GROUP BY w HAVING count(*)>={args.min_fills}")
        hh = con.sql("""SELECT f.w w, (f.bt//3600)%24 hr, count(*) c FROM f JOIN keep k ON k.w=f.w GROUP BY 1,2""").df()
        # compute entropy per wallet
        ent = {}
        if len(hh):
            hh = hh.sort_values("w")
            wv = hh["w"].to_numpy(); cv = hh["c"].to_numpy().astype(float)
            bnd = np.flatnonzero(np.r_[True, wv[1:] != wv[:-1], True])
            for i in range(len(bnd) - 1):
                c = cv[bnd[i]:bnd[i + 1]]; p = c / c.sum()
                ent[wv[bnd[i]]] = float(-(p * np.log(p)).sum())
        for _, r in sc.iterrows():
            feats["w"].append(r["w"]); feats["maker_share"].append(r["maker_share"])
            feats["n_fills"].append(r["n_fills"]); feats["n_markets"].append(r["n_markets"])
            feats["n_cat"].append(r["n_cat"]); feats["active_days"].append(r["active_days"])
            feats["hour_entropy"].append(ent.get(r["w"], 0.0)); feats["pnl"].append(r["pnl"])
        print(f"  bucket {b+1}/{NB} ({time.time()-t0:.0f}s) wallets+={len(sc):,}", flush=True)

    w = np.array(feats["w"]); mk = np.array(feats["maker_share"], float); nf = np.array(feats["n_fills"], float)
    nm = np.array(feats["n_markets"], float); ncat = np.array(feats["n_cat"], float)
    ad = np.array(feats["active_days"], float); he = np.array(feats["hour_entropy"], float)
    pnl = np.array(feats["pnl"], float)
    fpd = nf / np.maximum(ad, 1)
    con.close(); shutil.rmtree(tmp, ignore_errors=True)

    # heuristic functional labels (priority order)
    lab = np.full(len(w), "retail_casual", dtype=object)
    lab[(nf < 40) & (nm <= 3)] = "one_shot_or_casual"
    lab[(fpd >= 15) & (nm >= 10)] = "active_trader"
    lab[(fpd >= 40) & (he >= 0.9 * HMAX)] = "hft_bot"      # high frequency + ~24/7
    lab[mk >= 0.7] = "market_maker"                         # dominates (liquidity provision)

    def summarize(mask, name):
        return {"actor_type": name, "n": int(mask.sum()),
                "mean_maker_share": float(mk[mask].mean()), "median_fills": float(np.median(nf[mask])),
                "median_fills_per_day": float(np.median(fpd[mask])), "mean_hour_entropy_frac": float(he[mask].mean()/HMAX),
                "median_n_markets": float(np.median(nm[mask])), "median_n_categories": float(np.median(ncat[mask])),
                "mean_pnl": float(pnl[mask].mean()), "median_pnl": float(np.median(pnl[mask])),
                "frac_winners": float((pnl[mask] > 0).mean()), "total_pnl": float(pnl[mask].sum())}
    types = ["market_maker", "hft_bot", "active_trader", "retail_casual", "one_shot_or_casual"]
    rep = {"scope": "archive maker+taker; behavioural actor taxonomy (heuristic, descriptive)",
           "n_wallets": int(len(w)), "min_fills": args.min_fills,
           "by_actor_type": [summarize(lab == t, t) for t in types if (lab == t).sum() >= 20],
           "note": "on-chain type is ~uniformly a proxy wallet; function is behavioural. hft_bot = >=40 fills/active-day "
                   "AND near-24/7 (hour-entropy ~ max); market_maker = maker_share>=0.7. LLM-agents & AMMs are NOT "
                   "separable on-chain (see docs/research_ideas §5). Heuristic thresholds — report the distribution too."}

    # account-type mix per actor type (if codes cache exists)
    if CODES.exists():
        import polars as pl
        codes = pl.read_parquet(CODES)
        KNOWN = {"f5c625376518f07a": "gnosis_safe", "cefa4f597e0304e1": "polymarket_proxy"}
        cd = {r["wallet"]: ("EOA" if r["is_eoa"] else KNOWN.get(r["code_hash"], "other_proxy")) for r in codes.iter_rows(named=True)}
        at = np.array([cd.get(x, "unknown") for x in w])
        for row in rep["by_actor_type"]:
            m = lab == row["actor_type"]
            sub = at[m]
            row["account_type_mix"] = {t: int((sub == t).sum()) for t in ("gnosis_safe", "polymarket_proxy", "EOA", "other_proxy") if (sub == t).sum()}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True); Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    print("actor type | n | maker_share | fills/day | 24-7 | mkts | mean_pnl | winners")
    for r in rep["by_actor_type"]:
        print(f"  {r['actor_type']:20s} n={r['n']:>7,} mk={r['mean_maker_share']:.2f} fpd={r['median_fills_per_day']:.1f} "
              f"h24={r['mean_hour_entropy_frac']:.2f} mkts={r['median_n_markets']:.0f} pnl={r['mean_pnl']:+,.0f} win={100*r['frac_winners']:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
