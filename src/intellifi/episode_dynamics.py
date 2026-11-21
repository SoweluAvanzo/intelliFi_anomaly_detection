"""Episode dynamics for the RQ2 negRisk price-correction analysis.

Beyond the converged episodes that `intellifi.correction` attributes, this module measures:
  * correction speed (episode open->close duration),
  * openings that NEVER converge (ran off the family's end still open) and WHY
    (basket staleness at death, last observed gap, correctors present-but-insufficient vs absent,
     resolution-ended), plus the economics of those un-converged families (liquidity, gap size),
  * terminal / resolution contamination measured RELATIVE to each family's traded life
    (a close in the final `1-TERM_FRAC` of life), not a fixed wall-clock window — V2 markets are so
    short that a 48h absolute window ~= the whole market life (fixed 2026-11-19),
  * composition-adjusted episode intensity: episodes per active-family-day, overall and by category,
  * volume / dollar weighting: count-vs-dollar concentration, distinctness-from-volume-leaders under
    both weightings, and volume- / peak-weighted un-converged rates.

It reuses the committed canonical builders (`correction.build_canonical` / `build_canonical_v1`) so
the open/close detector is byte-identical to the shipped RQ2 pipeline; only the bookkeeping is added.
Aggressor = `maker` field on `is_taker_order=TRUE` rows (the `taker` field is the exchange operator);
volume metrics are mint/merge-clean (YES-leg-only + taker-order aggregates). See `docs/FEE_EFFECTS.md`.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from . import config as _cfg
from . import correction as _corr

HIGH, LOW, MIN_CAND, STALE = _corr.HIGH, _corr.LOW, _corr.MIN_CAND, _corr.STALE
TERM_FRAC = 0.9            # relative terminal: episode closes in the final (1-TERM_FRAC) of family life
CLEAN_MAX_DUR = 7 * 86400  # clean subset: non-terminal and duration <= 7 days
RES_WIN = 48 * 3600        # v2 only: close within this of true resolved_ts (secondary, lifespan-caveated)
# committed RQ2 closed-episode counts for the loop-replication gate; v1 is set once the deterministic
# build is re-established (build_canonical_v1 ORDER BY fix), then pinned here.
COMMITTED = {"v2": 210993, "v1": 365587}  # deterministic after build_canonical_v1 ORDER BY+is_buy fix

# feeRate by clob primary tag — mirror of intellifi.rebate._FEERATE (verified 2026-11-19).
_FEERATE = {"crypto": 0.07, "sports": 0.05, "finance": 0.04, "politics": 0.04, "tech": 0.04,
            "mentions": 0.04, "geopolitics": 0.0, "world": 0.0}


def feerate(cat):
    return _FEERATE.get(cat, 0.05) if isinstance(cat, str) else np.nan


def instrumented_loop(fid, tid, wid, ts, price, usd, ncand, high, low, min_cand, stale):
    """Same open/close logic as correction._run_loop, extended to record each episode's END time and
    corrective dollars, and to capture openings still in-episode at a family's end (never converged).
    Validated: with a deterministic canonical build it reproduces the committed closed-episode count."""
    ev_fam, ev_start, ev_end, ev_peak, ev_ncorr, ev_top = [], [], [], [], [], []
    ev_epusd, ev_topusd = [], []
    un = {k: [] for k in ("fid", "start", "last_eval", "last_da", "peak", "n_corr_wallets",
                          "corr_mag", "corr_usd", "top_wid", "top_usd", "last_trade")}
    N = len(fid); i = 0
    while i < N:
        f = fid[i]; j = i
        while j < N and fid[j] == f:
            j += 1
        nc = ncand[int(f)]
        if nc >= min_cand:
            last, lts = {}, {}
            in_ep = False; peak = 0.0; start = 0; corr_ep = {}; corr_usd = {}
            le_ts = 0; le_da = 0.0
            last_now = int(ts[j - 1])
            for k in range(i, j):
                t = int(tid[k]); now = int(ts[k]); w = int(wid[k]); p = float(price[k]); u = float(usd[k])
                full_before = len(last) == nc
                Sb = sum(last.values()) if (full_before and all(now - lts[x] <= stale for x in lts)) else None
                last[t] = p; lts[t] = now
                if len(last) < nc:
                    continue
                Sa = sum(last.values()) if all(now - lts[x] <= stale for x in lts) else None
                if Sb is None or Sa is None:
                    if Sa is not None and not in_ep and abs(Sa - 1) > high:
                        in_ep = True; peak = abs(Sa - 1); start = now; corr_ep = {}; corr_usd = {}
                        le_ts = now; le_da = abs(Sa - 1)
                    continue
                db = abs(Sb - 1); da = abs(Sa - 1); mag = db - da
                if not in_ep and da > high:
                    in_ep = True; peak = da; start = now; corr_ep = {}; corr_usd = {}
                    le_ts = now; le_da = da
                if in_ep:
                    if db > peak: peak = db
                    if da > peak: peak = da
                    if mag > 0:
                        corr_ep[w] = corr_ep.get(w, 0) + mag
                        corr_usd[w] = corr_usd.get(w, 0) + u
                    le_ts = now; le_da = da
                    if da < low:
                        top = max(corr_ep, key=corr_ep.get) if corr_ep else -1
                        ev_fam.append(int(f)); ev_start.append(start); ev_end.append(now)
                        ev_peak.append(peak); ev_ncorr.append(len(corr_ep)); ev_top.append(top)
                        ev_epusd.append(float(sum(corr_usd.values())))
                        ev_topusd.append(float(corr_usd.get(top, 0.0)) if top >= 0 else 0.0)
                        in_ep = False
            if in_ep:
                top = max(corr_ep, key=corr_ep.get) if corr_ep else -1
                un["fid"].append(int(f)); un["start"].append(start); un["last_eval"].append(le_ts)
                un["last_da"].append(le_da); un["peak"].append(peak)
                un["n_corr_wallets"].append(len(corr_ep)); un["corr_mag"].append(float(sum(corr_ep.values())))
                un["corr_usd"].append(float(sum(corr_usd.values())))
                un["top_wid"].append(top); un["top_usd"].append(float(corr_usd.get(top, 0.0)) if top >= 0 else 0.0)
                un["last_trade"].append(last_now)
        i = j
    E = pd.DataFrame({"fid": ev_fam, "start": ev_start, "end": ev_end, "peak": ev_peak,
                      "n_correctors": ev_ncorr, "top_wid": ev_top,
                      "ep_corr_usd": ev_epusd, "top_corr_usd": ev_topusd})
    U = pd.DataFrame(un)
    return E, U


# ---- analysis helpers ----

def _concentration(E):
    s = E[E.top_wid >= 0]
    w = s.groupby("top_wid").size()
    tot = int(w.sum())
    if tot == 0:
        return {"n_episodes": 0, "n_correctors": 0, "gini": None, "top10_pct": None, "top100_pct": None}
    ws = w.sort_values(ascending=False)
    return {"n_episodes": int(len(s)), "n_correctors": int((w > 0).sum()),
            "gini": round(float(_corr._gini(w.values)), 3),
            "top10_pct": round(100 * ws.head(10).sum() / tot, 1),
            "top100_pct": round(100 * ws.head(100).sum() / tot, 1)}


def _persistence(E):
    s = E[E.top_wid >= 0]
    if len(s) < 10:
        return {"spearman_h1_h2": None, "n_both_halves": 0}
    tmid = s.start.median()
    h1 = s[s.start < tmid].groupby("top_wid").size().rename("w1")
    h2 = s[s.start >= tmid].groupby("top_wid").size().rename("w2")
    P = pd.concat([h1, h2], axis=1).fillna(0); both = P[(P.w1 > 0) & (P.w2 > 0)]
    r = spearmanr(both.w1, both.w2).correlation if len(both) > 2 else float("nan")
    return {"spearman_h1_h2": round(float(r), 3) if r == r else None, "n_both_halves": int(len(both))}


def _dur_stats(sec):
    s = pd.Series(sec, dtype="float64")
    if len(s) == 0:
        return {}
    q = s.quantile([.5, .9, .99]).to_dict()
    return {"n": int(len(s)), "median_h": round(q[.5] / 3600, 3), "p90_h": round(q[.9] / 3600, 2),
            "p99_h": round(q[.99] / 3600, 1), "max_h": round(s.max() / 3600, 1),
            "frac_le_1h": round((s <= 3600).mean(), 3), "frac_le_1d": round((s <= 86400).mean(), 3),
            "frac_le_7d": round((s <= 7 * 86400).mean(), 3), "frac_gt_30d": round((s > 30 * 86400).mean(), 3)}


def _med(x):
    x = pd.Series(x, dtype="float64")
    return round(float(x.median()), 4) if len(x) else None


def _duration_volume(E):
    """Does family liquidity predict correction speed? OLS of log10(correction time, s) on
    log10(family volume) + controls, overall and by fee tier, with SE clustered by family (fid)
    when statsmodels is available. Also the median-correction-minutes-by-volume-decile curve (chart).
    Closed episodes only; the un-converged tail is the censored extreme (see economics_of_unconverged)."""
    d = E[(E.vol > 0) & (E.peak > 0)].copy()
    if len(d) < 200:
        return {}
    d["logdur"] = np.log10(d.duration.clip(lower=1) + 1)
    d["logvol"] = np.log10(d.vol.clip(lower=1))
    d["logpeak"] = np.log10(d.peak.clip(lower=1e-6))

    def fit(g):
        if len(g) < 100:
            return None
        try:
            import statsmodels.formula.api as smf
            m = smf.ols("logdur ~ logvol + logpeak + n_cand", data=g).fit(
                cov_type="cluster", cov_kwds={"groups": g.fid})
            return {"beta_logvol": round(float(m.params["logvol"]), 4),
                    "se_clustered": round(float(m.bse["logvol"]), 4),
                    "p": float(f"{m.pvalues['logvol']:.2e}"), "r2": round(float(m.rsquared), 3),
                    "n": int(m.nobs)}
        except Exception:
            X = np.column_stack([np.ones(len(g)), g.logvol, g.logpeak, g.n_cand])
            beta, *_ = np.linalg.lstsq(X, g.logdur.values, rcond=None)
            return {"beta_logvol": round(float(beta[1]), 4), "se_clustered": None, "n": int(len(g))}

    out = {"overall": fit(d),
           "by_feerate": {str(fr): fit(g) for fr, g in d.groupby("feerate") if len(g) >= 500}}
    d["vdec"] = pd.qcut(d.logvol, 10, labels=False, duplicates="drop")
    dec = d.groupby("vdec").agg(med_dur_min=("duration", lambda x: float(np.median(x)) / 60),
                                med_vol=("vol", "median"), n=("duration", "size")).reset_index()
    out["by_volume_decile"] = dec.round(2).to_dict("records")
    return out


def analyze(E, U, FAM, daily, dailycat, AGG, source, committed=None):
    """Compute the full episode-dynamics report dict from the loop outputs + per-family features."""
    fcols = ["fid", "vol", "n_wallets", "n_cand", "first_ts", "last_ts", "res_ts", "feerate", "cat"]
    E = E.merge(FAM[fcols], on="fid", how="left")
    E["duration"] = E.end - E.start
    life = (E.last_ts - E.first_ts).clip(lower=1)
    E["close_frac"] = (E.end - E.first_ts) / life           # where in the family's life the close lands
    E["terminal"] = E.close_frac >= TERM_FRAC               # RELATIVE terminal (fix 2)
    E["res_coincident"] = (E.res_ts.notna()) & (E.end >= (E.res_ts - RES_WIN))
    w2wal = dict(zip(AGG.wid, AGG.wallet))
    E["wallet"] = E.top_wid.map(lambda w: w2wal.get(w) if w >= 0 else None)

    U = U.merge(FAM[["fid", "vol", "n_wallets", "n_cand", "first_ts", "last_ts", "res_ts", "feerate", "cat"]],
                on="fid", how="left")
    U["stale_at_death"] = U.last_trade - U.last_eval
    U["still_wide"] = U.last_da > HIGH
    U["nobody_tried"] = U.n_corr_wallets == 0
    U["res_ended"] = (U.res_ts.notna()) & (U.last_eval >= (U.res_ts - RES_WIN))

    n_open = len(E) + len(U)
    clean = E[(~E.terminal) & (E.duration <= CLEAN_MAX_DUR)]
    vol_q25 = float(FAM.vol.quantile(0.25))

    # why un-converged: priority-ordered primary reason
    def classify(r):
        if source == "v2" and bool(r.res_ended):
            return "resolution_ended"
        if r.stale_at_death > STALE:
            return "went_stale"
        if (r.vol <= vol_q25) and bool(r.nobody_tried):
            return "thin_ignored"
        if r.n_corr_wallets > 0:
            return "tried_insufficient"
        return "other"
    U["reason"] = U.apply(classify, axis=1) if len(U) else pd.Series(dtype=object)

    econ = {
        "closed_families": {"median_vol_usd": _med(E.vol), "median_n_wallets": _med(E.n_wallets),
                            "median_n_cand": _med(E.n_cand), "median_peak": _med(E.peak)},
        "unconverged_families": {"median_vol_usd": _med(U.vol), "median_n_wallets": _med(U.n_wallets),
                                 "median_n_cand": _med(U.n_cand), "median_peak": _med(U.peak),
                                 "median_last_gap": _med(U.last_da)},
        "why": {
            "frac_still_wide_gt_high": round(float(U.still_wide.mean()), 3) if len(U) else None,
            "frac_nobody_tried": round(float(U.nobody_tried.mean()), 3) if len(U) else None,
            "frac_went_stale_gt48h": round(float((U.stale_at_death > STALE).mean()), 3) if len(U) else None,
            "frac_resolution_ended": (round(float(U.res_ended.mean()), 3) if source == "v2" and len(U) else None),
            "median_corr_mag_when_tried": _med(U[U.n_corr_wallets > 0].corr_mag) if len(U) else None,
        },
        "reason_breakdown": {k: round(v, 3) for k, v in U.reason.value_counts(normalize=True).to_dict().items()} if len(U) else {},
        "unconverged_vol_vs_closed_ratio": (round(_med(U.vol) / _med(E.vol), 3) if _med(E.vol) and _med(U.vol) else None),
    }

    # composition (H1 proliferation / H2 intensity / H4 lifespan) + confound-adjusted intensity
    FAM = FAM.copy(); FAM["lifespan_days"] = (FAM.last_ts - FAM.first_ts) / 86400.0
    elig = FAM[FAM.n_cand >= 3]
    tot_afd = float(daily.nf.sum())
    comp = {"n_families": int(len(FAM)), "n_families_ge3cand": int(len(elig)), "active_days": int(len(daily)),
            "active_families_per_day_mean": round(float(daily.nf.mean()), 1),
            "active_families_per_day_median": round(float(daily.nf.median()), 1),
            "fills_per_day_mean": round(float(daily.nt.mean()), 0),
            "fills_per_active_family_day": round(float(daily.nt.sum() / tot_afd), 2),
            "median_family_lifespan_days": round(float(elig.lifespan_days.median()), 3),
            "p90_family_lifespan_days": round(float(elig.lifespan_days.quantile(.9)), 2),
            "total_active_family_days": int(tot_afd),
            "episodes_per_active_family_day": round(len(E) / tot_afd, 4),
            "openings_per_active_family_day": round(n_open / tot_afd, 4)}
    afd_cat = dailycat.groupby("cat").nf.sum(); fills_cat = dailycat.groupby("cat").nt.sum()
    ep_cat = E.groupby("cat").size() if len(E) else pd.Series(dtype=int)
    comp["by_category"] = {}
    for c in afd_cat.sort_values(ascending=False).head(8).index:
        afd = float(afd_cat.get(c, 0))
        comp["by_category"][str(c)] = {
            "active_family_days": int(afd), "episodes": int(ep_cat.get(c, 0)),
            "episodes_per_active_family_day": round(ep_cat.get(c, 0) / afd, 4) if afd else None,
            "fills_per_active_family_day": round(float(fills_cat.get(c, 0)) / afd, 2) if afd else None,
            "median_lifespan_days": round(float(FAM[FAM.cat == c].lifespan_days.median()), 3),
            "feerate": float(feerate(c)) if isinstance(c, str) else None}
    # volume-weighted episode density (does the count-density gap survive dollar-weighting?)
    tot_ep_usd = float(E.ep_corr_usd.sum())
    comp["corrective_usd_total_musd"] = round(tot_ep_usd / 1e6, 2)
    comp["corrective_usd_per_active_family_day"] = round(tot_ep_usd / tot_afd, 1) if tot_afd else None
    comp["mean_corrective_usd_per_closed_episode"] = round(tot_ep_usd / len(E), 1) if len(E) else None

    # volume / dollar weighting
    Ec = E[E.top_wid >= 0]
    dcorr = Ec.groupby("top_wid").top_corr_usd.sum()
    cwin = Ec.groupby("top_wid").size()
    WD = AGG.set_index("wid").join(dcorr.rename("dcorr")).join(cwin.rename("cwin")).fillna(0.0)
    tot_dc = float(dcorr.sum()); dc_sorted = dcorr.sort_values(ascending=False)
    openings_vol = float(E.vol.fillna(0).sum() + U.vol.fillna(0).sum())
    openings_peak = float(E.peak.sum() + U.peak.sum())
    cc = _concentration(E)
    volwt = {
        "concentration_count": {"gini": cc.get("gini"), "top100_pct": cc.get("top100_pct")},
        "concentration_dollar": {
            "gini": round(float(_corr._gini(dcorr.values)), 3) if len(dcorr) else None,
            "top100_pct": round(100 * dc_sorted.head(100).sum() / tot_dc, 1) if tot_dc else None,
            "total_corrective_usd_musd": round(tot_dc / 1e6, 2)},
        "distinctness_vs_volume": {
            "spearman_count_win_vs_vol": round(float(spearmanr(WD.cwin, WD.vol).correlation), 3) if len(WD) > 2 else None,
            "spearman_dollar_corr_vs_vol": round(float(spearmanr(WD.dcorr, WD.vol).correlation), 3) if len(WD) > 2 else None},
        "unconverged_rate_count": round(len(U) / n_open, 4) if n_open else None,
        "unconverged_rate_volume_weighted": round(float(U.vol.fillna(0).sum()) / openings_vol, 4) if openings_vol else None,
        "unconverged_rate_peak_weighted": round(float(U.peak.sum()) / openings_peak, 4) if openings_peak else None,
        "median_top_corr_usd_closed": _med(E.top_corr_usd),
    }

    matched = (committed is not None) and (len(E) == committed)
    rep = {
        "source": source, "closed_matches_committed": bool(matched) if committed is not None else None,
        "committed_reference": committed,
        "n_openings": int(n_open), "n_closed": int(len(E)), "n_unconverged": int(len(U)),
        "unconverged_rate": round(len(U) / n_open, 4) if n_open else None,
        "span_days": round((E.start.max() - E.start.min()) / 86400, 1) if len(E) else None,
        "duration_closed": _dur_stats(E.duration.values),
        "peak_closed_median": _med(E.peak), "peak_unconverged_median": _med(U.peak),
        "terminal_close_frac_relative": round(float(E.terminal.mean()), 3) if len(E) else None,
        "resolution_coincident_frac": (round(float(E.res_coincident.mean()), 3) if source == "v2" and len(E) else None),
        "concentration_full": _concentration(E), "concentration_clean": _concentration(clean),
        "persistence_full": _persistence(E), "persistence_clean": _persistence(clean),
        "clean_n": int(len(clean)),
        "economics_of_unconverged": econ,
        "composition": comp,
        "duration_vs_volume": _duration_volume(E),
        "volume_weighting": volwt,
    }
    # fee-tier dose-response (within era)
    tiers = {}
    allo = pd.concat([E.assign(_c=1)[["feerate", "_c", "duration", "peak"]],
                      U.assign(_c=0, duration=np.nan)[["feerate", "_c", "duration", "peak"]]], ignore_index=True)
    for fr, g in allo.groupby("feerate", dropna=True):
        cg = g[g._c == 1]
        tiers[str(fr)] = {"n_openings": int(len(g)), "n_closed": int(len(cg)),
                          "unconverged_rate": round(1 - len(cg) / len(g), 4) if len(g) else None,
                          "median_dur_h": round(float(cg.duration.median()) / 3600, 3) if len(cg) else None,
                          "median_peak": round(float(cg.peak.median()), 4) if len(cg) else None}
    rep["fee_tier_breakdown"] = tiers
    return rep, E, U


def run(con, source: str, out_prefix: str, ts_lo: int | None = None, ts_hi: int | None = None,
        committed="__auto__") -> dict:
    """Build the canonical set (reusing correction.*), run the instrumented loop, analyze, and write
    `<out_prefix>_{episodes,unconverged}.parquet` + `<out_prefix>.json`. `con` must be a configured
    (memory-limited, spill-enabled) DuckDB connection. Optional ts_lo/ts_hi (epoch s) restrict v1 to a
    period (P1 = fee-free, ts_hi=2026-03-01); episodes straddling the cut are truncated (minor, short
    market lives). `committed` defaults to the full-era gate reference; pass None for a period subset
    (the regression gate does not apply). Returns the report dict."""
    t0 = time.time()
    sub = "negrisk_v2" if source == "v2" else "negrisk_v1"
    fills = str(_cfg.PARQUET_DIR / sub / "fills.parquet")
    clob = str(_cfg.PARQUET_DIR / "clob_markets" / "tokens.parquet")
    n = (_corr.build_canonical(con, fills) if source == "v2"
         else _corr.build_canonical_v1(con, fills, ts_lo=ts_lo, ts_hi=ts_hi))
    print(f"[{source}] canonical taker trades: {n:,}  ({time.time()-t0:.0f}s)", flush=True)

    ncand = dict(con.execute("SELECT fid, count(DISTINCT tid) FROM C GROUP BY fid").fetchall())
    AGG = con.execute("""SELECT wid, any_value(wallet) wallet, sum(usdc) vol, sum(fee) fee_paid,
        count(*) n_trades FROM C GROUP BY wid""").df()
    FAM = con.execute("""SELECT fid, sum(usdc) vol, count(*) n_trades, count(DISTINCT wid) n_wallets,
        count(DISTINCT tid) n_cand, min(ts) first_ts, max(ts) last_ts, any_value(family) AS family
        FROM C GROUP BY fid""").df()
    fam = con.execute(f"""SELECT neg_risk_market_id AS family, any_value(lower(tags[1])) cat
        FROM '{clob}' WHERE neg_risk=TRUE AND neg_risk_market_id IS NOT NULL AND neg_risk_market_id<>''
        GROUP BY neg_risk_market_id""").df()
    FAM = FAM.merge(fam, on="family", how="left")
    if source == "v2":
        res = con.execute(f"SELECT family, max(epoch(resolved_ts_utc)) res_ts FROM '{fills}' GROUP BY family").df()
        FAM = FAM.merge(res, on="family", how="left")
    else:
        FAM["res_ts"] = np.nan
    FAM["feerate"] = FAM.cat.map(feerate)

    con.register("mapcat", FAM[["fid", "cat", "feerate", "n_cand"]])
    daily = con.execute("""SELECT floor(C.ts/86400.0) d, count(DISTINCT C.fid) nf, count(*) nt
        FROM C JOIN mapcat m ON C.fid=m.fid WHERE m.n_cand>=3 GROUP BY d""").df()
    dailycat = con.execute("""SELECT floor(C.ts/86400.0) d, m.cat, m.feerate,
        count(DISTINCT C.fid) nf, count(*) nt FROM C JOIN mapcat m ON C.fid=m.fid
        WHERE m.n_cand>=3 GROUP BY 1,2,3""").df()

    a = con.execute("SELECT fid,tid,wid,ts,price,usdc FROM C ORDER BY fid, block_number, evt_index").fetchnumpy()
    ts = a["ts"].astype(np.int64)
    E, U = instrumented_loop(a["fid"].astype(np.int64), a["tid"], a["wid"], ts,
                             a["price"].astype(np.float64), a["usdc"].astype(np.float64),
                             ncand, HIGH, LOW, MIN_CAND, STALE)
    print(f"[{source}] loop: closed={len(E):,} unconverged={len(U):,}  ({time.time()-t0:.0f}s)", flush=True)

    cref = COMMITTED.get(source) if committed == "__auto__" else committed
    rep, E, U = analyze(E, U, FAM, daily, dailycat, AGG, source, committed=cref)
    Path(out_prefix).parent.mkdir(parents=True, exist_ok=True)
    E.to_parquet(f"{out_prefix}_episodes.parquet", index=False)
    U.to_parquet(f"{out_prefix}_unconverged.parquet", index=False)
    Path(f"{out_prefix}.json").write_text(json.dumps(rep, indent=2, default=float))
    gate = rep.get("closed_matches_committed")
    print(f"[{source}] gate closed_matches_committed={gate} (committed={cref})  ({time.time()-t0:.0f}s)", flush=True)
    return rep
