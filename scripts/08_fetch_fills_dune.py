"""Stage 8 (Phase 3 prototype): reconstruct on-chain order fills via Dune and
reconcile them against the Data API sample.

Usage:
    # one-off: save the query on Dune (paste data/export/dune_fills_query.sql
    # in the editor with parameters token_ids / start_time / end_time as text,
    # or let the script try to create it), then:
    python scripts/08_fetch_fills_dune.py --query-id 1234567 --window-days 14 -v
    python scripts/08_fetch_fills_dune.py --reconcile-only            # no network

Idempotent per market (skip-if-exists; --overwrite to refetch). Every Dune
result page is written raw to data/raw/dune/fills/ before normalisation.
One market at a time, its trading life chunked into ``--window-days``
sub-windows (one Dune execution each) to stay under the free tier's 2-minute
execution cap; partitions are written only when a market completes.
"""
from __future__ import annotations

import argparse
import logging
import sys

import polars as pl

from intellifi import config
from intellifi.fills import (FILLS_DIR, FILLS_SQL_TEMPLATE, QUERY_PARAMETERS, DuneClient,
                             fetched_markets, market_windows, normalise_fills, reconcile_fills,
                             register_fills_view, token_map, write_fills, write_raw)
from intellifi.warehouse import open_warehouse

QUERY_SQL_OUT = config.DATA_DIR / "export" / "dune_fills_query.sql"
RECON_DIR = config.PARQUET_DIR / "fills_reconciliation"


def report(con) -> None:
    register_fills_view(con)
    n = con.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
    if n == 0:
        print("no fills on disk yet"); return
    r = reconcile_fills(con)
    RECON_DIR.mkdir(parents=True, exist_ok=True)
    for k, v in r.items():
        v.write_parquet(RECON_DIR / f"{k}.parquet", compression="zstd")
    tm, cons, pm, pw = r["taker_match"], r["conservation"], r["per_market"], r["per_wallet"]
    tot_tr, tot_found, tot_exact = tm["n_trades"].sum(), tm["n_found"].sum(), tm["n_exact"].sum()
    print(f"\n=== Invariant 1 — taker reconciliation over {tm.height} markets")
    print(f"  Data API rows: {tot_tr:,}  found in fills: {tot_found:,} ({tot_found/tot_tr:.1%})  "
          f"exact (shares, price, side): {tot_exact:,} ({tot_exact/tot_tr:.1%})")
    bad = tm.filter(pl.col("exact_rate") < 0.999)
    if bad.height:
        print(f"  markets below 99.9% exact: {bad.height} (worst: {bad.head(3).select('condition_id','exact_rate').to_dicts()})")
    print("\n=== Exchange addresses seen as `taker` (must all be known exchanges)")
    print(r["taker_addresses"].to_pandas().to_string(index=False))
    print("\n=== Invariant 2 — conservation per transaction")
    print(cons.to_pandas().round(4).to_string(index=False))
    print("\n=== Invariants 3 & 4 — coverage gain and completeness (top 10 markets by volume)")
    cols = ["slug", "n_maker_fills", "n_taker_orders", "n_sampled_trades", "taker_order_coverage",
            "notional_coverage", "share_volume_vs_gamma", "hours_of_history_recovered", "n_wallets", "n_sampled_wallets"]
    print(pm.select(cols).head(10).to_pandas().round(3).to_string(index=False))
    med = pm.select(pl.col("taker_order_coverage").median(), pl.col("notional_coverage").median(),
                    pl.col("share_volume_vs_gamma").median(), pl.col("hours_of_history_recovered").median()).row(0)
    fmt = lambda x, f: (f % x) if x is not None else "n/a"
    print(f"  medians — taker-order coverage of the feed: {fmt(med[0], '%.3f')}; notional coverage: {fmt(med[1], '%.3f')}; "
          f"completeness (taker shares / Gamma volumeClob): {fmt(med[2], '%.3f')}; extra history: {fmt(med[3], '%.0f')} h")
    seen = pw.filter(pl.col("fills_as_taker").is_not_null())
    if seen.height:
        vis = seen["visibility_in_feed"].median()
        maker_share = (seen["fills_as_maker"].sum() / (seen["fills_as_maker"].sum() + seen["fills_as_taker"].sum()))
        print(f"\n=== Universe wallets: {seen.height}/{pw.height} seen; median feed visibility {vis:.1%}; "
              f"maker-leg share of their fills {maker_share:.1%}")
    print(f"\nreconciliation tables -> {RECON_DIR}")


WINDOW_INDEX = config.RAW_DIR / "dune" / "fills" / "windows.json"


def _window_key(tokens, a, b, fmt) -> str:
    import hashlib
    h = hashlib.sha256(",".join(sorted(tokens)).encode()).hexdigest()[:16]
    return f"{a.strftime(fmt)}|{b.strftime(fmt)}|{h}"


