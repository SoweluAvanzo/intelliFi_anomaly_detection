#!/usr/bin/env python
"""Cross-market skill BREADTH — are skilled accounts skilled across MANY markets/categories, or
is their profit one lucky concentrated win? Compares skilled vs non-skilled (and, when available,
by account type from scripts/37).

For each wallet (full maker+taker, archive), from its per-(wallet, market) realised PnL d_g:
  * skill proxy z = A / sqrt(sum d_g^2)   (A = sum d_g); classify skilled = z>1.645 & k>=min.
  * BREADTH:   k = #distinct markets, ncat = #distinct categories traded.
  * CONSISTENCY: market win-rate = share of the wallet's markets with d_g>0.
  * CONCENTRATION: top-market share = max positive d_g / sum positive d_g
                   (high => one lucky win; low => profit spread across markets = skill-like).
Then compares these across skill tiers (skilled / neutral / anti-skilled) and, if
docs account codes exist, across account types.

MEMORY-SAFE: wallet-hash bucketed group-bys (memory_limit 3GB, spill). Launch in systemd-run.

  python scripts/38_skill_breadth.py --out docs/skill_breadth.json --buckets 8 --memory-limit 3GB
"""
from __future__ import annotations

import argparse
import json
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


def summ(a: np.ndarray) -> dict:
    a = a[np.isfinite(a)]
    return {"n": int(len(a)), "mean": float(a.mean()) if len(a) else None,
            "median": float(np.median(a)) if len(a) else None}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/skill_breadth.json")
    ap.add_argument("--buckets", type=int, default=8)
    ap.add_argument("--min-pos", type=int, default=10)
    ap.add_argument("--memory-limit", default="3GB")
    args = ap.parse_args()
    NB, MIN = args.buckets, args.min_pos

    tmp = _cfg.DATA_DIR / "_s38_tmp"; import shutil; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='60GB'")
    register_archive_views(con)

    RES = ("winning_outcome_label IS NOT NULL AND price>0 AND price<1 AND shares>0 "
           "AND taker_direction IN ('BUY','SELL')")
    WON = "(CASE WHEN outcome_label = winning_outcome_label THEN 1 ELSE 0 END)"
    PAY = f"(CASE WHEN taker_direction='BUY' THEN ({WON}-price)*shares ELSE (price-{WON})*shares END)"
    UNION = (f"SELECT taker AS w, condition_id AS grp, category AS cat, {PAY} AS pay FROM arc_raw WHERE {RES} "
             f"UNION ALL SELECT maker, condition_id, category, -({PAY}) FROM arc_raw WHERE {RES} AND maker IS NOT NULL")

    cols = {k: [] for k in ("w", "A", "S2", "k", "ncat", "nwon", "topshare")}
    t0 = time.time()
    for b in range(NB):
        con.execute(f"""CREATE OR REPLACE TABLE dg AS
            SELECT w, grp, SUM(pay) d, any_value(cat) cat FROM ({UNION}) t
            WHERE (hash(w)%{NB})={b} GROUP BY w, grp""")
        rows = con.sql(f"""
            SELECT w, SUM(d) A, SUM(d*d) S2, COUNT(*) k, COUNT(DISTINCT cat) ncat,
                   COUNT(*) FILTER (WHERE d>0) nwon,
                   MAX(CASE WHEN d>0 THEN d ELSE 0 END) / NULLIF(SUM(CASE WHEN d>0 THEN d ELSE 0 END),0) topshare
            FROM dg GROUP BY w HAVING COUNT(*)>={MIN} AND SUM(d*d)>0""").df()
        for c in cols:
            cols[c].append(rows[c].to_numpy())
        print(f"  bucket {b+1}/{NB} ({time.time()-t0:.0f}s)  wallets+={len(rows):,}", flush=True)

    w = np.concatenate(cols["w"]); A = np.concatenate(cols["A"]); S2 = np.concatenate(cols["S2"])
    k = np.concatenate(cols["k"]); ncat = np.concatenate(cols["ncat"]); nwon = np.concatenate(cols["nwon"])
    topshare = np.concatenate(cols["topshare"]).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.nan_to_num(A / np.sqrt(S2)); winrate = nwon / k
    con.close(); shutil.rmtree(tmp, ignore_errors=True)

    skilled = z > 1.645; anti = z < -1.645; neutral = ~skilled & ~anti
    def block(mask, name):
        return {"tier": name, "n": int(mask.sum()),
                "n_markets": summ(k[mask].astype(float)), "n_categories": summ(ncat[mask].astype(float)),
                "market_win_rate": summ(winrate[mask]), "top_market_share_of_gains": summ(topshare[mask])}
    rep = {"scope": "archive maker+taker; per-wallet cross-market breadth vs skill proxy z", "n_wallets": int(len(w)),
           "by_skill_tier": [block(skilled, "skilled(z>1.645)"), block(neutral, "neutral"), block(anti, "anti-skilled(z<-1.645)")],
           "interpretation": "skilled wallets trading MORE markets/categories with a HIGHER market win-rate and LOWER "
                             "top-market concentration => breadth = skill (not one lucky win); the reverse for anti-skilled.",
           "caveats": ["z is a sign-flip skill proxy (cross-market-correlation caveat applies as in scripts/31); "
                       "realised, outcome-dependent (survivorship)."]}

    # stratify SKILL by FINE account category (EOA / each dominant proxy code-hash / minor-proxy /
    # custom-SC) — does the level of skill rise or fall with account type?
    if CODES.exists():
        import polars as pl
        from collections import Counter
        codes = pl.read_parquet(CODES)
        # the dominant contract code-hashes = the standard proxy types (contract type 1, 2, ...)
        KNOWN = {"f5c625376518f07a": "gnosis_safe", "cefa4f597e0304e1": "polymarket_proxy"}
        hcount = Counter(r["code_hash"] for r in codes.iter_rows(named=True) if not r["is_eoa"])
        dominant = [h for h, _ in hcount.most_common(4)]
        hmap = {h: KNOWN.get(h, f"proxy_type:{h[:8]}") for h in dominant}
        def lab(r):
            if r["is_eoa"]:
                return "EOA"
            if r["code_hash"] in KNOWN:
                return KNOWN[r["code_hash"]]
            if r["code_hash"] in hmap:
                return hmap[r["code_hash"]]
            return "custom_SC_long" if r["code_len"] > 400 else "proxy_variant"
        cd = {r["wallet"]: lab(r) for r in codes.iter_rows(named=True)}
        atype = np.array([cd.get(x, "unknown") for x in w])
        rep["dominant_code_hashes"] = dominant
        rep["skill_by_account_category"] = []
        for t in sorted(set(atype)):
            m = atype == t
            if m.sum() >= 20 and t != "unknown":
                rep["skill_by_account_category"].append({"acct_category": t, "n": int(m.sum()),
                    "mean_z": float(z[m].mean()), "frac_skilled_z>1.645": float((z[m] > 1.645).mean()),
                    "frac_anti_z<-1.645": float((z[m] < -1.645).mean()),
                    "mean_pnl": float(A[m].mean()), "win_rate_markets": float(winrate[m].mean()),
                    "mean_n_markets": float(k[m].mean()), "mean_n_categories": float(ncat[m].mean()),
                    "mean_top_market_share": float(np.nanmean(topshare[m]))})
        rep["skill_by_account_category"].sort(key=lambda r: -r["frac_skilled_z>1.645"])
        rep["skill_gradient_note"] = ("categories sorted by frac_skilled; a monotone gradient (e.g. a specific "
            "proxy type or EOA carrying most of the skill, custom_SC bots at the bottom) is the headline — "
            "identify proxy_type1/2 (Gnosis Safe vs Polymarket proxy) via scripts/37 getOwners/bytecode.")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True); Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    print("by skill tier (tier | n | mean #markets | mean #cats | mkt win-rate | top-market share):")
    for r in rep["by_skill_tier"]:
        print(f"  {r['tier']:22s} n={r['n']:>8,}  mkts={r['n_markets']['mean']:.1f}  cats={r['n_categories']['mean']:.2f}  "
              f"winrate={r['market_win_rate']['mean']:.3f}  topshare={r['top_market_share_of_gains']['mean']:.3f}")
    print("SKILL by account category (category | n | frac_skilled | mean_z | mean_pnl | mkts):")
    for r in rep.get("skill_by_account_category", []):
        print(f"  {r['acct_category']:22s} n={r['n']:>7,} skilled={100*r['frac_skilled_z>1.645']:5.1f}% "
              f"z={r['mean_z']:+.3f} pnl={r['mean_pnl']:+,.0f} mkts={r['mean_n_markets']:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
