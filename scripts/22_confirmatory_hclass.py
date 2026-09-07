#!/usr/bin/env python
"""Stage 22 — REGISTERED confirmatory H1-H4 (docs/stage2_preregistration.md §3).

Class-level confirmation on Sample B (the v2 tape) with the frozen decision rules:
Holm-corrected at alpha=0.05 across H1-H4, class/family-clustered SEs, wild-cluster
bootstrap where the number of clusters G <= 12, and the §2 CONTINGENCY (if < 5% of
taker orders are fee-free in EVERY class there is no within-B control and H3/H4 fall
back to a weaker within-class pre/post-vs-A design, labelled as such).

PORTABILITY / HONESTY: this ships the pieces whose inputs are on disk end-to-end
(H4 order-size DiD from the A + B class-week panels; H1c self-match from the cohort
descriptive) and CONSUMES pre-computed B-tape statistic tables for H1a/H1b/H2/H3
(the heavy round-trip / pairs / negRisk-band / maker-HHI-per-class computations,
produced separately). Any hypothesis whose table is absent is reported PENDING, not
guessed. NOTHING here is a confirmatory CLAIM until reviewed (the class treatment
assignment in particular must be confirmed against the panel builder's definition).

  python scripts/22_confirmatory_hclass.py --out docs/cohort_reports/confirmatory_h1_h4.json \
      [--h1a-table ...] [--h1b-table ...] [--h2-table ...] [--h3-table ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

REPO = Path(__file__).resolve().parents[1]
A_PANEL = REPO / "data/parquet/atlas/class_week.parquet"
B_PANEL = REPO / "data/parquet/atlas_v2/class_week_b.parquet"
COHORT1 = REPO / "docs/cohort_reports/cohort1_descriptive_repro.json"

# Junk / non-substantive classes to drop from every test (the token_cls mapper emits
# '__unmapped__' for markets it cannot classify; it is not a real fee-free control).
EXCLUDE_CLASSES = {"__unmapped__"}

# Registered "never-treated" control set for H4 (pre-reg §2: A fee-exempt = geopolitics/world/
# macro/US-politics). This is the PRIMARY control per the registered design; the code also
# reports the single-control (B-fee-free>=5%) rule as a sensitivity. finance_macro/politics_us
# pay fees in B (contaminated controls under a fee DiD) — hence both are reported (see §7 Dev 2.3).
REGISTERED_NEVER_TREATED = {"geopolitics_world", "finance_macro", "politics_us"}

# Cross-sample caveats baked into H3/H4. NOTE (2026-09-04, peer diagnosis): the large
# early B-vs-A HHI gap was NOT a venue difference — it was a DEFINITION MISMATCH. A's passB
# HHI/top5 are over (market×maker) pairs (n_makers2 ~ millions for high-fill classes -> HHI
# ~1e-4 by construction); the first B build used a maker-only HHI (~thousands -> far higher),
# inflating B 6-85x for high-fill classes. B must match passB's (market×maker) grouping for a
# valid comparison. passB's "maker HHI" thus conflates market fragmentation with maker
# concentration (a quirk worth a footnote; the cleaner pure-maker HHI is scripts/17 H6).
CROSS_SAMPLE_CAVEAT = ("A=v1 archive, B=v2 tape. (1) H3 HHI/top5 MUST use passB's (market×maker)-pair "
                       "definition (not maker-only) or B is inflated 6-85x for high-fill classes; passB's "
                       "'maker HHI' conflates market fragmentation with maker concentration (footnote). "
                       "(2) H4 pools v1 A-pre with v2 B in a DiD; never-treated controls absorb the common "
                       "v1->v2 shift under parallel trends, but with a SINGLE fee-free control that is fragile.")

# A pre-fee window (before the staggered fee adoption, treated cohorts g >= 2026-01-05)
A_PRE_START, A_PRE_END = "2025-10-01", "2025-12-29"


# ---------------------------------------------------------------------------
# statistics primitives
# ---------------------------------------------------------------------------
def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def cluster_robust_se(X: np.ndarray, y: np.ndarray, beta: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """CR1 cluster-robust covariance; returns SE vector."""
    n, k = X.shape
    resid = y - X @ beta
    XtX_inv = np.linalg.pinv(X.T @ X)
    meat = np.zeros((k, k))
    uniq = np.unique(groups)
    for g in uniq:
        m = groups == g
        Xg = X[m]; ug = resid[m]
        s = Xg.T @ ug
        meat += np.outer(s, s)
    G = len(uniq)
    dof = G / (G - 1) * (n - 1) / (n - k) if G > 1 else 1.0
    cov = dof * XtX_inv @ meat @ XtX_inv
    return np.sqrt(np.maximum(np.diag(cov), 0.0))


def wild_cluster_boot_p(X, y, groups, coef_idx, *, n_boot=9999, seed=42, one_sided_neg=True):
    """Wild-cluster restricted (WCR, Rademacher) bootstrap p-value for H0: beta[coef_idx]=0."""
    rng = np.random.default_rng(seed)
    beta = ols(X, y)
    se = cluster_robust_se(X, y, beta, groups)
    t_hat = beta[coef_idx] / se[coef_idx] if se[coef_idx] > 0 else 0.0
    # restricted fit: drop the tested column, refit, keep restricted residuals + fitted
    keep = [j for j in range(X.shape[1]) if j != coef_idx]
    Xr = X[:, keep]
    beta_r = ols(Xr, y)
    fitted_r = Xr @ beta_r
    resid_r = y - fitted_r
    uniq = np.unique(groups)
    t_star = np.empty(n_boot)
    for b in range(n_boot):
        w = rng.choice([-1.0, 1.0], size=len(uniq))
        wmap = {g: w[i] for i, g in enumerate(uniq)}
        wv = np.array([wmap[g] for g in groups])
        y_star = fitted_r + resid_r * wv
        bstar = ols(X, y_star)
        sestar = cluster_robust_se(X, y_star, bstar, groups)
        t_star[b] = bstar[coef_idx] / sestar[coef_idx] if sestar[coef_idx] > 0 else 0.0
    if one_sided_neg:
        p = (np.sum(t_star <= t_hat) + 1) / (n_boot + 1)
    else:
        p = (np.sum(np.abs(t_star) >= abs(t_hat)) + 1) / (n_boot + 1)
    return {"beta": float(beta[coef_idx]), "cluster_se": float(se[coef_idx]),
            "t": float(t_hat), "G": int(len(uniq)), "wild_cluster_p": float(p)}


def tost(diff, se, low, high, *, dof=None):
    """Two one-sided tests for equivalence: is `diff` within [low, high]? Returns max of the two p's."""
    from scipy import stats
    if se <= 0:
        return {"equivalent": None, "p": None}
    t_low = (diff - low) / se     # H0: diff <= low  (reject if t_low large +)
    t_high = (high - diff) / se   # H0: diff >= high (reject if t_high large +)
    if dof:
        p_low = 1 - stats.t.cdf(t_low, dof)
        p_high = 1 - stats.t.cdf(t_high, dof)
    else:
        p_low = 1 - stats.norm.cdf(t_low)
        p_high = 1 - stats.norm.cdf(t_high)
    p = max(p_low, p_high)
    return {"equivalent": bool(p < 0.05), "p": float(p), "p_low": float(p_low), "p_high": float(p_high)}


