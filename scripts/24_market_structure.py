#!/usr/bin/env python
"""Stage A — market-structure breakdown: who wins, who loses, on which markets,
and how edge/efficiency differ across market categories.

This is the descriptive layer under the population-skill null (scripts/23): the
population has no persistent skill cohort *on average*, so here we characterise
the structure that average hides — per-category calibration/edge, the
concentration of winnings within each market, and a realised-PnL leaderboard —
to surface the markets worth an event-study (Stage B/C, insider-timing).

Runs on whatever INTELLIFI_SOURCE points at (use INTELLIFI_SOURCE=archive +
INTELLIFI_ARCHIVE_CIDS for the complete tape). IMPORTANT — on the archive the
`trades` view sets proxy_wallet = TAKER and side = taker_direction (archive.py),
so every wallet statistic here is the **taker / aggressor** side (directional
bettors), NOT the maker/liquidity-provider counterparty. That is the right lens
for "who wins/loses"; a maker-side view would be a separate analysis.

  A. PER-CATEGORY calibration: size-weighted realised hit-rate vs entry-implied
     price (calibration_gap = edge above the price paid), plus a per-decile
     reliability curve, per category. Answers "are some categories more/less
     efficient, or more longshot-biased, than others?".
  B. PER-MARKET winner/loser concentration: per (market, taker) realised covered
     PnL -> per market: #winners/#losers, Gini and top-1/top-5 share of the
     winnings. Summarised by category + the most concentrated markets listed
     (a few wallets capturing most of a market's winnings is a triage flag).
  C. REALISED-PnL leaderboard: covered PnL per wallet (cost-basis-aware,
     skill.wallet_pnl semantics), overall top winners/losers + per category.

Caveats (surfaced in the JSON): ranking by *realised* PnL is outcome-dependent
(survivorship — winners are defined by having won), so this is DESCRIPTIVE, not
evidence of skill (that is scripts/23's job, and it is null). Covered PnL scales
uncovered sells; on the complete archive tape uncovered sells are rare (unlike
the 4000-cap feed). Thin categories (few markets) get wide, unreliable numbers.

  INTELLIFI_SOURCE=archive INTELLIFI_ARCHIVE_CIDS=corpus.txt \
      python scripts/24_market_structure.py --out docs/market_structure.json
"""
from __future__ import annotations

import argparse
import csv
import collections
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from intellifi.warehouse import open_warehouse       # noqa: E402
from intellifi.skill import build_bets_view           # noqa: E402
from intellifi import config as _cfg                  # noqa: E402

CLOB_TOKENS = _cfg.PARQUET_DIR / "clob_markets" / "tokens.parquet"
ATLAS_MAP = _cfg.PARQUET_DIR / "atlas" / "category_to_feeclass_mapping.csv"


def gini(x: np.ndarray) -> float:
    """Gini of a non-negative vector (0 = equal, ->1 = one wallet takes all)."""
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    s = x.sum()
    if n == 0 or s <= 0:
        return float("nan")
    return float((2.0 * np.arange(1, n + 1) - n - 1).dot(x) / (n * s))


