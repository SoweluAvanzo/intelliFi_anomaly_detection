"""Fee-vs-no-fee difference-in-differences on the episode-dynamics outcomes (the causal layer).

Treatment is each negRisk family's EMPIRICAL fee activation: the first canonical fill it carries with a
nonzero fee (ignoring spurious pre-2026 archive fees). Never-treated families never carry a fee. This is
self-contained (derived from the same fills the episodes come from), full-coverage, and exact to the
episode set — unlike `atlas/market_fee_start.parquet`, which covers only ~3% of the v2 negRisk families.

Design (pools V1+V2 episodes): an episode is `fee_active` if its start >= its family's empirical
fee_start. TWFE DiD: outcome ~ fee_active + category FE + calendar-month FE, clustered by family, with
never-treated families and not-yet-active episodes as controls; plus a never-treated placebo and an
event-study (pre-trend check). Outcomes: log correction duration (closed episodes), the un-converged
indicator (closed vs not), and the fee_active x log-volume interaction (does the fee steepen the
liquidity->speed gradient?).

Identification caveats (reported in the output): the fee largely attaches at family birth (little
within-family pre/post), so identification leans on cross-family treated-vs-never-treated differenced
over calendar time; the never-treated control is thin in V2; estimates are TWFE — Callaway-Sant'Anna /
Sun-Abraham (already cited in the paper) are the robust refinement under staggered adoption.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as _cfg

ROLLOUT_FLOOR = 1767225600          # 2026-01-01 UTC: ignore earlier (artifact) archive fees
PLACEBO_DATE = 1774915200           # 2026-03-31 UTC: pseudo-treatment date for never-treated placebo


def _treatment(con, source: str, fills: str) -> pd.DataFrame:
    """One row per family: deterministic fid (matches the canonical builder) + empirical fee_start
    (epoch s, NULL if never-treated). Reconstructs fid via dense_rank(ORDER BY family) over the same
    canonical-eligible fills the builder uses — validated to match the episode fids exactly."""
    if source == "v2":
        base = (f"SELECT family, epoch(ts_utc) ts, fee_raw fee FROM '{fills}' "
                f"WHERE is_taker_order=TRUE AND price>0 AND price<1")
    else:
        base = f"SELECT family, ts, fee FROM '{fills}' WHERE price>0 AND price<1"
    return con.execute(f"""
        SELECT family, dense_rank() OVER (ORDER BY family)-1 AS fid,
               min(CASE WHEN fee>0 AND ts>={ROLLOUT_FLOOR} THEN ts END) AS fee_start
        FROM ({base}) GROUP BY family""").df()


def _panel(con, episodes: dict, unconv: dict, fills: dict) -> pd.DataFrame:
    """Build the pooled episode-level panel (V1+V2) with family, treatment, and model variables."""
    parts = []
    cols = ["fid", "start", "first_ts", "vol", "peak", "n_cand", "cat", "unconv", "duration"]
    for src in ("v1", "v2"):
        tr = _treatment(con, src, fills[src])[["fid", "family", "fee_start"]]
        E = pd.read_parquet(episodes[src], columns=["fid", "start", "end", "first_ts", "vol", "peak", "n_cand", "cat"])
        E = E.assign(unconv=0, duration=(E.end - E.start))
        U = pd.read_parquet(unconv[src], columns=["fid", "start", "first_ts", "vol", "peak", "n_cand", "cat"])
        U = U.assign(unconv=1, duration=np.nan)
        d = pd.concat([E[cols], U[cols]], ignore_index=True)
        d = d.merge(tr, on="fid", how="left")
        d["era"] = src
        parts.append(d)
    p = pd.concat(parts, ignore_index=True)
    p = p[(p.vol > 0) & (p.peak > 0)].copy()
    p["treated"] = p.fee_start.notna().astype(int)
    p["fee_active"] = ((p.treated == 1) & (p.start >= p.fee_start)).astype(int)
    p["logvol"] = np.log10(p.vol.clip(lower=1))
    p["logpeak"] = np.log10(p.peak.clip(lower=1e-6))
    p["logdur"] = np.log10(p.duration.clip(lower=1) + 1)
    p["logage"] = np.log10(((p.start - p.first_ts) / 86400).clip(lower=0) + 1)
    p["month"] = pd.to_datetime(p.start, unit="s").dt.strftime("%Y-%m")
    return p


def _fit(formula, data, cluster):
    """OLS with family-clustered SE. Builds the design via patsy and aligns the cluster vector to the
    rows patsy keeps, so clustered SEs don't break on listwise NaN deletion."""
    import patsy
    import statsmodels.api as sm
    y, X = patsy.dmatrices(formula, data, return_type="dataframe")
    g = data.loc[X.index, cluster].values
    return sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": g})


def _coef(m, name):
    return {"beta": round(float(m.params[name]), 4), "se": round(float(m.bse[name]), 4),
            "p": float(f"{m.pvalues[name]:.2e}"), "n": int(m.nobs)}


