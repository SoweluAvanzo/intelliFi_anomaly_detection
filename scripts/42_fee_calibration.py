#!/usr/bin/env python
"""RQ1: forecast calibration under the fee + the negRisk arbitrage-band audit.

Reads the validated price series and the atlas negRisk family-hour sums; writes the era-comparison
table, reliability curves, and the band-audit verdict to `data/export/`. See `docs/FEE_EFFECTS.md`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import pandas as pd                             # noqa: E402
from intellifi import config as _cfg            # noqa: E402
from intellifi import fee_calibration as fc     # noqa: E402

OUT = _cfg.DATA_DIR / "export"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    era = fc.era_comparison()
    era.to_csv(OUT / "calibration_era_decomposition.csv", index=False)
    print("=== RQ1 era comparison (reliability = mis-calibration; resolution = sharpness/mix) ===")
    print(era.to_string(index=False))

    # reliability curves for the chart (>=7d-life subset, both eras at 1 day)
    v2 = pd.read_parquet(OUT / "price_series_rq1.parquet", columns=["realized_y0", "p_1d", "lifespan_days"])
    v1 = pd.read_parquet(OUT / "price_series_v1.parquet",
                         columns=["realized_y0", "p_1d", "lifespan_days", "anchor_source"])
    rc_v2 = fc.reliability_curve(v2[v2.lifespan_days >= 7], "p_1d"); rc_v2["era"] = "v2 fee"
    rc_v1 = fc.reliability_curve(v1[(v1.lifespan_days >= 7) & (v1.anchor_source == "resolved_at")], "p_1d"); rc_v1["era"] = "v1 pre-fee"
    pd.concat([rc_v1, rc_v2], ignore_index=True).to_csv(OUT / "calibration_reliability_1d.csv", index=False)

    band = fc.band_audit()
    (OUT / "negrisk_band_audit.json").write_text(json.dumps(band, indent=2))
    print("\n=== negRisk band audit (verdict) ===")
    print(json.dumps(band, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