def build_category_map(con) -> int:
    """Register temp table mktcat(condition_id, category, slug) from CLOB tags
    mapped to the atlas fee-class taxonomy (primary = most-common mapped class).
    Returns the number of mapped markets. Decoupled from the archive views so it
    works identically at any scope; only the markets present in `trades` are
    mapped (so it never materialises the whole CLOB enumeration)."""
    if not CLOB_TOKENS.exists() or not ATLAS_MAP.exists():
        raise FileNotFoundError(f"need {CLOB_TOKENS} and {ATLAS_MAP} for category mapping")
    tag2cls: dict[str, str] = {}
    with open(ATLAS_MAP) as f:
        for row in csv.DictReader(f):
            tag2cls[row["category"].strip().lower()] = row["cls"].strip()
    cids = [r[0] for r in con.sql("SELECT DISTINCT lower(condition_id) AS cid FROM trades").fetchall()]
    if not cids:
        raise RuntimeError("no condition_ids in `trades`")
    in_list = ",".join("'" + c.replace("'", "") + "'" for c in cids)
    rows = con.sql(f"""
        SELECT lower(condition_id) AS condition_id,
               any_value(market_slug) AS slug,
               any_value(tags) AS tags
        FROM read_parquet('{CLOB_TOKENS.as_posix()}')
        WHERE lower(condition_id) IN ({in_list})
        GROUP BY lower(condition_id)
    """).fetchall()
    cid_l, cat_l, slug_l = [], [], []
    for cid, slug, tags in rows:
        cats = [tag2cls.get(t.strip().lower()) for t in (tags or [])]
        cats = [c for c in cats if c]
        cid_l.append(cid)
        cat_l.append(collections.Counter(cats).most_common(1)[0][0] if cats else "other")
        slug_l.append(slug)
    import polars as pl
    mdf = pl.DataFrame({"condition_id": cid_l, "category": cat_l, "slug": slug_l})
    con.register("mktcat_df", mdf.to_arrow())
    con.execute("CREATE TEMP TABLE mktcat AS SELECT * FROM mktcat_df")
    return len(cid_l)


def per_category_calibration(con) -> list[dict]:
    """Size-weighted hit-rate vs implied price per category, + reliability curve."""
    cat = con.sql("""
        SELECT c.category,
               COUNT(DISTINCT b.condition_id)                       AS n_markets,
               COUNT(DISTINCT b.proxy_wallet)                       AS n_wallets,
               COUNT(*)                                             AS n_taker_orders,
               SUM(b.size)                                          AS total_shares,
               SUM(b.size*b.implied_p)/NULLIF(SUM(b.size),0)        AS mean_implied_p,
               SUM(b.size*b.won)/NULLIF(SUM(b.size),0)              AS hit_rate,
               (SUM(b.size*b.won)-SUM(b.size*b.implied_p))/NULLIF(SUM(b.size),0) AS calibration_gap
        FROM bets b JOIN mktcat c USING (condition_id)
        WHERE b.implied_p IS NOT NULL AND b.won IS NOT NULL
        GROUP BY c.category ORDER BY total_shares DESC
    """).fetchall()
    curve = con.sql("""
        SELECT c.category, FLOOR(b.implied_p*10)::INT AS decile,
               COUNT(*) AS n,
               SUM(b.size*b.implied_p)/NULLIF(SUM(b.size),0) AS mean_p,
               SUM(b.size*b.won)/NULLIF(SUM(b.size),0)       AS hit_rate
        FROM bets b JOIN mktcat c USING (condition_id)
        WHERE b.implied_p IS NOT NULL AND b.won IS NOT NULL
        GROUP BY 1,2 ORDER BY 1,2
    """).fetchall()
    by_cat_curve: dict[str, list] = collections.defaultdict(list)
    for category, dec, n, mp, hr in curve:
        by_cat_curve[category].append({"decile": int(dec), "mean_p": mp, "hit_rate": hr,
                                       "gap": (hr - mp) if (hr is not None and mp is not None) else None,
                                       "n": int(n)})
    return [{"category": r[0], "n_markets": int(r[1]), "n_wallets": int(r[2]),
             "n_taker_orders": int(r[3]), "mean_implied_p": r[5], "hit_rate": r[6],
             "calibration_gap": r[7], "reliability_curve": by_cat_curve[r[0]]} for r in cat]