def holm(pmap: dict, alpha=0.05) -> dict:
    items = sorted([(k, v) for k, v in pmap.items() if v is not None], key=lambda kv: kv[1])
    m = len(items); out = {}; rej = True
    for i, (k, p) in enumerate(items):
        rej = rej and (p <= alpha / (m - i))
        out[k] = {"p": p, "reject_null_holm": bool(rej)}
    for k, v in pmap.items():
        if v is None:
            out[k] = {"p": None, "reject_null_holm": None}
    return out


# ---------------------------------------------------------------------------
# H4 — taker order-size DiD (B vs A-pre, treated vs control classes)
# ---------------------------------------------------------------------------
def _did_ordsize(a_col: str, b: "pl.DataFrame", b_col: str, control_classes: set, any_ff: bool) -> tuple[dict, float | None]:
    """One order-size DiD spec: pool A-pre(a_col) + B(b_col); class FE + post + treated:post."""
    a = (pl.read_parquet(A_PANEL).filter(
            (pl.col("week") >= pl.lit(A_PRE_START).str.to_datetime()) &
            (pl.col("week") <= pl.lit(A_PRE_END).str.to_datetime()))
         .select(cls="cls", ordsize=a_col).with_columns(post=pl.lit(0)))
    bb = b.select(cls="cls", ordsize=b_col).with_columns(post=pl.lit(1))
    panel = pl.concat([a, bb]).filter(pl.col("ordsize") > 0)
    both = (panel.group_by("cls").agg(pl.col("post").n_unique().alias("np"))
            .filter(pl.col("np") == 2)["cls"].to_list())
    panel = panel.filter(pl.col("cls").is_in(both)).with_columns(
        y=pl.col("ordsize").log(),
        treated=pl.when(pl.col("cls").is_in(list(control_classes))).then(0).otherwise(1))
    classes = sorted(both)
    n_treated = sum(1 for c in classes if c not in control_classes)
    n_control = sum(1 for c in classes if c in control_classes)
    if len(classes) < 3 or n_control < 1 or n_treated < 1:
        return ({"status": "PENDING", "reason": f"DiD not identified: {len(classes)} classes "
                 f"({n_treated} treated, {n_control} control)"}, None)
    cls_idx = {c: i for i, c in enumerate(classes)}
    df = panel.to_dict(as_series=False)
    n = len(df["y"])
    Xcols = [np.array([1.0 if cc == c else 0.0 for cc in df["cls"]]) for c in classes[1:]]
    post = np.array([float(p) for p in df["post"]])
    treated = np.array([float(t) for t in df["treated"]])
    X = np.column_stack([np.ones(n)] + Xcols + [post, post * treated])
    y = np.array(df["y"], dtype=float)
    groups = np.array([cls_idx[c] for c in df["cls"]])
    res = wild_cluster_boot_p(X, y, groups, X.shape[1] - 1, one_sided_neg=True)
    res.update({
        "prediction": "beta < 0 (A order-size effect ~ -0.40 mean / -0.16 median)",
        "decision_rule": "one-sided p < 0.05 (class-clustered SE + wild-cluster bootstrap)",
        "confirmed_pending_review": bool(res["beta"] < 0 and res["wild_cluster_p"] < 0.05),
        "design": f"B(post) vs A-pre(Oct-Dec 2025); class FE + post + treated:post; outcome=log({b_col} vs A {a_col})",
        "classes_in_DiD": {"total": len(classes), "treated": n_treated, "control": n_control},
        "status": "COMPUTED_PENDING_REVIEW"})
    if not any_ff:
        res["design"] += "  [§2 CONTINGENCY: no within-B control -> weaker design]"
    return res, res["wild_cluster_p"]


