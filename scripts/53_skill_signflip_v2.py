#!/usr/bin/env python
"""V2 port of the sign-randomization skill test (scripts/31), on the v2 tape.

Replicates scripts/31's method (full maker+taker, decision unit = (wallet, condition) realised PnL,
Rademacher sign-flip null + split-half persistence) using scripts/28's VERIFIED v2 tape conventions:
  * GROSS from maker-fill records (is_taker_order=FALSE): taker=`taker`, taker_side = OPPOSITE of the
    maker `side`; won from token->ctf_v2_conditions. PAY = (won-price)*shares for BUY else (price-won)*shares.
  * Each fill credits the taker +PAY and the maker -PAY (zero-sum before fees).
  * token->condition_id and token->winning_outcome from ctf_v2_conditions (token0/token1).
  * DEDUP by (tx_hash, evt_index); exchange v2_a/v2_b; event OrderFilled; price in (0,1), shares>0.
Materialises the signed (w, condition, ts, pay) rows ONCE (block-partitioned) then does the hash-bucketed
sign-flip, so the tape is scanned once (not NB times). Writes docs/skill_signflip_v2.json.

  systemd-run --user --scope -p MemoryMax=9G .venv/bin/python scripts/53_skill_signflip_v2.py --out docs/skill_signflip_v2.json
  (smoke test:  --test 6   # only the first 6 block-partitions)
"""
from __future__ import annotations
import argparse, json, shutil, sys, time
from pathlib import Path
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                   # noqa: E402
from intellifi import config as _cfg            # noqa: E402

TAPE = "data/parquet/tape_v2/**/*.parquet"
REG = "data/parquet/ctf_v2_conditions.parquet"
STEP = 250_000
MIN = 5           # min positions to classify (matches scripts/31)
NB = 8            # wallet-hash buckets


def mc_p(d, a, n_sim, rng):
    """Upper-tail sign-flip p: P(sum(eps*d) >= a), eps Rademacher. (add-one smoothed)."""
    eps = rng.integers(0, 2, size=(n_sim, len(d))).astype(np.float64) * 2 - 1
    sims = eps @ d
    return float((np.sum(sims >= a) + 1) / (n_sim + 1))