def did(panel: pd.DataFrame) -> dict:
    """Run the DiD regressions, the never-treated placebo, and the duration event-study."""
    panel = panel.dropna(subset=["family", "cat", "month", "logvol", "logpeak", "n_cand"]).copy()
    panel["cat"] = panel.cat.astype(str)
    panel["month"] = panel.month.astype(str)
    out = {"n_episodes": int(len(panel)),
           "n_families": int(panel.family.nunique()),
           "n_treated_families": int(panel[panel.treated == 1].family.nunique()),
           "n_nevertreated_families": int(panel[panel.treated == 0].family.nunique()),
           "n_fee_active_episodes": int(panel.fee_active.sum())}

    # (1) correction duration (closed episodes only) ~ fee_active (+ interaction with log-volume)
    C = panel[panel.unconv == 0].copy()
    m1 = _fit("logdur ~ fee_active + logvol + logpeak + n_cand + C(cat) + C(month)", C, "family")
    out["duration_did"] = {"fee_active": _coef(m1, "fee_active"), "logvol": _coef(m1, "logvol"),
                           "interpretation": "fee effect on log10(correction seconds), net of volume/mix/time"}
    m1i = _fit("logdur ~ fee_active*logvol + logpeak + n_cand + C(cat) + C(month)", C, "family")
    out["duration_x_volume"] = {"fee_active:logvol": _coef(m1i, "fee_active:logvol"),
                                "interpretation": "does the fee steepen the volume->speed gradient? (negative = faster per $ under fee)"}

    # (2) un-converged probability (closed vs never-closed) ~ fee_active  (linear probability)
    m2 = _fit("unconv ~ fee_active + logvol + logpeak + n_cand + C(cat) + C(month)", panel, "family")
    out["unconverged_did"] = {"fee_active": _coef(m2, "fee_active"),
                              "interpretation": "fee effect on P(never converges), net of volume/mix/time"}

    # (3) never-treated placebo: pseudo-treatment at a fixed date on control families only
    ctrl = panel[panel.treated == 0].copy()
    ctrl["fee_active"] = (ctrl.start >= PLACEBO_DATE).astype(int)
    Cc = ctrl[ctrl.unconv == 0]
    try:
        mp = _fit("logdur ~ fee_active + logvol + logpeak + n_cand + C(cat) + C(month)", Cc, "family")
        out["placebo_duration"] = {"fee_active(pseudo)": _coef(mp, "fee_active"),
                                   "expect": "~0 if the DiD is not picking up a secular trend"}
    except Exception as e:
        out["placebo_duration"] = {"error": str(e)[:160]}

    # (4) event-study on duration: months relative to fee_start (treated families), pre-trend check
    T = panel[(panel.treated == 1) & (panel.unconv == 0)].copy()
    T["evt"] = ((T.start - T.fee_start) / (30 * 86400)).round().clip(-4, 4).astype(int)
    T = T[T.evt != -1]  # omit t=-1 as the reference period
    try:
        me = _fit("logdur ~ C(evt) + logvol + logpeak + n_cand + C(cat) + C(month)", T, "family")
        es = {}
        for k in me.params.index:
            if k.startswith("C(evt)[T."):
                lab = k.split("T.")[1].rstrip("]")
                es[lab] = round(float(me.params[k]), 4)
        out["event_study_duration"] = {"ref": "t=-1", "coef_by_month": es,
                                       "read": "flat before t=0 = parallel pre-trends; jump at/after t>=0 = effect"}
    except Exception as e:
        out["event_study_duration"] = {"error": str(e)[:160]}

    out["caveats"] = [
        "Treatment = empirical family fee-activation; fee largely attaches at birth, so identification is "
        "mostly cross-family (treated vs never-treated) differenced over calendar months, not within-family.",
        "Never-treated control is large in V1 but thin in V2 (94 families).",
        "TWFE under staggered adoption; Callaway-Sant'Anna / Sun-Abraham are the robust refinement.",
        "Un-converged DiD is a linear probability model; duration is on closed episodes (censored tail = unconv).",
    ]
    return out


def _fit_within(data, y, xs, group, timefe):
    """Within-group (family-FE) OLS with time dummies and group-clustered SE, via vectorized demeaning.
    Identifies `fee_active` only from families observed both pre- and post-their-fee-start (the clean DiD)."""
    import statsmodels.api as sm
    d = data[[group, timefe, y] + xs].dropna().reset_index(drop=True)
    td = pd.get_dummies(d[timefe], prefix="t", drop_first=True).astype(float)
    frame = pd.concat([d[[y] + xs].astype(float), td], axis=1)
    g = d[group].values
    dem = frame - frame.groupby(g).transform("mean")
    m = sm.OLS(dem[y], dem.drop(columns=[y])).fit(cov_type="cluster", cov_kwds={"groups": g})
    return {"fee_active": {"beta": round(float(m.params["fee_active"]), 4), "se": round(float(m.bse["fee_active"]), 4),
            "p": float(f"{m.pvalues['fee_active']:.2e}"), "n_obs": int(m.nobs)}}