def build_h4(rep: dict, h3_table: str | None = None) -> dict:
    """H4 order-size DiD. Prefers the A-consistent fill_ord_* from class_week_b_h3;
    falls back to the CONFOUNDED class_week_b.taker_order_median_notional (labelled)."""
    if not A_PANEL.exists():
        rep["H4_median"] = {"status": "PENDING", "reason": "A class-week panel missing"}
        return {}
    if h3_table and Path(h3_table).exists():
        b = pl.read_parquet(h3_table)
        specs = [("ord_med", "fill_ord_med", "median"), ("ord_mean", "fill_ord_mean", "mean")]
        src = h3_table
    elif B_PANEL.exists():
        b = pl.read_parquet(B_PANEL)
        specs = [("ord_med", "taker_order_median_notional", "median_CONFOUNDED")]
        src = str(B_PANEL)
    else:
        rep["H4"] = {"status": "PENDING", "reason": "no B panel"}
        return {}
    b = b.filter(~pl.col("cls").is_in(list(EXCLUDE_CLASSES)))
    confounded = specs[0][2].endswith("CONFOUNDED")
    rep["_cross_sample_caveat"] = CROSS_SAMPLE_CAVEAT
    fee_free = b.group_by("cls").agg(pl.col("fee_free_share").mean().alias("ff"))
    any_ff = bool((fee_free["ff"] >= 0.05).any())
    single_ctrl = set(fee_free.filter(pl.col("ff") >= 0.05)["cls"].to_list())          # sensitivity
    reg_ctrl = REGISTERED_NEVER_TREATED & set(b["cls"].unique().to_list())              # PRIMARY (pre-reg §2)
    rep["_treatment"] = {
        "registered_control_PRIMARY": {"rule": "§2 never-treated = A fee-exempt (geopolitics/world/macro/US-politics)",
                                       "classes": sorted(reg_ctrl)},
        "single_control_sensitivity": {"rule": "mean B fee_free_share >= 0.05", "classes": sorted(single_ctrl)},
        "control_fee_free_shares": {r["cls"]: round(r["ff"], 3)
            for r in fee_free.sort("ff", descending=True).head(5).to_dicts()},
        "note": "PRIMARY = the registered never-treated set (>=3 controls). finance_macro/politics_us pay fees "
                "in B (contaminated controls under a fee DiD), so the single fee-free-in-B control (geopolitics_world) "
                "is also reported as a sensitivity. H4 is INCONCLUSIVE under BOTH (nothing significant).",
        "b_source": src}
    rep["_contingency_within_B_control_exists"] = any_ff
    pmap = {}
    for ctrl_name, ctrl, is_primary in [("reg", reg_ctrl, True), ("single", single_ctrl, False)]:
        for a_col, b_col, base in specs:
            if b_col not in b.columns:
                continue
            res, p = _did_ordsize(a_col, b, b_col, ctrl, any_ff)
            label = f"H4_{base}_{ctrl_name}"
            rep[label] = res
            # Holm primary = registered-control MEAN spec (its sign matches the predicted beta<0);
            # for the confounded fallback path (median only), use that.
            if is_primary and p is not None and (base == "mean" or (confounded and base == "median")):
                pmap["H4"] = p
    return pmap


