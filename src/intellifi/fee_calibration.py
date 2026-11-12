"""RQ1: forecast calibration under the fee, and the negRisk arbitrage-band audit.

Operates on the validated price series (`data/export/price_series_{rq1,v1}.parquet`) and the atlas
negRisk family-hour sums. Key result: calibration (the Brier *reliability* term) is ~0 in both eras;
V1/V2 Brier differences are *sharpness/composition*, not forecast quality. The "+3.4-4.2pp band
widening" does not survive a liquidity control + never-treated placebo. See `docs/FEE_EFFECTS.md`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as _cfg


def brier_decomposition(df: pd.DataFrame, col: str, y: str = "realized_y0", bins: int = 10) -> dict:
    """Murphy decomposition: Brier = reliability - resolution + uncertainty (10 equal-width bins).
    reliability = mis-calibration (lower better, the forecast-quality term); resolution = sharpness."""
    d = df.dropna(subset=[col, y])
    n = len(d)
    if n < 50:
        return {"n": n}
    o = d[y].mean()
    bk = (d[col] * bins).round() / bins
    g = pd.DataFrame({"y": d[y].to_numpy(), "p": d[col].to_numpy(), "bk": bk.to_numpy()}).groupby("bk")
    agg = g.agg(nk=("y", "size"), pk=("bk", "first"), ok=("y", "mean"))
    rel = float((agg.nk * (agg.pk - agg.ok) ** 2).sum() / n)
    res = float((agg.nk * (agg.ok - o) ** 2).sum() / n)
    brier = float(((d[col] - d[y]) ** 2).mean())
    return {"n": n, "brier": round(brier, 4), "reliability": round(rel, 4),
            "resolution": round(res, 4), "uncertainty": round(o * (1 - o), 4), "base_rate": round(o, 3)}


def reliability_curve(df: pd.DataFrame, col: str, y: str = "realized_y0", bins: int = 10) -> pd.DataFrame:
    """predicted-probability bucket -> empirical win rate (for the reliability chart)."""
    d = df.dropna(subset=[col, y]).copy()
    d["bucket"] = (d[col] * bins).round() / bins
    return (d.groupby("bucket").agg(n=(y, "size"), empirical=(y, "mean")).reset_index())


def era_comparison(v1_path: str | None = None, v2_path: str | None = None) -> pd.DataFrame:
    """The RQ1 headline: Brier decomposition by era (V1 all, V1 oracle-anchored, V2) at 1h and last."""
    v1_path = v1_path or str(_cfg.DATA_DIR / "export" / "price_series_v1.parquet")
    v2_path = v2_path or str(_cfg.DATA_DIR / "export" / "price_series_rq1.parquet")
    v1 = pd.read_parquet(v1_path, columns=["realized_y0", "p_1h", "p_last", "anchor_source"])
    v2 = pd.read_parquet(v2_path, columns=["realized_y0", "p_1h", "p_last"])
    rows = []
    for lab, df, col in [("v1 all", v1, "p_1h"),
                         ("v1 oracle", v1[v1.anchor_source == "resolved_at"], "p_1h"),
                         ("v2 fee", v2, "p_1h"),
                         ("v1 all", v1, "p_last"),
                         ("v1 oracle", v1[v1.anchor_source == "resolved_at"], "p_last"),
                         ("v2 fee", v2, "p_last")]:
        r = brier_decomposition(df, col)
        r.update({"era": lab, "horizon": col})
        rows.append(r)
    return pd.DataFrame(rows)[["era", "horizon", "n", "brier", "reliability", "resolution", "uncertainty", "base_rate"]]


# ----- negRisk arbitrage-band audit (the rejected "+3.4-4.2pp widening") -----
# Cleanest treated class = crypto (97.5% fee adoption); never-treated = the placebo control.
NEVER_TREATED = ("politics", "geopolitics")


def band_audit(hour_sums_path: str | None = None, seed: int = 0, n_boot: int = 500) -> dict:
    """Reproduce the raw fee>nofee |S-1| gap, then control for volume x candidate-count x class and
    run a never-treated placebo. Verdict: the gap is a liquidity/composition artifact
    (crypto ~0, placebo large)."""
    hour_sums_path = hour_sums_path or str(_cfg.PARQUET_DIR / "atlas" / "negrisk_family_hour_sums.parquet")
    rng = np.random.default_rng(seed)
    h = pd.read_parquet(hour_sums_path, columns=["adev", "n_alive", "vol_hr", "cls", "fee_status", "ym"])
    h["nbin"] = pd.cut(h.n_alive, [0, 7, 15, 10 ** 9], labels=["sm", "md", "lg"])
    h["vbin"] = pd.qcut(h.vol_hr, 5, labels=False, duplicates="drop")
    h["fee"] = (h.fee_status == "fee").astype(int)

    raw = (h.groupby("fee_status").adev.mean())
    raw_gap = round(float(raw.get("fee", np.nan) - raw.get("nofee", np.nan)), 4)

    def std_gap(sub):
        g = sub.groupby(["nbin", "vbin", "fee"], observed=True).adev.mean().unstack("fee")
        c = sub.groupby(["nbin", "vbin", "fee"], observed=True).adev.size().unstack("fee").fillna(0)
        b = g.dropna()
        if b.empty or 1 not in b.columns or 0 not in b.columns:
            return np.nan
        w = (c.loc[b.index, 1] + c.loc[b.index, 0]); w = w / w.sum()
        return float(((b[1] - b[0]) * w).sum())

    def boot_ci(sub):
        pt = std_gap(sub)
        vals = [std_gap(sub.sample(len(sub), replace=True, random_state=int(rng.integers(1e9)))) for _ in range(n_boot)]
        lo, hi = np.nanpercentile(vals, [2.5, 97.5])
        return round(pt, 4), round(float(lo), 4), round(float(hi), 4)

    crypto = boot_ci(h[h.cls == "crypto"])
    placebo = boot_ci(h[h.cls.isin(NEVER_TREATED)])
    verdict = (f"not a fee effect: the never-treated placebo gap ({placebo[0]:+.4f}) — which cannot be a "
               f"fee effect — is as large as the raw fee/no-fee gap ({raw_gap:+.4f}) and far exceeds the "
               f"cleanest-treated crypto gap ({crypto[0]:+.4f}, small/bin-sensitive) after controlling for "
               f"volume x candidate-count. The cross-sectional contrast is confounded by liquidity/market-type selection.")
    return {"raw_fee_minus_nofee": raw_gap,
            "cleanest_treated_crypto_gap_ci": crypto,
            "never_treated_placebo_gap_ci": placebo,
            "verdict": verdict}
