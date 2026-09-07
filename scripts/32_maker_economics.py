#!/usr/bin/env python
"""T3 — the economics of (losing) liquidity provision on the v1 archive.

The who-profits literature (Akey 2026) treats maker-share as a WINNING trait. But most
individual makers LOSE: 637k of 1.21M maker wallets are net-negative while a maker elite
captures the +$86M (concentration.json). This script characterises that:
  1. Maker PnL distribution + concentration (Gini, top-k), vs the taker side.
  2. The PROFESSIONALISATION gradient: maker mean PnL / win-rate by volume decile and by
     #-markets decile — do big/active makers win while small/amateur makers lose?
  3. ADVERSE SELECTION proxy: per maker, the size-weighted rate at which their taker
     counterparties' directional bets WON (i.e. the maker was picked off). Correlate with
     maker PnL; a high counterparty-win-rate among losing makers = adverse selection.
  4. Professionalisation over time: maker-profit concentration by year.

Realised gross PnL (v1 ~fee-free); maker PnL per fill = -(taker payoff). Outcome-dependent
(survivorship) — descriptive. MEMORY-SAFE: file-backed DuckDB, memory_limit, on-disk spill,
group-bys only (no giant materialised joins); launch inside systemd-run -p MemoryMax.

  python scripts/32_maker_economics.py --out docs/maker_economics.json --memory-limit 7GB
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                              # noqa: E402
from intellifi.archive import register_archive_views      # noqa: E402
from intellifi import config as _cfg                       # noqa: E402


def gini_pos(x: np.ndarray) -> float:
    x = np.sort(x[x > 0]); n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum())) if n else float("nan")


def decile_table(key: np.ndarray, pnl: np.ndarray, vol: np.ndarray, adv: np.ndarray, nq=10) -> list:
    """Group wallets into nq quantiles of `key`; report mean PnL, win-rate, adverse rate."""
    q = np.quantile(key, np.linspace(0, 1, nq + 1))
    q[-1] = np.inf; q[0] = -np.inf
    out = []
    idx = np.digitize(key, q[1:-1])
    for b in range(nq):
        m = idx == b
        if not m.any():
            continue
        out.append({"decile": b + 1, "n": int(m.sum()),
                    "mean_pnl": float(pnl[m].mean()), "median_pnl": float(np.median(pnl[m])),
                    "frac_winners": float((pnl[m] > 0).mean()),
                    "total_pnl": float(pnl[m].sum()),
                    "mean_counterparty_winrate": float(np.average(adv[m], weights=np.maximum(vol[m], 1)))})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/maker_economics.json")
    ap.add_argument("--memory-limit", default="7GB")
    args = ap.parse_args()

    tmp = _cfg.DATA_DIR / "_s32_tmp"; import shutil; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='60GB'")
    register_archive_views(con)

    RESOLVED = ("winning_outcome_label IS NOT NULL AND price>0 AND price<1 AND shares>0 "
                "AND taker_direction IN ('BUY','SELL') AND maker IS NOT NULL AND maker <> taker")
    WON = "(CASE WHEN outcome_label = winning_outcome_label THEN 1 ELSE 0 END)"
    TAKER_PAY = f"(CASE WHEN taker_direction='BUY' THEN ({WON}-price)*shares ELSE (price-{WON})*shares END)"
    TAKER_WON = ("(CASE WHEN (taker_direction='BUY' AND outcome_label=winning_outcome_label) "
                 "OR (taker_direction='SELL' AND outcome_label<>winning_outcome_label) THEN 1 ELSE 0 END)")

    # per-maker table: PnL (= -taker payoff), volume, #markets, #fills, size-wt counterparty win-rate
    con.execute(f"""CREATE TABLE mk AS
        SELECT maker AS w,
               SUM(-({TAKER_PAY})) AS pnl,
               SUM(usdc_amount) AS vol,
               COUNT(DISTINCT condition_id) AS nmk,
               COUNT(*) AS nfills,
               SUM(shares*{TAKER_WON})/SUM(shares) AS cp_winrate
        FROM arc_raw WHERE {RESOLVED} GROUP BY maker""")
    df = con.sql("SELECT w, pnl, vol, nmk, nfills, cp_winrate FROM mk").df()
    pnl = df["pnl"].to_numpy(); vol = df["vol"].to_numpy(); nmk = df["nmk"].to_numpy()
    adv = df["cp_winrate"].to_numpy()

    rep: dict = {"scope": "v1 archive, MAKER side; realised gross PnL (= -taker payoff); descriptive",
                 "n_makers": int(len(df)), "n_winners": int((pnl > 0).sum()), "n_losers": int((pnl < 0).sum()),
                 "total_maker_pnl": float(pnl.sum()), "gini_positive": gini_pos(pnl),
                 "median_maker_pnl": float(np.median(pnl))}
    pos = np.sort(pnl[pnl > 0])[::-1]; tot = pos.sum()
    if len(pos):
        rep["top_1pct_share_of_maker_winnings"] = float(pos[:max(1, len(pos)//100)].sum() / tot)
        rep["top_0.1pct_share"] = float(pos[:max(1, len(pos)//1000)].sum() / tot)

    # professionalisation gradient
    rep["by_volume_decile"] = decile_table(vol, pnl, vol, adv)
    rep["by_nmarkets_decile"] = decile_table(nmk.astype(float), pnl, vol, adv)

    # adverse selection: counterparty win-rate distribution + correlation with PnL
    from scipy.stats import spearmanr
    big = vol > np.quantile(vol, 0.5)   # focus on makers with material volume for the correlation
    rho, pv = spearmanr(adv[big], pnl[big])
    rep["adverse_selection"] = {
        "mean_counterparty_winrate_sizewt": float(np.average(adv, weights=np.maximum(vol, 1))),
        "interpretation": "size-wt rate at which taker counterparties' bets WON against the maker; "
                          ">0.5 => makers systematically face winning (informed) takers = adverse selection",
        "spearman_cp_winrate_vs_pnl_(vol>median)": float(rho), "spearman_p": float(pv),
        "note": "negative rho expected (higher counterparty win-rate -> lower maker PnL); the SPREAD of "
                "cp_winrate across makers, and whether a subset stays <0.5, indicates informed vs amateur makers."}

    # professionalisation over time: maker-profit concentration by year (size-wt)
    rows = con.sql(f"""
        SELECT date_part('year', to_timestamp(block_timestamp)) yr,
               COUNT(DISTINCT maker) n_makers, SUM(-({TAKER_PAY})) tot_pnl
        FROM arc_raw WHERE {RESOLVED} GROUP BY 1 ORDER BY 1""").fetchall()
    yr_gini = []
    for yr, nm, tp in rows:
        if yr is None:
            continue
        arr = con.sql(f"""SELECT SUM(-({TAKER_PAY})) p FROM arc_raw WHERE {RESOLVED}
            AND date_part('year', to_timestamp(block_timestamp))={int(yr)} GROUP BY maker""").fetchnumpy()["p"].astype(float)
        yr_gini.append({"year": int(yr), "n_makers": int(nm), "total_maker_pnl": float(tp),
                        "gini_positive": gini_pos(arr), "n_winners": int((arr > 0).sum()), "n_losers": int((arr < 0).sum())})
    rep["by_year"] = yr_gini

    rep["caveats"] = [
        "Maker = resting-order owner in the archive; mint/merge legs re-expressed from the taker are excluded "
        "(maker IS NOT NULL AND maker<>taker). Realised gross PnL, outcome-dependent (survivorship).",
        "Adverse-selection proxy is counterparty-win-rate (no order-book midprice available for a spread/AS "
        "decomposition); a subset of makers with cp_winrate<0.5 would be the informed/professional makers.",
        "v1 ~fee-free: maker economics here EXCLUDE the maker rebate/fee flows introduced in v2.",
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    print(f"makers={rep['n_makers']:,}  winners={rep['n_winners']:,}  losers={rep['n_losers']:,}  "
          f"total_pnl={rep['total_maker_pnl']:,.0f}  Gini(+)={rep['gini_positive']:.3f}  "
          f"top1%share={rep.get('top_1pct_share_of_maker_winnings',float('nan')):.3f}")
    print("PnL by VOLUME decile (mean pnl / frac winners / counterparty win-rate):")
    for r in rep["by_volume_decile"]:
        print(f"  d{r['decile']:2d} n={r['n']:>8,} mean_pnl={r['mean_pnl']:>+11,.0f} winners={r['frac_winners']*100:5.1f}%  cp_win={r['mean_counterparty_winrate']:.3f}")
    a = rep["adverse_selection"]
    print(f"adverse selection: size-wt counterparty win-rate={a['mean_counterparty_winrate_sizewt']:.3f}  "
          f"Spearman(cp_win,pnl)={a['spearman_cp_winrate_vs_pnl_(vol>median)']:+.3f}")
    print("by year (maker Gini / winners / losers):")
    for r in rep["by_year"]:
        print(f"  {r['year']} makers={r['n_makers']:>8,} Gini={r['gini_positive']:.3f} W/L={r['n_winners']:,}/{r['n_losers']:,}")
    con.close(); shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