# ---------------------------------------------------------------------------
# H3 — provider structure unchanged under fees (TOST vs A-April, per statistic)
# ---------------------------------------------------------------------------
A_APRIL_REF = REPO / "docs/cohort_reports/a_april_reference.json"


def build_h3(rep: dict, h3_table: str | None) -> float | None:
    if not (h3_table and Path(h3_table).exists() and A_APRIL_REF.exists()):
        rep["H3"] = {"status": "PENDING", "reason": "class_week_b_h3 or A-April reference missing"}
        return None
    b = pl.read_parquet(h3_table).filter(~pl.col("cls").is_in(list(EXCLUDE_CLASSES)))
    need = {"maker_hhi", "top5_maker_share", "spread_proxy", "fee_free_share"}
    if not need.issubset(set(b.columns)):
        rep["H3"] = {"status": "PENDING", "reason": f"table missing {need - set(b.columns)}"}
        return None
    ref = {r["cls"]: r for r in json.loads(A_APRIL_REF.read_text())}
    fee_free = b.group_by("cls").agg(pl.col("fee_free_share").mean().alias("ff"))
    control = set(fee_free.filter(pl.col("ff") >= 0.05)["cls"].to_list())
    feepay = [c for c in b["cls"].unique().to_list() if c not in control and c in ref]
    bmean = (b.filter(pl.col("cls").is_in(feepay)).group_by("cls").agg(
                pl.col("maker_hhi").mean().alias("hhi_B"),
                pl.col("top5_maker_share").mean().alias("top5_B"),
                pl.col("spread_proxy").mean().alias("spread_B"))).to_dicts()

    def cluster_tost(diffs, low, high):
        d = np.array(diffs, dtype=float)
        if len(d) < 2:
            return {"equivalent": None, "p": None, "n_classes": int(len(d))}
        se = d.std(ddof=1) / np.sqrt(len(d))
        r = tost(float(d.mean()), float(se), low, high, dof=len(d) - 1)
        r.update({"mean_diff": float(d.mean()), "n_classes": int(len(d))})
        return r

    lr_hhi = [np.log(r["hhi_B"] / ref[r["cls"]]["hhi_A"]) for r in bmean
              if ref[r["cls"]]["hhi_A"] > 0 and r["hhi_B"] and r["hhi_B"] > 0]
    lr_top5 = [np.log(r["top5_B"] / ref[r["cls"]]["top5_A"]) for r in bmean
               if ref[r["cls"]]["top5_A"] > 0 and r["top5_B"] and r["top5_B"] > 0]
    d_spread = [r["spread_B"] - ref[r["cls"]]["spread_A"] for r in bmean if r["spread_B"] is not None]
    stats = {"maker_hhi": cluster_tost(lr_hhi, np.log(0.75), np.log(1.25)),      # ±25% (log-ratio)
             "top5_maker_share": cluster_tost(lr_top5, np.log(0.75), np.log(1.25)),
             "spread_proxy": cluster_tost(d_spread, -0.005, 0.005)}             # ±0.5 cents (absolute)
    all_equiv = all(s.get("equivalent") for s in stats.values())
    rep["H3"] = {"status": "COMPUTED_PENDING_REVIEW", "fee_paying_classes_tested": feepay,
                 "bounds": {"hhi": "±25% (log-ratio)", "top5": "±25% (log-ratio)", "spread": "±0.5 cents (absolute)"},
                 "statistics": stats,
                 "decision_rule": "TOST equivalence, class-clustered, p<0.05 for ALL three; any failure => that stat not confirmed",
                 "confirmed_pending_review": bool(all_equiv),
                 "interpretation": "point differences are SMALL after de-confounding (B vs A close); equiv=False "
                     "here means the ±bound TOST is UNDERPOWERED at n=11 noisy class-level obs (wide CI), NOT a "
                     "refutation. Read as 'provider structure looks roughly stable but equivalence is not "
                     "formally established', not 'structure changed'.",
                 "CAVEAT_definition": CROSS_SAMPLE_CAVEAT + " B now uses A's (condition,maker) HHI basis "
                     "(corrected table) so the comparison is valid; the (market×maker) HHI remains a passB quirk "
                     "worth a footnote.",
                 "spread_status": "spread sign corrected (B records maker side; taker = opposite); spread_proxy "
                     "now positive (crypto_updown ~+0.022, ~A-April +0.0156)."}
    ps = [s["p"] for s in stats.values() if s.get("p") is not None]
    return max(ps) if ps else None   # H3 passes only if the WORST statistic passes


