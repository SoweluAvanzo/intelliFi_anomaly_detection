#!/usr/bin/env python
"""Stage 19: cross-cohort inference on the Sample-B tape-level descriptive metrics.

Reads the per-cohort JSONs written by scripts/17 (cohort1_descriptive_repro.json +
cohortN_descriptive.json for N=2..6) and asks, for each tape-level metric, whether
it is STABLE across the six two-week cohorts that span the v2 fee rollout — via a
cross-cohort trend test and a TOST-style equivalence check, Holm-corrected across
the family. Pure-local, offline-safe (reads small JSONs only).

SCOPE — read this before citing anything:
  This is the cohort-level REPLICATION-STABILITY layer. It is NOT the registered
  confirmatory H1-H4 (docs/stage2_preregistration.md §3), which are CLASS-level
  (fee-paying vs fee-free classes) with a Sample-A April comparison, class-clustered
  SEs and wild-cluster bootstrap over G=8 classes. Those need the tape joined to
  clob_markets classes + negRisk families + the A reference levels — a larger offline
  build (feasible: clob_markets is local at ~100% token coverage) that is the next
  step. With only 6 cohort points the tests here are LOW-POWER and descriptive; treat
  them as "do the tape-level integrity metrics drift across the rollout window", not
  as the pre-registered confirmatory verdicts.

    python scripts/19_confirmatory_inference.py --out docs/cohort_reports/cross_cohort_inference.json
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from pathlib import Path


def load_cohorts(dir_: Path) -> list[dict]:
    out = []
    for n in range(1, 7):
        cands = ([str(dir_ / "cohort1_descriptive_repro.json")] if n == 1 else []) + \
                [str(dir_ / f"cohort{n}_descriptive.json")]
        for p in cands:
            if os.path.exists(p):
                d = json.load(open(p))
                d["_cohort_n"] = n
                out.append(d)
                break
    return out


def ols_trend(xs: list[float], ys: list[float]) -> dict:
    """Slope of y ~ x with a t-test p-value (two-sided). Low n -> low power; reported."""
    n = len(xs)
    if n < 3:
        return {"slope": None, "p": None, "n": n, "note": "n<3, not testable"}
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return {"slope": 0.0, "p": None, "n": n}
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    inter = my - slope * mx
    resid = [y - (inter + slope * x) for x, y in zip(xs, ys)]
    dof = n - 2
    s2 = sum(r * r for r in resid) / dof if dof > 0 else float("nan")
    se = math.sqrt(s2 / sxx) if sxx > 0 and s2 == s2 else float("nan")
    t = slope / se if se and se == se and se != 0 else float("nan")
    # two-sided p via a normal approx (dof small; approximate — flagged in scope)
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2)))) if t == t else None
    return {"slope": slope, "p": p, "n": n, "se": se, "t": t}


def holm(pvals: dict[str, float | None], alpha: float = 0.05) -> dict[str, bool]:
    items = [(k, p) for k, p in pvals.items() if p is not None]
    items.sort(key=lambda kv: kv[1])
    m = len(items)
    rej, out = True, {}
    for i, (k, p) in enumerate(items):
        thresh = alpha / (m - i)
        rej = rej and (p <= thresh)
        out[k] = rej
    for k, p in pvals.items():
        if p is None:
            out[k] = False
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="docs/cohort_reports")
    ap.add_argument("--out", default="docs/cohort_reports/cross_cohort_inference.json")
    ap.add_argument("--equiv-margin-rel", type=float, default=0.15,
                    help="TOST-style equivalence: cross-cohort range within +-margin*|mean| = 'stable'")
    args = ap.parse_args()

    cohorts = load_cohorts(Path(args.dir))
    if len(cohorts) < 2:
        print(f"only {len(cohorts)} cohort JSONs found in {args.dir}; need >=2. "
              "Run the cohort driver first.", file=sys.stderr)
        return 2

    # extract the tape-level metrics per cohort
    def get(d, path, default=None):
        cur = d
        for k in path:
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        return cur if cur is not None else default

    def feeclass(d, key, fee):  # order_size_by_fee / H1a lists -> value for fee_paying==fee
        for r in d.get(key, []) or []:
            if bool(r.get("fee_paying")) == fee:
                return r
        return {}

    metrics = {}
    ns = [d["_cohort_n"] for d in cohorts]
    metrics["self_match_fills"] = [d.get("self_match_fills") for d in cohorts]
    metrics["taker_fee_paying_share"] = [d.get("taker_orders_fee_paying_share") for d in cohorts]
    metrics["maker_hhi_notional"] = [get(d, ["H6_maker_concentration", "hhi_notional"]) for d in cohorts]
    metrics["maker_top10_notional"] = [get(d, ["H6_maker_concentration", "top10_notional_share"]) for d in cohorts]
    metrics["order_size_median_feepaying"] = [feeclass(d, "order_size_by_fee", True).get("median_notional") for d in cohorts]
    metrics["order_size_median_nofee"] = [feeclass(d, "order_size_by_fee", False).get("median_notional") for d in cohorts]
    metrics["roundtrip_share_feepaying"] = [feeclass(d, "H1a_roundtrip_share_by_fee", True).get("rt_share") for d in cohorts]

    rep: dict = {"cohorts_loaded": ns, "equiv_margin_rel": args.equiv_margin_rel,
                 "SCOPE": "cohort-level replication stability; NOT the registered class-level H1-H4 "
                          "(those need the clob_markets class join + Sample-A comparison). n=6 => low power.",
                 "metrics": {}}
    trend_p = {}
    for name, ys in metrics.items():
        pairs = [(float(n), float(y)) for n, y in zip(ns, ys) if y is not None]
        if len(pairs) < 2:
            rep["metrics"][name] = {"values": ys, "note": "insufficient cohorts"}
            continue
        xs2, ys2 = [p[0] for p in pairs], [p[1] for p in pairs]
        mean = sum(ys2) / len(ys2)
        rng = max(ys2) - min(ys2)
        equiv = (rng <= args.equiv_margin_rel * abs(mean)) if mean != 0 else (rng == 0)
        tr = ols_trend(xs2, ys2)
        trend_p[name] = tr.get("p")
        rep["metrics"][name] = {
            "by_cohort": {int(n): y for n, y in zip(ns, ys)},
            "mean": mean, "min": min(ys2), "max": max(ys2), "range": rng,
            "stable_within_margin": bool(equiv),
            "trend_slope_per_cohort": tr.get("slope"), "trend_p_uncorrected": tr.get("p"),
        }
    rep["trend_significant_holm"] = holm(trend_p)

    # H1c is structural: any non-zero self-match across cohorts refutes it.
    sm = [s for s in metrics["self_match_fills"] if s is not None]
    rep["H1c_self_match_all_zero"] = all(s == 0 for s in sm) if sm else None

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out} ({len(cohorts)} cohorts)")
    print("SCOPE: cohort-level stability, NOT registered class-level H1-H4 (low power at n=6).")
    for name, m in rep["metrics"].items():
        if "mean" in m:
            print(f"  {name:32s} mean={m['mean']:.5g} range={m['range']:.3g} "
                  f"stable={m['stable_within_margin']} trend_p={m['trend_p_uncorrected']}")
    print(f"  H1c self-match all zero across cohorts: {rep['H1c_self_match_all_zero']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