def did_refined(panel: pd.DataFrame) -> dict:
    """Refined DiD: restrict to the V1 rollout window (breaks the V1->V2 data-boundary confound), add a
    family-age control (kills the long-lived-family selection the naive event-study picked up), add a
    within-family (family-FE) estimate from the switcher families (clean DiD), and run level + interaction
    placebos. Trust fee_active only if both placebos are ~0."""
    WIN_LO = 1767225600  # 2026-01-01; V1 is pre-cutover by construction
    p = panel[(panel.era == "v1") & (panel.start >= WIN_LO)].copy()
    p = p.dropna(subset=["family", "cat", "logvol", "logpeak", "n_cand", "logage"]).copy()
    p["cat"] = p.cat.astype(str)
    p["week"] = pd.to_datetime(p.start, unit="s").dt.strftime("%Y-%U")
    byf = p[p.treated == 1].groupby("family").fee_active.agg(["min", "max"])
    n_switch = int(((byf["min"] == 0) & (byf["max"] == 1)).sum())
    out = {"window": "V1, start>=2026-01-01", "n_episodes": int(len(p)),
           "n_treated_families": int(p[p.treated == 1].family.nunique()),
           "n_nevertreated_families": int(p[p.treated == 0].family.nunique()),
           "treated_families_with_within_variation": n_switch}
    C = p[p.unconv == 0]
    m1 = _fit("logdur ~ fee_active + logvol + logpeak + logage + n_cand + C(cat) + C(week)", C, "family")
    out["duration_did_pooled"] = {"fee_active": _coef(m1, "fee_active")}
    m1i = _fit("logdur ~ fee_active*logvol + logpeak + logage + n_cand + C(cat) + C(week)", C, "family")
    out["duration_x_volume_pooled"] = {"fee_active:logvol": _coef(m1i, "fee_active:logvol")}
    if n_switch >= 30:
        try:
            out["duration_within_family_fe"] = _fit_within(C, "logdur",
                ["fee_active", "logvol", "logpeak", "logage"], "family", "week")
        except Exception as e:
            out["duration_within_family_fe"] = {"error": str(e)[:150]}
    else:
        out["duration_within_family_fe"] = {"note": f"only {n_switch} within-variation families — within DiD underpowered"}
    m2 = _fit("unconv ~ fee_active + logvol + logpeak + logage + n_cand + C(cat) + C(week)", p, "family")
    out["unconverged_did_pooled"] = {"fee_active": _coef(m2, "fee_active")}
    ctrl = p[p.treated == 0].copy(); ctrl["fee_active"] = (ctrl.start >= PLACEBO_DATE).astype(int)
    Cc = ctrl[ctrl.unconv == 0]
    try:
        mp = _fit("logdur ~ fee_active + logvol + logpeak + logage + n_cand + C(cat) + C(week)", Cc, "family")
        out["placebo_level"] = _coef(mp, "fee_active")
        mpi = _fit("logdur ~ fee_active*logvol + logpeak + logage + n_cand + C(cat) + C(week)", Cc, "family")
        out["placebo_interaction"] = _coef(mpi, "fee_active:logvol")
    except Exception as e:
        out["placebo"] = {"error": str(e)[:150]}
    out["caveats"] = [
        "Restricted to V1 pre-cutover rollout window to avoid the V1/V2 data-boundary confound.",
        "logage control absorbs the long-lived-family selection the naive event-study picked up.",
        "duration_within_family_fe uses only families observed both pre- and post-their-fee-start = the "
        "clean DiD; if few switchers (fee attaches near birth) it is the binding limit on identification.",
        "Trust fee_active only if BOTH placebo_level and placebo_interaction are ~0.",
    ]
    return out


def run(con, out_path: str, episodes: dict | None = None, unconv: dict | None = None,
        fills: dict | None = None) -> dict:
    """Load both eras' episode-dynamics outputs, build the panel, run the DiD, write `out_path` JSON."""
    exp = _cfg.DATA_DIR / "export"
    episodes = episodes or {s: str(exp / f"episode_dynamics_{s}_episodes.parquet") for s in ("v1", "v2")}
    unconv = unconv or {s: str(exp / f"episode_dynamics_{s}_unconverged.parquet") for s in ("v1", "v2")}
    fills = fills or {s: str(_cfg.PARQUET_DIR / f"negrisk_{s}" / "fills.parquet") for s in ("v1", "v2")}
    panel = _panel(con, episodes, unconv, fills)
    rep = {"baseline": did(panel), "refined": did_refined(panel)}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(rep, indent=2, default=float))
    return rep