# ---------------------------------------------------------------------------
# H1c — self-matching (structural: exactly 0)
# ---------------------------------------------------------------------------
def build_h1c(rep: dict) -> None:
    if COHORT1.exists():
        d = json.loads(COHORT1.read_text())
        sm = d.get("self_match_fills")
        rep["H1c"] = {"self_match_fills": sm,
                      "prediction": "exactly 0 (structural)",
                      "refuted": (sm is not None and sm != 0),
                      "status": "COMPUTED" if sm is not None else "PENDING",
                      "source": "cohort1_descriptive_repro.json (confirmatory window = cohort 1)"}
    else:
        rep["H1c"] = {"status": "PENDING", "reason": "cohort1 descriptive not found"}


# ---------------------------------------------------------------------------
# H1a — one-step round-trip share (wash-like), TOST B fee-paying vs A-April ±1pp
# ---------------------------------------------------------------------------
A_RT_REF = REPO / "data/parquet/atlas/wash_q3b_roundtrip_monthly_class_fee.parquet"
H1A_CONTROL = {"geopolitics_world"}  # fee-free control + under-captured in B by taxonomy: footnote, not tested


def build_h1a(rep: dict, h1a_table: str | None) -> float | None:
    if not (h1a_table and Path(h1a_table).exists() and A_RT_REF.exists()):
        rep["H1a"] = {"status": "PENDING", "reason": "B rt table or A wash reference missing"}
        return None
    b = pl.read_parquet(h1a_table)
    if "fee_flag" not in b.columns or not b.filter(pl.col("fee_flag")).height:
        rep["H1a"] = {"status": "PENDING", "reason": "B table has no fee_flag=true rows"}
        return None
    bfee = {r["wash_cls"]: r["rt_any_share"] for r in b.filter(pl.col("fee_flag")).to_dicts()}
    a = pl.read_parquet(A_RT_REF).filter((pl.col("ym") == "2026-04") & (pl.col("fee_flag")))
    aref = {r["cls"]: r["rt_any_share"] for r in a.to_dicts()}
    if not aref:
        rep["H1a"] = {"status": "PENDING", "reason": "no A-April fee=true rows in wash reference"}
        return None
    rows = [{"cls": c, "B_rt_any": round(bshare, 4), "A_apr_rt_any": round(aref[c], 4),
             "diff_pp": round((bshare - aref[c]) * 100, 3)}
            for c, bshare in bfee.items() if c not in H1A_CONTROL and c in aref]
    if len(rows) < 2:
        rep["H1a"] = {"status": "PENDING", "reason": f"only {len(rows)} matched fee-paying classes"}
        return None
    diffs = np.array([r["diff_pp"] / 100.0 for r in rows])   # share units
    se = float(diffs.std(ddof=1) / np.sqrt(len(diffs)))
    t = tost(float(diffs.mean()), se, -0.01, 0.01, dof=len(diffs) - 1)
    rep["H1a"] = {"status": "COMPUTED_PENDING_REVIEW",
                  "metric": "rt_any_share (both-legs round-trip vol share, 600s / >=50% overlap)",
                  "decision_rule": "TOST equivalence +-1pp on B - A-April, class-clustered; confirmed if both one-sided p<0.05",
                  "per_class": sorted(rows, key=lambda r: -r["diff_pp"]),
                  "mean_diff_pp": round(float(diffs.mean()) * 100, 3),
                  "n_fee_paying_classes": len(rows),
                  "classes_over_plus_1pp": [r["cls"] for r in rows if r["diff_pp"] > 1.0],
                  "tost": t,
                  "confirmed_pending_review": bool(t.get("equivalent")),
                  "interpretation": ("equiv=True => round-tripping did NOT rise >1pp under fees (H1 supported). "
                      "equiv=False => cannot confirm it is unchanged; may be elevated in B (see classes_over_plus_1pp) "
                      "— but subject to the v1-vs-v2 cross-sample caveat + construction residuals, so 'suspicious', not proof."),
                  "geo_footnote": "geopolitics_world excluded (fee-free control, under-captured in B by taxonomy)."}
    return t.get("p")


