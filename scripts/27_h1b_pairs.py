#!/usr/bin/env python
"""H1b: concentrated-pair volume share, Sample-B, matching atlasB s06_pairs_rollup.

A "concentrated pair" = a wallet pair (a,b) where a wallet is FLAGGED: N>=100 trades AND its
counterparty-HHI (sum(n^2)/sum(n)^2 over counterparties) >= 0.5 (trades concentrated among few
counterparties -> collusion/wash candidate). pair_share = vol touching a flagged pair / total
vol; recip_share = both wallets flag each other (k=2). Pre-reg H1b threshold: point <= 0.1%,
bootstrap upper-95 <= 0.5%. DIRECT threshold test -- no cross-sample A-matching.

Built on v2 MAKER-FILL records (is_taker_order=FALSE) = true LP<->taker counterparty matches;
pair = (least,greatest) of the two wallet hashes; self-matches (a=b) EXCLUDED (that's H1c=0).
Per-class via feeclass token_cls (color only; the test is platform-level). Memory-safe chunked.

    python scripts/27_h1b_pairs.py --out data/parquet/atlas_v2/h1b_pairs_b.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from intellifi.fills import TAPE_V2_DIR  # noqa: E402
from intellifi import config as _cfg  # noqa: E402

TOKEN_CLS = _cfg.PARQUET_DIR / "atlas_v2" / "token_cls.parquet"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-block", type=int, default=86_126_978)
    ap.add_argument("--to-block", type=int, default=92_995_000)
    ap.add_argument("--out", default="data/parquet/atlas_v2/h1b_pairs_b.parquet")
    ap.add_argument("--json-out", default="docs/cohort_reports/h1b_pairs_b.json")
    ap.add_argument("--memory-limit", default="12GB")
    args = ap.parse_args()

    glob = (TAPE_V2_DIR / "blocks=*" / "part.parquet").as_posix()
    tmp = _cfg.DATA_DIR / "_h1b_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    dbf = tmp / "h1b.duckdb"
    if dbf.exists():
        dbf.unlink()
    con = duckdb.connect(str(dbf))
    con.execute("SET TimeZone='UTC'; SET preserve_insertion_order=false; SET threads=3")
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='150GB'")
    tok = pl.read_parquet(TOKEN_CLS)
    con.register("tk", tok.to_arrow())
    con.execute("CREATE TABLE token_cls AS SELECT * FROM tk")

    # chunked ingest of maker-fill pairs (undirected wallet-hash pair, exclude self-match)
    con.execute("""CREATE TABLE pr (a UBIGINT, b UBIGINT, cls VARCHAR, usdc DOUBLE)""")
    CHUNK = 300_000
    lo = args.from_block
    while lo <= args.to_block:
        hi = min(lo + CHUNK - 1, args.to_block)
        con.execute(f"""
            INSERT INTO pr
            SELECT least(hash(sub.maker), hash(sub.taker)) a,
                   greatest(hash(sub.maker), hash(sub.taker)) b,
                   COALESCE(c.cls, '__unmapped__') cls, sub.usdc
            FROM (SELECT maker, taker, token_id, usdc, tx_hash, evt_index
                  FROM read_parquet('{glob}', hive_partitioning=true)
                  WHERE event='OrderFilled' AND exchange IN ('v2_a','v2_b') AND is_taker_order=FALSE
                    AND block_number BETWEEN {lo} AND {hi} AND usdc>0 AND maker<>taker
                  QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index) = 1) sub
            LEFT JOIN token_cls c USING (token_id);
        """)
        print(f"  ingested chunk [{lo:,}..{hi:,}]", flush=True)
        lo = hi + 1

    # pair aggregates (a,b,cls) and (a,b)
    con.execute("CREATE TABLE p AS SELECT a, b, cls, SUM(usdc) vol, COUNT(*) n FROM pr GROUP BY 1,2,3")
    con.execute("DROP TABLE pr")
    con.execute("CREATE TABLE pab AS SELECT a, b, SUM(vol) vol, SUM(n) n FROM p GROUP BY 1,2")
    # wallet -> counterparty (both directions), wallet counterparty-HHI, flag concentrated wallets
    con.execute("""CREATE TABLE wc AS
        SELECT w, c, SUM(n) n, SUM(vol) vol FROM (
            SELECT a w, b c, n, vol FROM pab UNION ALL SELECT b w, a c, n, vol FROM pab) GROUP BY 1,2""")
    con.execute("""CREATE TABLE ws AS
        SELECT w, SUM(n) N, SUM(vol) V, SUM(n*n)*1.0/(SUM(n)*SUM(n)) hhi, COUNT(*) n_cp FROM wc GROUP BY 1""")
    con.execute("CREATE TABLE flag AS SELECT w FROM ws WHERE N>=100 AND hhi>=0.5")
    con.execute("""CREATE TABLE fp AS
        SELECT least(f.w, wc.c) a, greatest(f.w, wc.c) b, COUNT(*) k
        FROM flag f JOIN wc ON wc.w=f.w GROUP BY 1,2""")

    # per-class attribution + platform totals
    percls = con.execute("""
        SELECT p.cls, SUM(p.vol) vol,
               SUM(CASE WHEN fp.a IS NOT NULL THEN p.vol ELSE 0 END) pair_vol,
               SUM(CASE WHEN fp.k=2 THEN p.vol ELSE 0 END) recip_vol
        FROM p LEFT JOIN fp USING (a,b) GROUP BY 1 ORDER BY vol DESC""").df()
    percls["pair_share"] = percls.pair_vol / percls.vol
    percls["recip_share"] = percls.recip_vol / percls.vol
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(percls).write_parquet(args.out)

    tot_vol = float(percls.vol.sum())
    tot_pair = float(percls.pair_vol.sum())
    tot_recip = float(percls.recip_vol.sum())
    n_wallets = con.execute("SELECT COUNT(*) FROM ws").fetchone()[0]
    n_flagged = con.execute("SELECT COUNT(*) FROM flag").fetchone()[0]
    n_pairs = con.execute("SELECT COUNT(*) FROM pab").fetchone()[0]

    # pair-level bootstrap upper-95 on the platform pair_share (resample pairs w/ replacement)
    ab = con.execute("""SELECT pab.vol, (fp.a IS NOT NULL)::INT flagged FROM pab LEFT JOIN fp USING (a,b)""").df()
    vol = ab["vol"].to_numpy(); fl = ab["flagged"].to_numpy().astype(bool); m = len(vol)
    rng = np.random.default_rng(42)
    B = 1000 if m <= 20_000_000 else 300
    shares = np.empty(B)
    fvol = vol * fl
    for i in range(B):
        idx = rng.integers(0, m, m)
        shares[i] = fvol[idx].sum() / vol[idx].sum()
    up95 = float(np.quantile(shares, 0.95))

    rep = {
        "platform_pair_share": tot_pair / tot_vol,
        "platform_recip_share": tot_recip / tot_vol,
        "bootstrap_upper95_pair_share": up95,
        "bootstrap_n": B,
        "thresholds": {"point_max": 0.001, "upper95_max": 0.005},
        "point_pass": (tot_pair / tot_vol) <= 0.001,
        "upper95_pass": up95 <= 0.005,
        "n_wallets": int(n_wallets), "n_flagged_wallets": int(n_flagged), "n_pairs": int(n_pairs),
        "total_vol": tot_vol, "flagged_pair_vol": tot_pair,
        "per_class": percls.to_dict(orient="records"),
    }
    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"\nPLATFORM pair_share = {tot_pair/tot_vol:.6f} (point<=0.001? {rep['point_pass']}) "
          f"| bootstrap upper95 = {up95:.6f} (<=0.005? {rep['upper95_pass']})", flush=True)
    print(f"recip_share = {tot_recip/tot_vol:.6f} | n_wallets={n_wallets:,} flagged={n_flagged:,} pairs={n_pairs:,}", flush=True)
    print("per-class pair_share:", flush=True)
    for r in percls.itertuples():
        print(f"  {r.cls:18s} pair_share={r.pair_share:.6f}  vol={r.vol:,.0f}", flush=True)

    # flagged-pair rows (a, b, k, pair_vol, pair_n) for the peer's optional wallet-level resample
    fpr_out = str(Path(args.out).with_name("h1b_flagged_pairs_b.parquet"))
    con.execute(f"""COPY (SELECT fp.a, fp.b, fp.k, pab.vol pair_vol, pab.n pair_n
                        FROM fp JOIN pab USING (a,b)) TO '{fpr_out}' (FORMAT PARQUET)""")
    nfp = con.execute("SELECT COUNT(*) FROM fp").fetchone()[0]
    print(f"flagged-pair rows: {nfp:,} -> {fpr_out}", flush=True)

    con.close()
    for pth in (dbf, dbf.with_suffix(".duckdb.wal")):
        try:
            pth.unlink()
        except OSError:
            pass
    print("H1B_DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
