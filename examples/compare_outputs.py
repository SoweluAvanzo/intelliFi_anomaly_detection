#!/usr/bin/env python
"""Compare a regenerated parquet store against a reference snapshot.

After re-running scripts 03–06 (see REPRODUCING.md), run:

    .venv/bin/python examples/compare_outputs.py [--new data/parquet] [--ref data/snapshots/<date>]

Numeric columns are compared with a relative tolerance (floating-point
summation order differs between DuckDB thread schedules and CPUs); row order
is ignored; Louvain communities are compared by membership, not by label.
Exit code 0 = every table reproduces.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl

RTOL, ATOL = 1e-9, 1e-6

# A leader can fill twice in the same second on one asset, so event rows are
# keyed on the copied trade fields too (exact values, not computed).
EVENT_KEYS = ["leader", "asset_id", "leader_ts", "side", "leader_price", "leader_notional", "horizon_seconds", "matched_event_idx"]

TABLES: list[tuple[str, list[str]]] = [           # (relative path, key columns)
    ("universe.parquet", ["proxy_wallet"]),
    ("wallet_graph/communities.parquet", ["members"]),
    ("coordination/cotrade_pairs.parquet", ["a", "b"]),
    ("coordination/leader_lag.parquet", ["leader", "follower"]),
    ("coordination/wash_round_trips.parquet", ["proxy_wallet"]),
    ("backtest/summary.parquet", ["leader_set", "eval_scope", "is_control", "horizon_seconds"]),
    ("convergence/per_market.parquet", ["condition_id", "hours_before_end"]),
    ("convergence/aggregate.parquet", ["hours_before_end"]),
]
PARTITIONS = ["wallet_graph/partition.json", "coordination/behavioural_partition.json"]


def load(path: Path) -> pl.DataFrame:
    df = pl.read_parquet(path)
    if "members" in df.columns:          # community label is arbitrary; key on sorted membership
        df = df.with_columns(pl.col("members").list.sort().list.join("|")).drop("community_id")
    return df


def compare_table(rel: str, keys: list[str], new: Path, ref: Path) -> tuple[bool, str]:
    pn, pr = new / rel, ref / rel
    if not pn.exists() or not pr.exists():
        return False, f"missing file ({'new' if not pn.exists() else 'ref'})"
    x, y = load(pn), load(pr)
    if x.columns != y.columns:
        return False, f"column mismatch: {sorted(set(x.columns) ^ set(y.columns))}"
    kx, ky = set(map(tuple, x.select(keys).rows())), set(map(tuple, y.select(keys).rows()))
    if kx != ky:
        return False, f"key sets differ: {len(kx - ky)} only in new, {len(ky - kx)} only in ref"
    if x.select(keys).is_duplicated().any():
        # Keys not unique: compare as sorted multisets of whole rows instead.
        xs, ys = x.sort(x.columns), y.sort(y.columns)
        if xs.height != ys.height:
            return False, f"row count {xs.height} vs {ys.height}"
        j = pl.concat([xs, ys.rename({c: c + "__ref" for c in ys.columns})], how="horizontal")
    else:
        j = x.join(y, on=keys, suffix="__ref")
    bad = []
    for c in x.columns:
        if c in keys:
            continue
        a, b = j[c], j[c + "__ref"]
        if a.dtype.is_numeric():
            af, bf = a.cast(pl.Float64), b.cast(pl.Float64)
            d = (af - bf).abs()
            tol = ATOL + RTOL * bf.abs()
            n = int(((d > tol) & ~(af.is_null() & bf.is_null())).sum())
        else:
            n = int((a != b).fill_null(a.is_null() != b.is_null()).sum())
        if n:
            bad.append(f"{c} ({n} rows)")
    return (not bad), (f"{x.height} rows" if not bad else "differs in " + ", ".join(bad))


def compare_partition(rel: str, new: Path, ref: Path) -> tuple[bool, str]:
    a, b = json.loads((new / rel).read_text()), json.loads((ref / rel).read_text())
    ga: dict[int, set[str]] = {}
    gb: dict[int, set[str]] = {}
    for w, c in a.items():
        ga.setdefault(c, set()).add(w)
    for w, c in b.items():
        gb.setdefault(c, set()).add(w)
    same = set(map(frozenset, ga.values())) == set(map(frozenset, gb.values()))
    return same, f"{len(ga)} groups, labels {'identical' if a == b else 'renumbered but same grouping' if same else 'differ'}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new", type=Path, default=Path("data/parquet"))
    ap.add_argument("--ref", type=Path, default=None,
                    help="reference snapshot dir (default: newest under data/snapshots/)")
    args = ap.parse_args()
    ref = args.ref or sorted(Path("data/snapshots").iterdir())[-1]
    print(f"new: {args.new}\nref: {ref}\n")
    failures = 0
    tables = list(TABLES) + [(f"backtest/{p.name}", EVENT_KEYS)
                             for p in sorted((ref / "backtest").glob("*_events.parquet"))]
    for rel, keys in tables:
        ok, msg = compare_table(rel, keys, args.new, ref)
        failures += (not ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {rel:45s} {msg}")
    for rel in PARTITIONS:
        ok, msg = compare_partition(rel, args.new, ref)
        failures += (not ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {rel:45s} {msg}")
    print(f"\n{'ALL TABLES REPRODUCE' if not failures else f'{failures} TABLE(S) DIFFER'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