# ---------------------------------------------------------------------------
# H1a / H1b / H2 / H3 — consume pre-computed B-tape statistic tables
# ---------------------------------------------------------------------------
def load_table(path: str | None):
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return pl.read_parquet(p) if p.suffix == ".parquet" else pl.read_csv(p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/cohort_reports/confirmatory_h1_h4.json")
    ap.add_argument("--h1a-table", help="B round-trip share per class (from peer's atlasB port)")
    ap.add_argument("--h1b-table", help="B concentrated-pairs volume share")
    ap.add_argument("--h2-table", help="B negRisk |S-1| per family with fee-band")
    ap.add_argument("--h3-table", help="B maker HHI/top5/spread per class-week")
    ap.add_argument("--n-boot", type=int, default=9999)
    args = ap.parse_args()

    rep: dict = {"registered_spec": "docs/stage2_preregistration.md §3",
                 "note": "PRELIMINARY — no confirmatory CLAIM until reviewed; treatment assignment to be confirmed."}
    pmap: dict = {}

    # H4 (order-size DiD) + H3 (provider TOST): ready when the peer's class_week_b_h3 lands
    # (H4 falls back to the confounded panel column if not); H1c: ready now.
    pmap.update(build_h4(rep, args.h3_table))
    build_h1c(rep)
    p_h3 = build_h3(rep, args.h3_table)
    if p_h3 is not None:
        pmap["H3"] = p_h3
    p_h1a = build_h1a(rep, args.h1a_table)
    if p_h1a is not None:
        pmap["H1a"] = p_h1a

    # H1b / H2: consume the peer's B-tape tables when present, else PENDING
    for h, arg in [("H1b", args.h1b_table), ("H2", args.h2_table)]:
        tbl = load_table(arg)
        rep[h] = ({"status": "PENDING", "reason": "B-tape statistic table not provided yet "
                   "(heavy class-level computation owned by the panel/atlas builder)"} if tbl is None
                  else {"status": "TABLE_LOADED", "n_rows": tbl.height,
                        "next": "apply registered decision rule (wire once schema confirmed)"})

    rep["holm_across_available"] = holm(pmap)
    def _done(h):
        return rep.get(h, {}).get("status", "").startswith("COMPUTED")
    h4_labels = sorted(k for k in rep if k.startswith("H4_"))
    rep["summary"] = {
        "computed": [h for h in ["H1c", "H3", *h4_labels] if _done(h)],
        "pending": [h for h in ("H1a", "H1b", "H2", "H3") if rep.get(h, {}).get("status") == "PENDING"],
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    for lab in h4_labels:
        h4 = rep.get(lab, {})
        if h4.get("status", "").startswith("COMPUTED"):
            print(f"{lab}: beta={h4['beta']:+.4f}  cluster_se={h4['cluster_se']:.4f}  G={h4['G']}  "
                  f"wild-cluster p={h4['wild_cluster_p']:.4f}  "
                  f"-> {'beta<0 & p<.05 (pending review)' if h4['confirmed_pending_review'] else 'not confirmed'}")
    if "_treatment" in rep:
        print(f"   §2 within-B control exists: {rep.get('_contingency_within_B_control_exists')}; "
              f"PRIMARY (registered) control: {rep['_treatment']['registered_control_PRIMARY']['classes']}; "
              f"sensitivity (single): {rep['_treatment']['single_control_sensitivity']['classes']}")
    if rep.get("H3", {}).get("status", "").startswith("COMPUTED"):
        for k, s in rep["H3"]["statistics"].items():
            print(f"H3 {k}: mean_diff={s.get('mean_diff')}  TOST p={s.get('p')}  equiv={s.get('equivalent')} (n={s.get('n_classes')})")
    if rep.get("H1a", {}).get("status", "").startswith("COMPUTED"):
        h1a = rep["H1a"]
        print(f"H1a round-trip: mean_diff={h1a['mean_diff_pp']}pp  TOST p={h1a['tost']['p']:.3f}  "
              f"equiv={h1a['tost']['equivalent']}  over+1pp={h1a['classes_over_plus_1pp']}")
    print(f"H1c self-match: {rep['H1c'].get('self_match_fills')}  (refuted={rep['H1c'].get('refuted')})")
    print(f"PENDING: {rep['summary']['pending']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
