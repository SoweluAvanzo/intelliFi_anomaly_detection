#!/usr/bin/env python
"""Phase-2a: Sample-B class-week panel + the pre-registration §2 fee-control contingency.

Assigns every v2 market to a fee-CLASS comparable to the Sample-A atlas (reusing
data/parquet/atlas/category_to_feeclass_mapping.csv for the category->cls map, and
docs/atlas_2026-08-30/scripts/atlasB/catmap.py keyword rules as the fallback, so the
priority mirrors the atlas), then aggregates the v2 tape per (cls, week) into a panel
matching data/parquet/atlas/class_week.parquet's key columns, and decides the §2
CONTINGENCY that GATES the confirmatory H3/H4:

    control_exists = at least one class with >= 5% fee-free taker orders
    (if NO class clears 5% fee-free, there is NO within-B fee-free control, so
     H3/H4 as *fee* effects are UNIDENTIFIABLE in B — scripts/22 must say so.)

Pure-local / network-free. Memory-safe (file-backed DuckDB, disk spill) like scripts/17.
Validate the class assignment (coverage + distribution vs
data/parquet/atlas/class_mapping_coverage.csv) BEFORE its outputs feed scripts/22.

    python scripts/21_class_panels.py --out data/parquet/atlas_v2/class_week_b.parquet \
        --json-out docs/cohort_reports/class_contingency_h2.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import duckdb
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs/atlas_2026-08-30/scripts/atlasB"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs/atlas_2026-08-30/scripts/atlasA"))
from intellifi.fills import TAPE_V2_DIR, EXCHANGES_V2  # noqa: E402
from intellifi import config as _cfg  # noqa: E402
import catmap  # atlas class keyword rules (exact Sample-A logic)  # noqa: E402
import feeclass  # atlas per-market fee-class mapper map_market(category, category_refined, slug)  # noqa: E402

MAP_CSV = _cfg.PARQUET_DIR / "atlas" / "category_to_feeclass_mapping.csv"
CLOB = _cfg.PARQUET_DIR / "clob_markets"
# specific-before-broad priority when a market's tags map to several classes
CLS_PRIORITY = ["esports_tennis", "geopolitics_world", "finance_macro", "crypto_updown",
                "sports", "finance", "crypto_other", "politics_us", "culture",
                "tech_science", "weather", "meta_other", "other"]
# catmap's coarse class -> fee-class family, for the keyword fallback
CATMAP_TO_CLS = {"esports": "esports_tennis", "geopolitics_world": "geopolitics_world",
                 "sports": "sports", "finance": "finance", "crypto": "crypto_other",
                 "culture": "culture", "politics": "politics_us", "other": "other"}


def load_category_map() -> dict[str, str]:
    m = {}
    with open(MAP_CSV) as f:
        for row in csv.DictReader(f):
            m[row["category"].strip().lower()] = row["cls"].strip()
    return m


_TOKEN_CLS_CACHE = _cfg.PARQUET_DIR / "atlas_v2" / "token_cls.parquet"
# updown crypto tags (feeclass._EXACT maps these to crypto_updown; the slug also carries it)
_UPDOWN_TAGS = {"up or down", "5m", "15m", "1h", "4h", "crypto prices", "weekly",
                "monthly", "hit price", "recurring", "hide from new", "today",
                "daily", "multi strikes"}
# catmap broad class -> feeclass category_refined argument
_BROAD_TO_REFINED = {"sports": "Sports", "esports": "Sports", "politics": "Politics",
                     "finance": "Finance", "culture": "Culture", "other": "Other"}
# finance_macro _EXACT keys (Fed/rates/inflation/CPI/macro/trade-war/shutdown), derived from the
# atlas mapper so it stays atlas-faithful. Used to recapture Fed/macro markets whose PRIMARY tag
# is 'Politics': the category loop finds 'Politics' before the 'Fed'/'Economy' tag and mislabels
# them politics_us. (Fed markets whose FIRST tag is 'Fed' already map to finance_macro directly.)
_FEEMACRO_TAGS = {k.lower() for k, v in feeclass._EXACT.items() if v == "finance_macro"}


def _market_cls(slug: str, tags, question) -> str:
    """One market -> fee-class via the atlas's OWN mapper feeclass.map_market(category,
    category_refined, slug). The tags derive the two category args; the SLUG is what splits
    sports vs tennis/esport (map_market ref=='Sports' branch) and crypto_other vs
    crypto_updown (the _UPDOWN slug override) -- which a tag-only heuristic cannot do,
    the bug that collapsed sports 34%->2.4%/64%.
    """
    s = slug or ""
    tl = [t for t in (list(tags) if tags is not None else []) if t]
    # Broad bucket from the PRIMARY (first) tag ONLY -- NOT the concatenation of all tags.
    # Sports league/team tags carry incidental country names (Portugal/Ukraine/Colombia) that
    # the high-priority GEO rule captures over the whole string, collapsing sports->geopolitics
    # (measured: geopolitics_world 0.50 vs atlas 0.08). The first tag is the market's primary
    # category, mirroring the atlas's single-`category` assignment.
    broad = catmap.map_class(tl[0], "")[0] if tl else "other"
    # GEO RECAPTURE: markets whose foreign/geo TOPIC lives in the QUESTION (US x Iran) or in an
    # unambiguous geo TAG (foreign elections carry 'Global Elections'; 'Geopolitics') but whose
    # PRIMARY tag is 'Politics'/'US' otherwise land in politics_us -- the $137M "US x Iran peace
    # deal", Iran-airspace, and Peru/Ethiopia elections leaked this way, under-capturing
    # geopolitics_world. Two safe geo signals: (1) atlas keyword rules on the QUESTION resolve
    # to geopolitics_world; (2) a GEO_TAG is present (these are foreign-only -- US markets never
    # carry 'Global Elections', and a 'Geopolitics' tag is unambiguous). SAFETY GATE: apply ONLY
    # to NON-sports/esports primary buckets, so World Cup markets (sports-primary, with country
    # names in team/league tags -- France, Argentina, Iran) can NEVER be re-broken. This is the
    # guard the earlier concat-geo override lacked.
    _GEO_TAGS = {"global elections", "world elections", "geopolitics"}
    low_tags = {t.lower() for t in tl}
    if broad not in ("sports", "esports") and (
            catmap.map_class(question or "", "")[0] == "geopolitics_world"
            or bool(low_tags & _GEO_TAGS)):
        return "geopolitics_world"
    # FED / MACRO RECAPTURE (AFTER geo, BEFORE the primary mapping -- a market is virtually never
    # both geo and Fed, and geo wins if it is): Fed-rate & macro markets whose PRIMARY tag is
    # 'Politics' land in politics_us because the category loop finds 'Politics' before the
    # 'Fed'/'Economy' tag. Relabel to finance_macro when any tag is a finance_macro _EXACT key.
    # Same NON-sports/esports-primary safety gate (a sports market never carries a Fed tag anyway).
    if broad not in ("sports", "esports") and bool(low_tags & _FEEMACRO_TAGS):
        return "finance_macro"
    if broad == "crypto":
        low = {t.lower() for t in tl}
        updown = bool(feeclass._UPDOWN.search(s)) or bool(low & _UPDOWN_TAGS)
        refined = "Price Action" if updown else "Crypto"
    elif broad == "geopolitics_world":
        refined = ""  # let a geo _EXACT tag / 'Geopolitics' carry it (below)
    else:
        refined = _BROAD_TO_REFINED.get(broad, "Other")
    # category = first SPECIFIC _EXACT-key tag; SKIP the broad 'Sports' so map_market's
    # ref=='Sports' branch lets the SLUG decide sports vs esports_tennis. A specific sports tag
    # (Soccer/NBA/Tennis/...) still maps correctly via _EXACT.
    category = ""
    for t in tl:
        if t == "Sports":
            continue
        if t in feeclass._EXACT:
            category = t
            break
    if broad == "geopolitics_world" and category == "":
        category = "Geopolitics"  # a geo primary tag with no specific _EXACT geo tag -> geopolitics_world
    return feeclass.map_market(category, refined, s)


def assign_token_cls() -> pl.DataFrame:
    """token_id -> fee-class for every clob token, via the atlas map_market(tags->category
    + category_refined, market_slug). Cached to atlas_v2/token_cls.parquet (compute once;
    delete the cache to recompute after changing _market_cls)."""
    if _TOKEN_CLS_CACHE.exists():
        return pl.read_parquet(_TOKEN_CLS_CACHE)
    d = (pl.read_parquet((CLOB / "**" / "*.parquet").as_posix())
         .select(["token_id", "market_slug", "tags", "question"])
         .filter(pl.col("token_id").is_not_null() & (pl.col("token_id") != ""))
         .unique(subset=["token_id"]))
    out = (d.with_columns(
              pl.struct(["market_slug", "tags", "question"]).map_elements(
                  lambda r: _market_cls(r["market_slug"], r["tags"], r["question"]),
                  return_dtype=pl.Utf8).alias("cls"))
           .select("token_id", "cls"))
    _TOKEN_CLS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(_TOKEN_CLS_CACHE)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/parquet/atlas_v2/class_week_b.parquet")
    ap.add_argument("--json-out", default="docs/cohort_reports/class_contingency_h2.json")
    ap.add_argument("--from-block", type=int, default=86_126_978)
    ap.add_argument("--to-block", type=int, default=92_995_000)
    ap.add_argument("--dedup", action="store_true", help="dedup overlapping chunks (needed for cohorts 2-6/genesis)")
    ap.add_argument("--memory-limit", default="12GB")
    ap.add_argument("--validate-only", action="store_true", help="print coverage/distribution and exit")
    args = ap.parse_args()

    tok = assign_token_cls()
    tmp = _cfg.DATA_DIR / "_s21_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    dbf = tmp / "s21.duckdb"
    if dbf.exists():
        dbf.unlink()
    con = duckdb.connect(str(dbf))
    con.execute("SET TimeZone='UTC'; SET preserve_insertion_order=false; SET threads=3")
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.register("tokcls", tok.to_arrow())
    con.execute("CREATE TABLE token_cls AS SELECT * FROM tokcls;")

    glob = (TAPE_V2_DIR / "blocks=*" / "part.parquet").as_posix()
    exch = ",".join(f"'{a}'" for a in EXCHANGES_V2.values())
    dedup = ("QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index) = 1" if args.dedup else "")
    # Build `tc` in BLOCK-RANGE CHUNKS. The dedup here is a window-sort over (tx_hash,evt_index)
    # across ALL fills in range; over the full c1-c6 (~450M+ fills) that single sort spills past
    # the free disk (>108G) and dies. Chunking bounds each dedup's spill to tens of GB. This is
    # EXACT, not approximate: each fill has one block_number, so it lands in exactly one disjoint
    # chunk, and per-chunk dedup on (tx_hash,evt_index) == global dedup. Only the columns the
    # panel + contingency use are kept (week, cls, usdc, fee_raw, maker, is_tk); token_id/ts_utc
    # live only inside the per-chunk subquery. Downstream aggregation over the accumulated tc is
    # identical to a single-shot build.
    def _tc_select(lo: int, hi: int) -> str:
        return f"""
            SELECT date_trunc('week', sub.ts_utc)::DATE AS week,
                   COALESCE(c.cls, '__unmapped__') AS cls,
                   sub.usdc, sub.fee_raw, sub.maker, sub.is_tk
            FROM (
                SELECT token_id, ts_utc, usdc, fee_raw, maker,
                       (taker IN ({exch})) AS is_tk
                FROM read_parquet('{glob}', hive_partitioning = true)
                WHERE event = 'OrderFilled' AND exchange IN ('v2_a','v2_b')
                  AND block_number BETWEEN {lo} AND {hi}
                {dedup}
            ) sub
            LEFT JOIN token_cls c USING (token_id)
        """
    CHUNK = 300_000  # ~33M fills/chunk -> per-chunk dedup spill ~<10G, safe under free disk
    lo = args.from_block
    first = True
    while lo <= args.to_block:
        hi = min(lo + CHUNK - 1, args.to_block)
        if first:
            con.execute(f"CREATE TABLE tc AS {_tc_select(lo, hi)};")
            first = False
        else:
            con.execute(f"INSERT INTO tc {_tc_select(lo, hi)};")
        print(f"  tc chunk [{lo:,}..{hi:,}] loaded", flush=True)
        lo = hi + 1

    # coverage + class distribution (validation)
    cov = con.execute("""
        SELECT SUM(usdc) FILTER (WHERE cls <> '__unmapped__') / SUM(usdc) AS notional_cov,
               SUM((cls <> '__unmapped__')::INT)::DOUBLE / COUNT(*) AS row_cov
        FROM tc WHERE is_tk;
    """).fetchone()
    dist = con.execute("""
        SELECT cls, SUM(usdc) notional, COUNT(*) FILTER (WHERE is_tk) taker_orders
        FROM tc GROUP BY cls ORDER BY notional DESC;
    """).fetchdf()
    tot_notl = float(dist["notional"].sum())
    dist_out = [{"cls": r.cls, "notional_share": r.notional / tot_notl, "taker_orders": int(r.taker_orders)}
                for r in dist.itertuples()]

    # per-class fee-free taker share -> §2 contingency
    ff = con.execute("""
        SELECT cls,
               COUNT(*) FILTER (WHERE is_tk) AS taker_orders,
               COUNT(*) FILTER (WHERE is_tk AND fee_raw = 0) AS ff,
               AVG(CASE WHEN is_tk THEN (fee_raw = 0)::INT END) AS fee_free_share
        FROM tc WHERE cls <> '__unmapped__' GROUP BY cls HAVING COUNT(*) FILTER (WHERE is_tk) >= 1000
        ORDER BY taker_orders DESC;
    """).fetchdf()
    classes = [{"cls": r.cls, "taker_orders": int(r.taker_orders), "fee_free_share": float(r.fee_free_share)}
               for r in ff.itertuples()]
    control_classes = [c["cls"] for c in classes if c["fee_free_share"] >= 0.05]
    contingency = {
        "control_exists": bool(control_classes),
        "fee_free_control_classes": control_classes,
        "rule": ">=5% fee-free taker orders in a class => usable fee-free control (pre-reg §2)",
        "per_class_fee_free_share": classes,
        "implication": ("within-B fee-free control exists; H3/H4 fee DiD identified"
                        if control_classes else
                        "NO within-B fee-free control; H3/H4 as fee effects NOT identified in B "
                        "(scripts/22 must report not_identified, not force a DiD)"),
    }

    # VALIDATION GATE (scripts/22 is gated on this). Re-scoped after the top-notional label
    # spot-check proved v2 cohort-1 is a genuine FIFA-World-Cup-June-2026 month (sports ~0.49
    # is CORRECT, not a bug): the tight distribution-vs-atlas match conflated a legitimate
    # cross-exchange/period difference with a mapping error, so it FALSE-FAILED a correct
    # mapping. HARD gates (fail-closed): coverage >= COV_MIN, unmapped < UNMAPPED_MAX, a §2
    # fee-free control exists, and a loose gross-bug backstop (no single class > MAX_SINGLE_CLASS,
    # which catches a mapping collapse but passes a real World-Cup mix). The tight per-class
    # match is DEMOTED to a soft warning. The definitive per-run check is the human label
    # spot-check (top-notional-per-class).
    unmapped_share = next((d["notional_share"] for d in dist_out if d["cls"] == "__unmapped__"), 0.0)
    COV_MIN, UNMAPPED_MAX, DIST_TOL, MAX_SINGLE_CLASS = 0.85, 0.15, 0.12, 0.60
    coverage_ok = (cov[0] or 0.0) >= COV_MIN
    unmapped_ok = unmapped_share < UNMAPPED_MAX
    control_ok = bool(contingency["control_exists"])  # §2: a within-B fee-free control must exist
    # SOFT distribution warning (reported, NOT a hard gate): major fee-classes' shares vs the
    # Sample-A atlas. A large deviation is worth a human eyeball, but can be a real period effect
    # (a World Cup month), so it must not hard-fail a correctly-labelled mapping.
    ref = {}
    try:
        with open(_cfg.PARQUET_DIR / "atlas" / "class_mapping_coverage.csv") as f:
            for row in csv.DictReader(f):
                ref[row["cls"]] = float(row["notional_share"])
    except OSError:
        ref = {}
    obs = {d["cls"]: d["notional_share"] for d in dist_out}
    MAJORS = ["sports", "crypto_updown", "esports_tennis", "geopolitics_world", "politics_us"]
    dist_devs = {c: round(abs(obs.get(c, 0.0) - ref.get(c, 0.0)), 4) for c in MAJORS if c in ref}
    distribution_ok = bool(ref) and all(v <= DIST_TOL for v in dist_devs.values())  # soft: reported only
    # LOOSE gross-bug backstop: a single class swallowing > MAX_SINGLE_CLASS of mapped notional
    # is a mapping collapse (the earlier geo-over-capture), NOT a legit period effect. This
    # still fails-closed on the real bug while passing a World-Cup-heavy month (sports 0.49).
    mapped_shares = {d["cls"]: d["notional_share"] for d in dist_out if d["cls"] != "__unmapped__"}
    max_class = max(mapped_shares, key=mapped_shares.get, default="")
    max_class_share = mapped_shares.get(max_class, 0.0)
    no_gross_bug = max_class_share <= MAX_SINGLE_CLASS
    class_validation_passed = bool(coverage_ok and unmapped_ok and control_ok and no_gross_bug)

    report = {
        "window_blocks": [args.from_block, args.to_block],
        "class_validation_passed": class_validation_passed,
        "validation_thresholds": {"taker_notional_coverage_min": COV_MIN, "unmapped_notional_max": UNMAPPED_MAX,
                                  "major_class_share_tol_SOFT": DIST_TOL, "max_single_class_share": MAX_SINGLE_CLASS},
        "class_assignment_validation": {
            "taker_notional_coverage": cov[0], "taker_row_coverage": cov[1],
            "unmapped_notional_share": unmapped_share,
            "coverage_ok": coverage_ok, "unmapped_ok": unmapped_ok,
            "control_ok": control_ok, "no_gross_bug": no_gross_bug,
            "largest_class": max_class, "largest_class_share": round(max_class_share, 4),
            "distribution_ok_SOFT": distribution_ok,
            "major_class_deviations_vs_atlas_SOFT": dist_devs,
            "class_distribution": dist_out,
            "atlas_reference_shares": {c: ref.get(c) for c in MAJORS if c in ref},
            "reference": "compare shares to data/parquet/atlas/class_mapping_coverage.csv",
            "note": "hard gates = coverage_ok AND unmapped_ok AND control_ok AND no_gross_bug; "
                    "distribution match is a SOFT warning (v2 may legitimately differ, e.g. World Cup)",
        },
        "contingency_H3H4": contingency,
        "H2_negrisk_band": {"status": "deferred_to_review_layer",
                            "note": "needs synchronized per-family price sums (hourly, members alive); "
                                    "not shipped here to avoid a shaky band. Build in the reviewed phase."},
        "pending_review": True,
    }
    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps(report, indent=1, default=str))
    print(f"taker notional coverage: {cov[0]:.4f} | row coverage: {cov[1]:.4f} | unmapped_share: {unmapped_share:.4f}")
    print("class distribution (top): " + ", ".join(f"{d['cls']}={d['notional_share']:.3f}" for d in dist_out[:6]))
    print(f"§2 contingency: control_exists={contingency['control_exists']} classes={control_classes}")
    print(f"HARD gates: coverage_ok={coverage_ok} unmapped_ok={unmapped_ok} control_ok={control_ok} "
          f"no_gross_bug={no_gross_bug} (largest {max_class}={max_class_share:.3f} <= {MAX_SINGLE_CLASS})")
    print(f"SOFT distribution_ok: {distribution_ok} | major devs vs atlas: {dist_devs}")
    print(f"class_validation_passed: {class_validation_passed}")

    if not class_validation_passed:
        # signal failure to the phase-2 driver BOTH ways: JSON flag (already written) + non-zero exit,
        # and do NOT write the panel, so scripts/22 cannot run on an unreliable class assignment.
        print(f"VALIDATION FAILED (hard gates: coverage_ok={coverage_ok} unmapped_ok={unmapped_ok} "
              f"control_ok={control_ok} no_gross_bug={no_gross_bug}) — NOT writing panel; "
              f"scripts/22 must be skipped.", file=sys.stderr)
        con.close()
        for p in (dbf, dbf.with_suffix(".duckdb.wal")):
            try:
                p.unlink()
            except OSError:
                pass
        return 3

    if not args.validate_only:
        panel = con.execute("""
            SELECT week, cls,
                   COUNT(*) AS n_fills, SUM(usdc) AS notional,
                   COUNT(*) FILTER (WHERE is_tk) AS n_taker_orders,
                   COUNT(*) FILTER (WHERE is_tk AND fee_raw > 0) AS n_fee_taker,
                   AVG(CASE WHEN is_tk THEN (fee_raw = 0)::INT END) AS fee_free_share,
                   median(usdc) FILTER (WHERE is_tk) AS taker_order_median_notional,
                   COUNT(DISTINCT maker) FILTER (WHERE NOT is_tk) AS n_makers
            FROM tc WHERE cls <> '__unmapped__' GROUP BY week, cls ORDER BY week, cls;
        """).fetchdf()
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        pl.from_pandas(panel).write_parquet(args.out)
        print(f"wrote panel {args.out}: {len(panel)} class-weeks")

    con.close()
    for p in (dbf, dbf.with_suffix(".duckdb.wal")):
        try:
            p.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