def wallet_market_pnl(con):
    """Per (taker, market) realised covered PnL (skill.wallet_pnl semantics), + category."""
    return con.sql("""
        WITH base AS (
            SELECT t.proxy_wallet, t.condition_id, t.outcome_index, t.side, t.price, t.size,
                   CASE WHEN t.outcome_index = w.winning_outcome_index THEN 1 ELSE 0 END AS outcome_won
            FROM trades t JOIN winning_outcomes w USING (condition_id)
            WHERE t.proxy_wallet IS NOT NULL AND t.price>0 AND t.price<1
              AND t.size>0 AND t.side IN ('BUY','SELL')
        ),
        pos AS (
            SELECT proxy_wallet, condition_id, outcome_index,
                   COALESCE(SUM(CASE WHEN side='BUY'  THEN size END),0) AS bought,
                   COALESCE(SUM(CASE WHEN side='SELL' THEN size END),0) AS sold,
                   COALESCE(SUM(CASE WHEN side='BUY'  THEN (outcome_won-price)*size END),0) AS pnl_buy,
                   COALESCE(SUM(CASE WHEN side='SELL' THEN (price-outcome_won)*size END),0) AS pnl_sell,
                   COUNT(*) AS n_trades
            FROM base GROUP BY 1,2,3
        ),
        covered AS (
            SELECT *, CASE WHEN sold=0 THEN 1.0 ELSE LEAST(1.0, bought/sold) END AS cf FROM pos
        )
        SELECT cov.proxy_wallet, cov.condition_id, c.category, c.slug,
               SUM(cov.pnl_buy + cov.pnl_sell*cov.cf) AS pnl,
               SUM(cov.n_trades)                      AS n_trades
        FROM covered cov JOIN mktcat c USING (condition_id)
        GROUP BY 1,2,3,4
    """).pl()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/market_structure.json")
    ap.add_argument("--top-k", type=int, default=15, help="leaderboard length")
    ap.add_argument("--top-markets", type=int, default=15, help="most-concentrated markets to list")
    ap.add_argument("--min-market-wallets", type=int, default=10,
                    help="min takers in a market to report its concentration")
    ap.add_argument("--memory-limit", default="8GB")
    args = ap.parse_args()
    import polars as pl

    con = open_warehouse(":memory:")
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute("SET preserve_insertion_order=false")
    _tmp = _cfg.DATA_DIR / "_s24_tmp"
    _tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{_tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='40GB'")
    build_bets_view(con)
    n_mapped = build_category_map(con)

    rep: dict = {"source": os.getenv("INTELLIFI_SOURCE", "parquet"),
                 "side": "taker (aggressor); makers are the counterparty and not measured here",
                 "n_markets_mapped": n_mapped}

    # A. per-category calibration
    rep["A_per_category"] = per_category_calibration(con)

    # B + C from the (wallet, market) PnL table
    wm = wallet_market_pnl(con)
    if wm.is_empty():
        print("no PnL rows", file=sys.stderr); return 2

    # B. per-market winner/loser concentration
    market_rows = []
    for (cid,), g in wm.group_by(["condition_id"]):
        pnl = g["pnl"].to_numpy()
        cat = g["category"][0]; slug = g["slug"][0]
        nw = len(pnl); pos = pnl[pnl > 0]; neg = pnl[pnl < 0]
        if nw < args.min_market_wallets:
            continue
        gsort = np.sort(pos)[::-1]
        tot_pos = float(pos.sum())
        market_rows.append({
            "condition_id": cid, "category": cat, "slug": slug,
            "n_wallets": int(nw), "n_winners": int((pnl > 0).sum()), "n_losers": int((pnl < 0).sum()),
            "total_positive_pnl": tot_pos,
            "top1_share": float(gsort[:1].sum() / tot_pos) if tot_pos > 0 else None,
            "top5_share": float(gsort[:5].sum() / tot_pos) if tot_pos > 0 else None,
            "gini_positive_pnl": gini(pos) if len(pos) else None,
        })
    mdf = pl.DataFrame(market_rows) if market_rows else pl.DataFrame()
    by_cat = []
    if not mdf.is_empty():
        for (cat,), g in mdf.group_by(["category"]):
            by_cat.append({"category": cat, "n_markets": g.height,
                           "median_top1_share": float(np.nanmedian(g["top1_share"].to_numpy())),
                           "median_gini": float(np.nanmedian(g["gini_positive_pnl"].to_numpy())),
                           "median_winner_frac": float(np.nanmedian(
                               (g["n_winners"] / g["n_wallets"]).to_numpy()))})
        by_cat.sort(key=lambda d: -d["n_markets"])
        top_conc = mdf.sort("top1_share", descending=True, nulls_last=True).head(args.top_markets)
    rep["B_market_concentration"] = {
        "min_market_wallets": args.min_market_wallets,
        "by_category": by_cat,
        "most_concentrated_markets": top_conc.to_dicts() if not mdf.is_empty() else [],
    }

    # C. realised-PnL leaderboard (overall + per category)
    overall = (wm.group_by("proxy_wallet")
               .agg(pl.col("pnl").sum().alias("pnl_covered"),
                    pl.col("condition_id").n_unique().alias("n_markets"),
                    pl.col("n_trades").sum().alias("n_trades"))
               .sort("pnl_covered", descending=True))
    def _rows(df):
        return [{"wallet": r["proxy_wallet"], "pnl_covered": r["pnl_covered"],
                 "n_markets": int(r["n_markets"]), "n_trades": int(r["n_trades"])} for r in df.to_dicts()]
    rep["C_leaderboard"] = {
        "n_wallets": overall.height,
        "total_pnl_all_wallets": float(overall["pnl_covered"].sum()),
        "top_winners": _rows(overall.head(args.top_k)),
        "top_losers": _rows(overall.tail(args.top_k).reverse()),
    }
    percat = (wm.group_by(["category", "proxy_wallet"])
              .agg(pl.col("pnl").sum().alias("pnl_covered"),
                   pl.col("condition_id").n_unique().alias("n_markets")))
    cat_top = []
    for (cat,), g in percat.group_by(["category"]):
        w = g.sort("pnl_covered", descending=True).head(3)
        cat_top.append({"category": cat,
                        "top_winners": [{"wallet": r["proxy_wallet"], "pnl_covered": r["pnl_covered"],
                                         "n_markets": int(r["n_markets"])} for r in w.to_dicts()]})
    cat_top.sort(key=lambda d: d["category"])
    rep["C_leaderboard"]["by_category_top_winners"] = cat_top

    rep["caveats"] = [
        "TAKER side only (proxy_wallet=taker on the archive); makers/liquidity providers are the "
        "uncounted counterparty and would need a separate maker-PnL analysis.",
        "PnL rankings are OUTCOME-DEPENDENT (survivorship): a 'top winner' is defined by having won, "
        "so this is DESCRIPTIVE structure, not evidence of skill — scripts/23 tests skill and is null.",
        "Covered PnL scales uncovered sells by min(1, bought/sold); rare on the complete archive tape.",
        "Thin categories (few markets) have wide, unreliable per-category numbers.",
        "Concentration Gini is over winners' positive PnL within a market (>= min_market_wallets takers).",
    ]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}  (source={rep['source']}, {n_mapped} markets, {overall.height} taker wallets)")
    print("\nA. per-category edge (size-weighted hit-rate - implied price):")
    for r in rep["A_per_category"]:
        print(f"  {r['category']:20s} n_mkts={r['n_markets']:>4} n_wallets={r['n_wallets']:>6} "
              f"implied_p={r['mean_implied_p']:.3f} hit={r['hit_rate']:.3f} gap={r['calibration_gap']:+.4f}")
    print("\nB. winner concentration by category (median top-1 share of winnings | Gini | winner frac):")
    for r in rep["B_market_concentration"]["by_category"]:
        print(f"  {r['category']:20s} n_mkts={r['n_markets']:>4} top1={r['median_top1_share']:.3f} "
              f"gini={r['median_gini']:.3f} winners={r['median_winner_frac']:.3f}")
    print(f"\nC. leaderboard: total taker PnL over {overall.height} wallets = "
          f"{rep['C_leaderboard']['total_pnl_all_wallets']:,.0f} USDC")
    print("   top 5 winners:", [f"{w['pnl_covered']:,.0f}" for w in rep["C_leaderboard"]["top_winners"][:5]])
    print("   top 5 losers: ", [f"{w['pnl_covered']:,.0f}" for w in rep["C_leaderboard"]["top_losers"][:5]])
    con.close()
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
