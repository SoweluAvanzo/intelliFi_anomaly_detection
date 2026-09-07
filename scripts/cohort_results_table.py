#!/usr/bin/env python3
"""Assemble the per-cohort descriptive JSONs into one cross-cohort results table.

Reads docs/cohort_reports/cohort{N}_descriptive.json (N=1..6; for c1 prefer the
committed cohort1_descriptive.json, else the _repro), flattens the key metrics,
and writes:
  docs/cohort_reports/cross_cohort_results.csv   (one row per cohort)
  docs/cohort_reports/cross_cohort_results.md    (transposed, metrics x cohorts)

Tolerant of the H2/H6 superset: any extra top-level scalar keys the generator
emits (e.g. an H2 negRisk-band median, a family-dedup HHI) appear as extra rows
automatically. Offline, no deps beyond the stdlib. Feeds scripts/19 (inference).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "docs" / "cohort_reports"

_KNOWN_NESTED = {
    "cohort", "block_range", "n_fills", "n_makers", "n_takers", "self_match_fills",
    "H6_maker_concentration", "H5_fee_incidence_by_size_decile",
    "taker_orders_fee_paying_share", "order_size_by_fee", "builder_attribution",
    "H1a_roundtrip_share_by_fee",
}


def _cohort_path(n: int) -> Path | None:
    if n == 1:
        # Prefer scripts/17's OWN c1 output (_repro): all cohorts must sit on identical
        # definitions for the cross-cohort comparison to be valid. The committed
        # cohort1_descriptive.json is kept only as a historical reference.
        for name in ("cohort1_descriptive_repro.json", "cohort1_descriptive.json"):
            p = REPORTS / name
            if p.exists():
                return p
        return None
    p = REPORTS / f"cohort{n}_descriptive.json"
    return p if p.exists() else None


def _flatten(j: dict) -> dict:
    row: dict = {"cohort": j.get("cohort")}
    br = j.get("block_range") or [None, None]
    row["block_lo"], row["block_hi"] = br[0], br[1]
    for k in ("n_fills", "n_makers", "n_takers", "self_match_fills",
              "taker_orders_fee_paying_share"):
        row[k] = j.get(k)
    h6 = j.get("H6_maker_concentration", {}) or {}
    row["maker_hhi_notional"] = h6.get("hhi_notional")
    row["maker_top10_notional_share"] = h6.get("top10_notional_share")
    row["maker_top10_fill_share"] = h6.get("top10_fill_share")
    for o in j.get("order_size_by_fee", []) or []:
        tag = "fee" if o.get("fee_paying") else "nofee"
        row[f"ordersize_median_{tag}"] = o.get("median_notional")
        row[f"ordersize_geomean_{tag}"] = o.get("geomean_notional")
    for o in j.get("H1a_roundtrip_share_by_fee", []) or []:
        tag = "fee" if o.get("fee_paying") else "nofee"
        row[f"roundtrip_share_{tag}"] = o.get("rt_share")
    dec = {d.get("decile"): d for d in j.get("H5_fee_incidence_by_size_decile", []) or []}
    if 1 in dec and 10 in dec:
        row["fee_pct_decile1_smallest"] = dec[1].get("mean_fee_pct")
        row["fee_pct_decile10_largest"] = dec[10].get("mean_fee_pct")
    b = j.get("builder_attribution", {}) or {}
    row["n_builders"] = b.get("n_builders")
    row["builder_notional_hhi"] = b.get("notional_hhi")
    # superset: any extra top-level scalar keys (H2 band, family HHI, coverage %, ...)
    for k, v in j.items():
        if k not in _KNOWN_NESTED and isinstance(v, (int, float, str, bool)):
            row.setdefault(k, v)
    return row


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def main() -> int:
    rows = []
    for n in range(1, 7):
        p = _cohort_path(n)
        if p is None:
            continue
        try:
            rows.append((_flatten(json.loads(p.read_text())), p.name))
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] could not read {p}: {exc}")
    if not rows:
        print("[cohort_results_table] no cohort descriptive JSONs found yet -- nothing to assemble.")
        return 0

    # union of columns, stable order (first-seen)
    cols: list[str] = []
    for r, _ in rows:
        for k in r:
            if k not in cols:
                cols.append(k)

    csv_path = REPORTS / "cross_cohort_results.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r, _ in rows:
            w.writerow(r)

    # transposed markdown: metrics as rows, cohorts as columns
    labels = [f"c{r.get('cohort','?')}" for r, _ in rows]
    md = ["# Cross-cohort descriptive results", "",
          "Fee regime: c1+ are v2 (fee) cohorts; compare fee vs no-fee columns within each.",
          "", "| metric | " + " | ".join(labels) + " |",
          "|" + "---|" * (len(labels) + 1)]
    for c in cols:
        if c == "cohort":
            continue
        md.append("| " + c + " | " + " | ".join(_fmt(r.get(c)) for r, _ in rows) + " |")
    md_path = REPORTS / "cross_cohort_results.md"
    md_path.write_text("\n".join(md) + "\n")

    print(f"[cohort_results_table] {len(rows)} cohorts -> {csv_path.name}, {md_path.name}")
    print("  cohorts:", ", ".join(labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
