#!/usr/bin/env python
"""Sign-randomization (permutation) skill test on the FULL v1 archive population —
maker AND taker — with a correlation-immune persistence cross-check. Matched to
Gomez-Cram et al. (2026) and reconciled with our paid-rate/calibration null.

METHOD (docs/research_framing_2026-09-05.md RQ2):
  Null: no side-selection skill => flipping the buy/sell sign of each directional bet
  leaves expected PnL unchanged.
  * Decision unit = (wallet, MARKET/condition) net realised position. d_g = sum over the
    wallet's fills in that market of q*(won-price) (q signed long/short). One market
    outcome = one decision (collapses YES/NO; coarser than token to reduce correlated
    double-counting). EXACT realised PnL.
  * Population = FULL maker+taker (each fill credits taker +q(won-price), maker the
    negative) — the direct answer to the taker-tail critique of skilled_population.json.
  * Statistic: A = sum_g d_g. Null N = sum_g eps_g d_g, eps~Rademacher, Var=sum_g d_g^2.
    z = A/sqrt(Var). p via Monte-Carlo sign flips (+ normal fallback for very high-k).
  * Classification: skilled (upper p<0.05) / worse (lower) / indistinguishable; reported
    UNCORRECTED (~Gomez-Cram) and BH/FDR-corrected (stricter).
  * RECONCILIATION diagnostics: z over-dispersion (sd>1) and SYMMETRIC two-tail excess
    reveal cross-market-correlation inflation of the sign-flip skilled-fraction (an UPPER
    bound). z_fill (per-fill variance) shows how a naive per-trade unit inflates further.
  * PERSISTENCE (split-half): does period-1 PnL predict period-2 PnL? Correlation-IMMUNE
    (no independence assumption) — the robust arbiter of real skill.

MEMORY-SAFE: partitioned by wallet-hash bucket (hash(w)%NB) so every aggregation is ~1/NB
of the population; per-fill variance folded into the single dt pass; classifiable position
arrays (~a few hundred MB) accumulate in RAM, MC runs once at the end. Launch inside
systemd-run -p MemoryMax.

  python scripts/31_skill_signflip.py --out docs/skill_signflip.json --buckets 8 --memory-limit 5GB
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                              # noqa: E402
from intellifi.archive import register_archive_views      # noqa: E402
from intellifi import config as _cfg                       # noqa: E402


def bh_discoveries(pvals: np.ndarray, q: float = 0.05) -> int:
    m = len(pvals)
    if m == 0:
        return 0
    order = np.argsort(pvals)
    passed = pvals[order] <= (np.arange(1, m + 1) / m) * q
    return int(np.max(np.nonzero(passed)[0]) + 1) if passed.any() else 0


def mc_p(d: np.ndarray, A: float, n_sim: int, rng) -> float:
    k = len(d); hits = 0; done = 0
    CH = max(1, int(2_000_000 / max(k, 1)))
    while done < n_sim:
        b = min(CH, n_sim - done)
        signs = rng.integers(0, 2, size=(b, k), dtype=np.int8) * 2 - 1
        hits += int(np.count_nonzero(signs @ d >= A - 1e-9)); done += b
    return (hits + 1) / (n_sim + 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/skill_signflip.json")
    ap.add_argument("--memory-limit", default="5GB")
    ap.add_argument("--buckets", type=int, default=8)
    ap.add_argument("--min-pos", type=int, default=10)
    ap.add_argument("--n-sim", type=int, default=2000)
    ap.add_argument("--n-sim-refine", type=int, default=200000)
    ap.add_argument("--k-mc-cap", type=int, default=2000)
    ap.add_argument("--start", default=None); ap.add_argument("--end", default=None)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    NB, MIN = args.buckets, args.min_pos

    tmp = _cfg.DATA_DIR / "_s31_tmp"; import shutil; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='70GB'")
    register_archive_views(con, start=args.start, end=args.end)

    RESOLVED = ("winning_outcome_label IS NOT NULL AND price>0 AND price<1 AND shares>0 "
                "AND taker_direction IN ('BUY','SELL')")
    WON = "(CASE WHEN outcome_label = winning_outcome_label THEN 1 ELSE 0 END)"
    PAY = f"(CASE WHEN taker_direction='BUY' THEN ({WON}-price)*shares ELSE (price-{WON})*shares END)"
    UNION = (f"SELECT taker AS w, condition_id AS grp, block_timestamp AS bt, {PAY} AS pay FROM arc_raw WHERE {RESOLVED} "
             f"UNION ALL SELECT maker, condition_id, block_timestamp, -({PAY}) FROM arc_raw WHERE {RESOLVED} AND maker IS NOT NULL")
    split_ts = con.sql(f"SELECT approx_quantile(bt,0.5) FROM ({UNION}) t").fetchone()[0]  # bounded memory

    # accumulators
    ids_all, d_all, seg_len = [], [], []           # ragged (wallet, positions)
    A_all, S2p_all, k_all = [], [], []
    zf_hit = zf_tot = 0; zf_sum = 0.0; n_total = 0
    p1p2 = []                                        # persistence pairs
    t0 = time.time()
    for b in range(NB):
        BF = f"(hash(w) % {NB}) = {b}"
        # ONE pass -> (w,grp): d, per-fill sum-of-squares (ss), fill count (cf)
        con.execute(f"""CREATE OR REPLACE TABLE dt AS
            SELECT w, grp, SUM(pay) d, SUM(pay*pay) ss, COUNT(*) cf
            FROM ({UNION}) t WHERE {BF} GROUP BY w, grp""")
        con.execute("""CREATE OR REPLACE TABLE ws AS
            SELECT w, SUM(d) A, SUM(d*d) S2_pos, COUNT(*) k_pos, SUM(ss) S2_fill, SUM(cf) k_fill
            FROM dt GROUP BY w""")
        n_total += con.sql("SELECT count(*) FROM ws").fetchone()[0]
        zf = con.sql(f"""SELECT count(*) FILTER(WHERE A/sqrt(S2_fill)>1.645),
                                count(*), sum(A/sqrt(S2_fill))
                         FROM ws WHERE k_pos>={MIN} AND S2_pos>0 AND S2_fill>0""").fetchone()
        zf_hit += int(zf[0] or 0); zf_tot += int(zf[1] or 0); zf_sum += float(zf[2] or 0)
        # classifiable arrays for this bucket
        arr = con.sql(f"""SELECT d.w, d.d FROM dt d JOIN ws s ON s.w=d.w
            WHERE s.k_pos>={MIN} AND s.S2_pos>0 ORDER BY d.w, d.grp""").df()
        if len(arr):
            ws_ = arr["w"].to_numpy(); ds_ = arr["d"].to_numpy().astype(np.float64)
            bnd = np.flatnonzero(np.r_[True, ws_[1:] != ws_[:-1], True]); st = bnd[:-1]
            ids_all.append(ws_[st]); d_all.append(ds_); seg_len.append(np.diff(bnd))
            A_all.append(np.add.reduceat(ds_, st)); S2p_all.append(np.add.reduceat(ds_ * ds_, st))
            k_all.append(np.diff(bnd))
        # persistence for this bucket
        pr = con.sql(f"""
            WITH pp AS (SELECT w, CASE WHEN bt < {split_ts} THEN 1 ELSE 2 END period, grp, pay FROM ({UNION}) t WHERE {BF}),
                 pw AS (SELECT w, period, SUM(pay) pnl, COUNT(DISTINCT grp) k FROM pp GROUP BY w, period)
            SELECT a.pnl p1, b2.pnl p2 FROM pw a JOIN pw b2 ON a.w=b2.w
            WHERE a.period=1 AND b2.period=2 AND a.k>={MIN} AND b2.k>={MIN}""").df()
        if len(pr):
            p1p2.append(pr[["p1", "p2"]].to_numpy())
        print(f"  bucket {b+1}/{NB}  wallets_so_far={n_total:,}  ({time.time()-t0:.0f}s)", flush=True)

    # combine
    ids = np.concatenate(ids_all); ds = np.concatenate(d_all); seglen = np.concatenate(seg_len)
    A = np.concatenate(A_all); S2p = np.concatenate(S2p_all); k = np.concatenate(k_all)
    starts = np.r_[0, np.cumsum(seglen)[:-1]]
    n_cl = len(ids)
    with np.errstate(invalid="ignore", divide="ignore"):
        z_pos = np.nan_to_num(A / np.sqrt(S2p), nan=0.0, posinf=0.0, neginf=0.0)

    rep: dict = {"scope": "whole v1 archive, maker+taker; realised gross per-(wallet,market) PnL; "
                          "sign-randomization skill test + split-half persistence",
                 "window": {"start": args.start, "end": args.end}, "buckets": NB,
                 "n_wallets_total": int(n_total), "n_classifiable": int(n_cl),
                 "classifiable_frac_of_all": n_cl / n_total if n_total else None,
                 "min_positions_for_classification": MIN,
                 "z_position": {"mean": float(z_pos.mean()), "sd": float(z_pos.std()),
                                "frac_skilled_nominal_z>1.645": float((z_pos > 1.645).mean()),
                                "frac_worse_z<-1.645": float((z_pos < -1.645).mean()),
                                "note": "null: z~mean0,sd1, 5% each tail. SYMMETRIC two-tail excess + sd>1 = "
                                        "cross-market-correlation inflation => the skilled-fraction is an UPPER bound."},
                 "z_fill": {"mean": (zf_sum / zf_tot) if zf_tot else None,
                            "frac_skilled_nominal_z>1.645": (zf_hit / zf_tot) if zf_tot else None,
                            "note": "per-fill unit inflates z further (repeated correct calls counted independent)."}}

    # MC sign-flip p (position unit)
    print(f"MC sign-flip on {n_cl:,} classifiable wallets ...", flush=True)
    from scipy import stats as _st
    p_up = np.empty(n_cl); p_dn = np.empty(n_cl); t1 = time.time()
    for i in range(n_cl):
        d = ds[starts[i]:starts[i] + seglen[i]]; a = float(A[i])
        if k[i] > args.k_mc_cap:
            zz = a / np.sqrt(S2p[i]); p_up[i] = float(_st.norm.sf(zz)); p_dn[i] = float(_st.norm.cdf(zz))
        else:
            p_up[i] = mc_p(d, a, args.n_sim, rng); p_dn[i] = mc_p(-d, -a, args.n_sim, rng)
        if i % 100000 == 0:
            print(f"  {i:,}/{n_cl:,} ({time.time()-t1:.0f}s)", flush=True)
    # refine top upper-tail candidates for BH accuracy
    for i in np.argsort(p_up)[:int(min(2000, n_cl))]:
        d = ds[starts[i]:starts[i] + seglen[i]]
        if len(d) <= args.k_mc_cap:
            p_up[i] = mc_p(d, float(d.sum()), args.n_sim_refine, rng)

    skilled = p_up < 0.05; worse = p_dn < 0.05
    rep["uncorrected"] = {"n_skilled": int(skilled.sum()), "frac_skilled": float(skilled.mean()),
                          "n_worse_than_chance": int(worse.sum()), "frac_worse": float(worse.mean()),
                          "frac_indistinguishable": float((~skilled & ~worse).mean()),
                          "vs_gomezcram": "their uncorrected ~3.1% skilled / ~6% worse / ~91% indistinguishable"}
    bh = bh_discoveries(p_up, 0.05)
    rep["fdr_bh_q0.05"] = {"n_certifiably_skilled": int(bh), "frac": bh / n_cl if n_cl else None,
                           "note": "BH on the upper-tail sign-flip p; the correlation caveat still applies (upper bound)."}
    topo = np.argsort(p_up)[:20]
    rep["top_candidates"] = [{"wallet": str(ids[i]), "A_pnl": float(A[i]), "k_pos": int(k[i]),
                              "z_pos": float(z_pos[i]), "p_up": float(p_up[i])} for i in topo]

    # persistence
    if p1p2:
        from scipy.stats import spearmanr
        pp = np.concatenate(p1p2); p1 = pp[:, 0]; p2 = pp[:, 1]
        rho, pv = spearmanr(p1, p2)
        qq = np.quantile(p1, [0.2, 0.8]); topm = p1 >= qq[1]; botm = p1 <= qq[0]
        rep["persistence"] = {"n_wallets_both_periods": int(len(pp)), "split_ts_epoch": float(split_ts),
            "spearman_rho_p1_p2": float(rho), "spearman_p": float(pv),
            "p1_top_quintile_mean_p2_pnl": float(p2[topm].mean()), "p1_top_quintile_frac_p2_pos": float((p2[topm] > 0).mean()),
            "p1_bottom_quintile_mean_p2_pnl": float(p2[botm].mean()), "p1_bottom_quintile_frac_p2_pos": float((p2[botm] > 0).mean()),
            "note": "correlation-IMMUNE: positive rho / top-quintile out-performance => persistent (weak) skill; ~0 => luck."}
    else:
        rep["persistence"] = {"status": "too few wallets in both halves"}

    rep["caveats"] = [
        "Realised, resolution-based PnL — outcome-dependent (survivorship); tests SIDE-SELECTION skill only.",
        "Sign-flip cross-market correlation inflates the skilled-fraction (SYMMETRIC two-tail excess + z sd>1 "
        "are the tell) -> read it as an UPPER bound; the persistence rho is the correlation-immune signal.",
        "Full maker+taker; zero-sum before fees; v1 ~fee-free. Partitioned by wallet-hash (memory-safe).",
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    zp = rep["z_position"]; u = rep["uncorrected"]; pe = rep["persistence"]
    print(f"classifiable {n_cl:,}/{n_total:,} ({100*rep['classifiable_frac_of_all']:.1f}%)")
    print(f"z_position mean={zp['mean']:+.3f} sd={zp['sd']:.3f} skilled(z>1.645)={100*zp['frac_skilled_nominal_z>1.645']:.2f}% worse={100*zp['frac_worse_z<-1.645']:.2f}%")
    print(f"UNCORRECTED skilled={u['n_skilled']:,} ({100*u['frac_skilled']:.2f}%) worse={100*u['frac_worse']:.2f}% indist={100*u['frac_indistinguishable']:.2f}% [G-C ~3.1/~6/~91%]")
    print(f"BH FDR q=0.05 certifiably skilled = {rep['fdr_bh_q0.05']['n_certifiably_skilled']:,}")
    if "spearman_rho_p1_p2" in pe:
        print(f"PERSISTENCE n={pe['n_wallets_both_periods']:,} Spearman rho={pe['spearman_rho_p1_p2']:+.3f} (p={pe['spearman_p']:.1e}); "
              f"p1-top-quintile p2 mean={pe['p1_top_quintile_mean_p2_pnl']:+,.0f} vs bottom={pe['p1_bottom_quintile_mean_p2_pnl']:+,.0f}")
    con.close(); shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