def _load_index() -> dict:
    import json
    return json.loads(WINDOW_INDEX.read_text()) if WINDOW_INDEX.exists() else {}


def _save_index(idx: dict) -> None:
    import json
    WINDOW_INDEX.parent.mkdir(parents=True, exist_ok=True)
    WINDOW_INDEX.write_text(json.dumps(idx, indent=1, sort_keys=True))


def _read_raw(execution_id: str) -> list:
    import json
    p = config.RAW_DIR / "dune" / "fills" / f"{execution_id}.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def run_split_on_timeout(client, args, tokens, a, b, fmt, depth: int = 0, counter: dict | None = None) -> list:
    """Execute one window; on an engine timeout split it in half (recursively,
    down to 12 h) so the free tier's 2-minute cap costs a retry, not a failure.
    Windows already executed (same start, end and token set) are replayed from
    their raw pages instead of being re-executed — resuming never costs credits."""
    from intellifi.fills import DuneError
    idx = _load_index()
    key = _window_key(tokens, a, b, fmt)
    if key in idx:
        rows = _read_raw(idx[key])
        print(f"    cached {a.date()} -> {b.date()} ({len(rows):,} rows, exec {idx[key]})")
        return rows
    if counter is not None and args.max_windows is not None and counter["new"] >= args.max_windows:
        raise StopIteration
    params = {"token_ids": ",".join(tokens), "start_time": a.strftime(fmt), "end_time": b.strftime(fmt)}
    try:
        ex, rows = client.run(args.query_id, params, performance=args.performance)
        write_raw(rows, ex)
        idx = _load_index(); idx[key] = ex; _save_index(idx)
        if counter is not None:
            counter["new"] += 1
        return rows
    except DuneError as e:
        if "TIMEOUT" not in str(e).upper() or (b - a).total_seconds() < 12 * 3600 or depth > 6:
            raise
        mid = a + (b - a) / 2
        print(f"    timeout on {a} -> {b}; splitting")
        return run_split_on_timeout(client, args, tokens, a, mid, fmt, depth + 1, counter) + \
               run_split_on_timeout(client, args, tokens, mid, b, fmt, depth + 1, counter)