def bh_discoveries(p, q):
    p = np.sort(p); n = len(p)
    thr = q * np.arange(1, n + 1) / n
    hits = np.flatnonzero(p <= thr)
    return int(hits.max() + 1) if len(hits) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/skill_signflip_v2.json")
    ap.add_argument("--memory-limit", default="6GB")
    ap.add_argument("--test", type=int, default=0, help="only the first N block-partitions (smoke test)")
    ap.add_argument("--resume", action="store_true", help="reuse existing <data>/_s53_tmp/signed parquet (skip materialisation)")
    ap.add_argument("--n-sim", type=int, default=2000)
    ap.add_argument("--n-sim-refine", type=int, default=20000)
    ap.add_argument("--k-mc-cap", type=int, default=2000)
    args = ap.parse_args()
    rng = np.random.default_rng(0)

    tmp = _cfg.DATA_DIR / "_s53_tmp"; sdir = tmp / "signed"
    resume = args.resume and sdir.exists() and any(sdir.glob("*.parquet"))
    if not resume:
        shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    else:
        (tmp / "w.db").unlink(missing_ok=True); (tmp / "spill").mkdir(exist_ok=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='70GB'")

    t0 = time.time()
    if not resume:
        # token -> (outcome_index, winning_outcome_index, condition_id)
        con.execute(f"""CREATE TABLE tokmap AS
            SELECT lower(token0) token_id, 0 outcome_index, winning_outcome_index, condition_id FROM read_parquet('{REG}')
              WHERE token0 IS NOT NULL AND winning_outcome_index IS NOT NULL
            UNION ALL
            SELECT lower(token1), 1, winning_outcome_index, condition_id FROM read_parquet('{REG}')
              WHERE token1 IS NOT NULL AND winning_outcome_index IS NOT NULL""")
        b0, b1 = con.sql(f"SELECT min(block_number), max(block_number) FROM read_parquet('{TAPE}', union_by_name=true)").fetchone()
        b0, b1 = int(b0), int(b1)
        WHERE = ("t.event='OrderFilled' AND t.exchange IN ('v2_a','v2_b') AND t.price>0 AND t.price<1 "
                 "AND t.shares>0 AND t.is_taker_order=FALSE AND t.block_number>={lo} AND t.block_number<{hi}")
        DEDUP = "QUALIFY row_number() OVER (PARTITION BY t.tx_hash, t.evt_index)=1"
        WON = "(CASE WHEN m.outcome_index=m.winning_outcome_index THEN 1 ELSE 0 END)"
        # taker_side = opposite of maker side; PAY from the taker's perspective
        PAY = (f"(CASE WHEN t.side='SELL' THEN ({WON}-t.price)*t.shares ELSE (t.price-{WON})*t.shares END)")
        # signed rows: taker +PAY, maker -PAY
        SEL = f"""
          SELECT lower(t.taker) w, m.condition_id grp, epoch(t.ts_utc::TIMESTAMP) bt, {PAY} pay
            FROM read_parquet('{TAPE}', union_by_name=true) t JOIN tokmap m ON m.token_id=lower(t.token_id)
            WHERE {WHERE} {DEDUP}
          UNION ALL
          SELECT lower(t.maker), m.condition_id, epoch(t.ts_utc::TIMESTAMP), -({PAY})
            FROM read_parquet('{TAPE}', union_by_name=true) t JOIN tokmap m ON m.token_id=lower(t.token_id)
            WHERE {WHERE} AND t.maker IS NOT NULL {DEDUP}"""
        # materialise signed rows once (block-partitioned)
        sdir.mkdir()
        ranges = list(range(b0, b1 + 1, STEP))
        if args.test:
            ranges = ranges[:args.test]
        tot = 0
        for i, lo in enumerate(ranges):
            pth = (sdir / f"p{i:04d}.parquet").as_posix()
            con.execute(f"COPY ({SEL.format(lo=lo, hi=lo+STEP)}) TO '{pth}' (FORMAT PARQUET, COMPRESSION zstd)")
            if i % 8 == 0 or i == len(ranges) - 1:
                tot = con.sql(f"SELECT count(*) FROM read_parquet('{(sdir/'*.parquet').as_posix()}')").fetchone()[0]
                print(f"  materialise {i+1}/{len(ranges)} signed_rows={tot:,} ({time.time()-t0:.0f}s)", flush=True)
    else:
        print("  [resume] reusing existing signed parquet", flush=True)
    con.execute(f"CREATE VIEW sg AS SELECT * FROM read_parquet('{(sdir/'*.parquet').as_posix()}')")
    split_ts = con.sql("SELECT approx_quantile(bt,0.5) FROM sg").fetchone()[0]

    # Collapse to compact decision-unit tables ONCE (spillable GROUP BYs over the 853M signed rows),
    # then run the sign-flip on the small tables. Avoids re-scanning the full tape per bucket (the OOM
    # in the naive version) while producing byte-identical statistics.
    # Integer-hash the (wallet, condition) keys so the 167M-group collapse fits in RAM with minimal spill
    # (string keys, 42+66-char hex, were ~5x larger and overflowed memory/disk). hash() is UINT64; at
    # 1.1M wallets / 167M decision units the collision probability is ~0 (expected <1 pair), negligible
    # for aggregate statistics. Identities are never reported, only grouped/counted.
    con.execute(f"""COPY (SELECT hash(w) w, hash(grp) grp, SUM(pay) d, COUNT(*) cf FROM sg GROUP BY hash(w), hash(grp))
        TO '{(tmp/'dt_all.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    con.execute(f"CREATE VIEW dta AS SELECT * FROM read_parquet('{(tmp/'dt_all.parquet').as_posix()}')")
    con.execute(f"""COPY (SELECT w, SUM(d) A, SUM(d*d) S2p, COUNT(*) k FROM dta GROUP BY w)
        TO '{(tmp/'ws_all.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    con.execute(f"CREATE VIEW wsa AS SELECT * FROM read_parquet('{(tmp/'ws_all.parquet').as_posix()}')")
    n_total = int(con.sql("SELECT count(*) FROM wsa").fetchone()[0])
    print(f"  collapsed decision units; {n_total:,} wallets ({time.time()-t0:.0f}s)", flush=True)

    # persistence: per (w, period) realised PnL + #conditions (COUNT(*) after GROUP BY w,period,grp = COUNT(DISTINCT grp))
    con.execute(f"""COPY (
        WITH dp AS (SELECT hash(w) w, CASE WHEN bt<{split_ts} THEN 1 ELSE 2 END period, hash(grp) grp, SUM(pay) pay
                    FROM sg GROUP BY hash(w), period, hash(grp))
        SELECT w, period, SUM(pay) pnl, COUNT(*) k FROM dp GROUP BY w, period)
        TO '{(tmp/'dp_all.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
    con.execute(f"CREATE VIEW dpa AS SELECT * FROM read_parquet('{(tmp/'dp_all.parquet').as_posix()}')")

    # pull classifiable decision units in hash buckets over the COMPACT table (cheap scans, bounded .df())
    ids_all, d_all, seglen_all, A_all, S2p_all, k_all, p1p2 = [], [], [], [], [], [], []
    for b in range(NB):
        arr = con.sql(f"""SELECT d.w, d.d FROM dta d JOIN wsa s ON s.w=d.w
            WHERE s.k>={MIN} AND s.S2p>0 AND (d.w%{NB})={b} ORDER BY d.w, d.grp""").df()
        if len(arr):
            ws_ = arr["w"].to_numpy(); ds_ = arr["d"].to_numpy().astype(np.float64)
            bnd = np.flatnonzero(np.r_[True, ws_[1:] != ws_[:-1], True]); st = bnd[:-1]
            ids_all.append(ws_[st]); d_all.append(ds_); seglen_all.append(np.diff(bnd))
            A_all.append(np.add.reduceat(ds_, st)); S2p_all.append(np.add.reduceat(ds_*ds_, st)); k_all.append(np.diff(bnd))
        print(f"  bucket {b+1}/{NB} ({time.time()-t0:.0f}s)", flush=True)
    pr = con.sql(f"""SELECT a.pnl p1, b2.pnl p2 FROM dpa a JOIN dpa b2 ON a.w=b2.w
        WHERE a.period=1 AND b2.period=2 AND a.k>={MIN} AND b2.k>={MIN}""").df()
    if len(pr): p1p2.append(pr[["p1", "p2"]].to_numpy())

    ids = np.concatenate(ids_all); ds = np.concatenate(d_all); seglen = np.concatenate(seglen_all)
    A = np.concatenate(A_all); S2p = np.concatenate(S2p_all); k = np.concatenate(k_all)
    starts = np.r_[0, np.cumsum(seglen)[:-1]]; n_cl = len(ids)
    with np.errstate(invalid="ignore", divide="ignore"):
        z_pos = np.nan_to_num(A/np.sqrt(S2p), nan=0.0, posinf=0.0, neginf=0.0)

    from scipy import stats as _st
    p_up = np.empty(n_cl); p_dn = np.empty(n_cl)
    for i in range(n_cl):
        d = ds[starts[i]:starts[i]+seglen[i]]; a = float(A[i])
        if k[i] > args.k_mc_cap:
            zz = a/np.sqrt(S2p[i]); p_up[i] = float(_st.norm.sf(zz)); p_dn[i] = float(_st.norm.cdf(zz))
        else:
            p_up[i] = mc_p(d, a, args.n_sim, rng); p_dn[i] = mc_p(-d, -a, args.n_sim, rng)
    for i in np.argsort(p_up)[:int(min(2000, n_cl))]:
        d = ds[starts[i]:starts[i]+seglen[i]]
        if len(d) <= args.k_mc_cap: p_up[i] = mc_p(d, float(d.sum()), args.n_sim_refine, rng)

    skilled = p_up < 0.05; worse = p_dn < 0.05; bh = bh_discoveries(p_up, 0.05)
    rep = {"scope": "v2 tape, ALL resolved markets, maker+taker; per-(wallet,condition) realised PnL; "
                    "sign-flip skill + split-half persistence (port of scripts/31)",
           "test_blocks": args.test or None, "n_wallets_total": int(n_total), "n_classifiable": int(n_cl),
           "classifiable_frac": n_cl/n_total if n_total else None, "min_positions": MIN,
           "z_position": {"mean": float(z_pos.mean()), "sd": float(z_pos.std()),
                          "frac_skilled_z>1.645": float((z_pos > 1.645).mean()),
                          "frac_worse_z<-1.645": float((z_pos < -1.645).mean())},
           "uncorrected": {"n_skilled": int(skilled.sum()), "frac_skilled": float(skilled.mean()),
                           "n_worse": int(worse.sum()), "frac_worse": float(worse.mean()),
                           "frac_indistinguishable": float((~skilled & ~worse).mean())},
           "fdr_bh_q0.05": {"n_certifiably_skilled": int(bh), "frac": bh/n_cl if n_cl else None}}
    if p1p2:
        from scipy.stats import spearmanr
        pp = np.concatenate(p1p2); rho, pv = spearmanr(pp[:, 0], pp[:, 1])
        qq = np.quantile(pp[:, 0], [0.2, 0.8]); top = pp[:, 0] >= qq[1]; bot = pp[:, 0] <= qq[0]
        rep["persistence"] = {"n_both_periods": int(len(pp)), "spearman_rho": float(rho), "spearman_p": float(pv),
            "p1_top_quintile_mean_p2": float(pp[top, 1].mean()), "p1_bottom_quintile_mean_p2": float(pp[bot, 1].mean())}
    else:
        rep["persistence"] = {"status": "too few wallets in both halves"}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"\nwrote {args.out}")
    print(f"classifiable {n_cl:,}/{n_total:,}; uncorrected skilled {100*rep['uncorrected']['frac_skilled']:.1f}% "
          f"worse {100*rep['uncorrected']['frac_worse']:.1f}%; BH q0.05 n={bh}; "
          f"persistence rho={rep['persistence'].get('spearman_rho')}")
    con.close()
    if not resume:
        shutil.rmtree(tmp, ignore_errors=True)   # keep signed parquet on resume runs
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