def run_shared_windows(client, args, todo: pl.DataFrame, tmap: dict) -> None:
    """Calendar windows over the union of the markets' lifetimes; each execution
    carries the tokens of every market alive in that window. Fills are
    accumulated per market and each partition is written once its last window
    has been fetched, so a crash leaves only complete partitions behind."""
    from datetime import timedelta
    from collections import defaultdict
    pad = timedelta(days=1)
    todo = todo.with_columns(pl.coalesce(pl.col("closed_time"), pl.col("end_date")).alias("close"))
    t0, t1 = todo["created_at"].min() - pad, todo["close"].max() + pad
    windows = []
    cur = t0
    while cur < t1:
        windows.append((cur, min(cur + timedelta(days=args.window_days), t1))); cur = windows[-1][1]
    last_window = {}
    for wi, (a, b) in enumerate(windows):
        for row in todo.filter((pl.col("created_at") - pad < b) & (pl.col("close") + pad > a)).iter_rows(named=True):
            last_window[row["condition_id"]] = wi
    fmt = "%Y-%m-%d %H:%M:%S"
    acc: dict[str, list[pl.DataFrame]] = defaultdict(list)
    counter = {"new": 0}
    print(f"shared windows: {len(windows)} x {args.window_days} d over {t0.date()} -> {t1.date()}")
    for wi, (a, b) in enumerate(windows):
        alive = todo.filter((pl.col("created_at") - pad < b) & (pl.col("close") + pad > a))
        if alive.height == 0:
            continue
        tokens = [str(t) for toks in alive["clob_token_ids"] for t in (list(toks) if toks is not None else [])]
        try:
            rows = run_split_on_timeout(client, args, tokens, a, b, fmt, counter=counter)
        except StopIteration:
            print(f"  stopped after {counter['new']} new execution(s) (--max-windows); "
                  f"partial markets are kept in raw pages and replayed on the next run")
            return
        df = normalise_fills(rows, tmap)
        print(f"  window {wi + 1}/{len(windows)} {a.date()} -> {b.date()}: {alive.height} markets, {len(rows):,} rows")
        for cid, part in df.filter(pl.col("condition_id").is_not_null()).partition_by("condition_id", as_dict=True).items():
            acc[cid[0] if isinstance(cid, tuple) else cid].append(part)
        for cid, lw in last_window.items():
            if lw == wi and acc.get(cid):
                full = pl.concat(acc.pop(cid)).unique(subset=["tx_hash", "evt_index"])
                write_fills(full)
                print(f"    completed {cid[:14]}…: {full.height:,} fills, {int(full['is_taker_order'].sum()):,} taker orders")
    for cid, parts in acc.items():   # markets whose last window returned nothing after data
        full = pl.concat(parts).unique(subset=["tx_hash", "evt_index"]); write_fills(full)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query-id", type=int, help="saved Dune query id (see --create-query)")
    ap.add_argument("--create-query", action="store_true", help="try to create the saved query via API")
    ap.add_argument("--condition-ids", nargs="*", help="markets to fetch (required unless --all)")
    ap.add_argument("--all", action="store_true", help="fetch every market in markets.parquet (many Dune executions)")
    ap.add_argument("--window-days", type=int, default=14,
                    help="sub-window length per Dune execution (free tier: 2-minute cap per execution)")
    ap.add_argument("--max-windows", type=int, default=None,
                    help="shared-windows mode: stop after this many NEW executions (cost probe)")
    ap.add_argument("--shared-windows", action="store_true",
                    help="one execution per calendar window covering EVERY market alive in it "
                         "(cost is driven by the scanned window, not by the token count) — "
                         "far fewer executions than per-market fetching")
    ap.add_argument("--update-query", action="store_true", help="push the current SQL template to the saved query")
    ap.add_argument("--performance", default=None, choices=("medium", "large"),
                    help="paid tiers only; omit on the free plan")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--reconcile-only", action="store_true")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args()
    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")

    QUERY_SQL_OUT.parent.mkdir(parents=True, exist_ok=True)
    QUERY_SQL_OUT.write_text(FILLS_SQL_TEMPLATE)
    con = open_warehouse(":memory:")
    if args.reconcile_only:
        report(con); return 0

    client = DuneClient()
    if args.create_query and not args.query_id:
        args.query_id = client.create_query("intellifi: Polymarket OrderFilled by token", FILLS_SQL_TEMPLATE,
                                            QUERY_PARAMETERS)
        print(f"created Dune query {args.query_id}")
        (config.RAW_DIR / "dune").mkdir(parents=True, exist_ok=True)
        (config.RAW_DIR / "dune" / "query_id.txt").write_text(str(args.query_id))
    qid_file = config.RAW_DIR / "dune" / "query_id.txt"
    if not args.query_id and qid_file.exists():
        args.query_id = int(qid_file.read_text().strip()); print(f"using saved Dune query {args.query_id}")
    if not args.query_id:
        ap.error(f"--query-id required (SQL written to {QUERY_SQL_OUT}; save it on Dune, or use --create-query)")

    markets = con.sql("SELECT * FROM markets ORDER BY volume_clob DESC NULLS LAST").pl()
    if args.condition_ids:
        markets = markets.filter(pl.col("condition_id").is_in(args.condition_ids))
        if markets.height != len(set(args.condition_ids)):
            ap.error("some --condition-ids are not in markets.parquet")
    elif not args.all:
        # Guard: an empty --condition-ids (e.g. from a failed shell substitution)
        # must not silently turn into a full-corpus fetch.
        ap.error("give --condition-ids ... or --all explicitly")
    done = set() if args.overwrite else fetched_markets()
    todo = markets.filter(~pl.col("condition_id").is_in(list(done)))
    print(f"markets: {markets.height} total, {todo.height} to fetch, {len(done)} already on disk")
    tmap = token_map(markets)

    if args.update_query:
        client.update_query(args.query_id, FILLS_SQL_TEMPLATE, QUERY_PARAMETERS)
        print(f"updated Dune query {args.query_id} with the current SQL template")

    if args.shared_windows:
        run_shared_windows(client, args, todo, tmap)
        report(con)
        return 0

    for k, m in enumerate(todo.iter_rows(named=True)):
        tokens = [str(t) for t in (list(m["clob_token_ids"]) if m["clob_token_ids"] is not None else [])]
        windows = market_windows(m, args.window_days)
        print(f"[{k + 1}/{todo.height}] {m['slug'][:60]}  tokens={len(tokens)}  windows={len(windows)}")
        frames = []
        for start, end in windows:
            params = {"token_ids": ",".join(tokens), "start_time": start, "end_time": end}
            ex, rows = client.run(args.query_id, params, performance=args.performance)
            write_raw(rows, ex)
            df = normalise_fills(rows, tmap)
            print(f"    {start} -> {end}: {len(rows):,} rows (exec {ex})")
            frames.append(df)
        df = pl.concat(frames) if frames else normalise_fills([], tmap)
        df = df.filter((pl.col("condition_id") == m["condition_id"]) | pl.col("condition_id").is_null())
        if df.height == 0:
            print("    no fills returned — partition not written"); continue
        write_fills(df.unique(subset=["tx_hash", "evt_index"]))
        print(f"    -> {df.height:,} fills, {int(df['is_taker_order'].sum()):,} taker-order records, "
              f"{df.filter(pl.col('condition_id').is_null()).height} unmapped")
    report(con)
    return 0


if __name__ == "__main__":
    sys.exit(main())
