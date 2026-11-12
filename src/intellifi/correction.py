"""RQ2 price-correction attribution + analysis on negRisk families.

Reconstructs each family's running price-sum S = Σ(YES last prices); a taker trade is *corrective*
if it moves |S-1| toward 0. Credits the aggressor; a mispricing *episode* = |S-1| crossing HIGH then
converging below LOW. Canonical trades = `is_taker_order=TRUE` rows, aggressor = `maker` field
(the `taker` field is the exchange operator). See `intellifi.negrisk` and `docs/FEE_EFFECTS.md`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HIGH, LOW, MIN_CAND, STALE = 0.05, 0.02, 3, 48 * 3600


def build_canonical(con, fills_path: str) -> int:
    """Create table C: canonical taker trades with int codes (fid,tid,wid). Returns row count."""
    con.execute(f"""CREATE OR REPLACE TABLE C AS
      SELECT family, tok, wallet, is_buy, ts, block_number, evt_index, usdc, shares, fee, price, yes_won,
             dense_rank() OVER (ORDER BY family)-1 fid,
             dense_rank() OVER (ORDER BY tok)-1 tid,
             dense_rank() OVER (ORDER BY wallet)-1 wid
      FROM (
        SELECT family, yes_token_id tok, maker wallet, (side='BUY') is_buy, epoch(ts_utc) ts,
               block_number, evt_index, usdc, shares, fee_raw/1e6 fee, price, yes_won, is_taker_order
        FROM '{fills_path}'
        QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index ORDER BY block_number)=1
      ) t
      WHERE price>0 AND price<1 AND is_taker_order=TRUE""")
    return con.execute("SELECT count(*) FROM C").fetchone()[0]


def build_canonical_v1(con, fills_path: str) -> int:
    """Create table C from the v1 archive extract. Aggregates maker legs to one taker-trade per
    (family,token,wallet,second,side); shares = usdc/price; causal order = (ts, synthetic evt_index).
    Spill-efficient: string keys are coded via dimension-table joins (no dense_rank sort over long
    strings); the only sort is the evt_index window on compact int codes."""
    con.execute(f"""CREATE OR REPLACE TABLE _agg AS
      SELECT family, tok, wallet, is_buy, ts, any_value(yes_won) yes_won,
             sum(usdc) usdc, sum(fee) fee, sum(usdc)/nullif(sum(usdc/price),0) price
      FROM '{fills_path}' WHERE price>0 AND price<1
      GROUP BY family, tok, wallet, is_buy, ts""")
    con.execute("CREATE OR REPLACE TABLE _dfam AS SELECT family, row_number() OVER ()-1 fid FROM (SELECT DISTINCT family FROM _agg)")
    con.execute("CREATE OR REPLACE TABLE _dtok AS SELECT tok, row_number() OVER ()-1 tid FROM (SELECT DISTINCT tok FROM _agg)")
    con.execute("CREATE OR REPLACE TABLE _dwal AS SELECT wallet, row_number() OVER ()-1 wid FROM (SELECT DISTINCT wallet FROM _agg)")
    con.execute("""CREATE OR REPLACE TABLE C AS
      SELECT *, row_number() OVER (PARTITION BY fid, ts ORDER BY tid, wid) AS evt_index
      FROM (
        SELECT a.family, a.tok, a.wallet, a.is_buy, a.ts, a.ts AS block_number,
               a.usdc, a.usdc/a.price AS shares, a.fee, a.price, a.yes_won,
               f.fid, t.tid, w.wid
        FROM _agg a JOIN _dfam f USING(family) JOIN _dtok t USING(tok) JOIN _dwal w USING(wallet)
        WHERE a.price>0 AND a.price<1
      )""")
    for d in ("_agg", "_dfam", "_dtok", "_dwal"):
        con.execute(f"DROP TABLE {d}")
    return con.execute("SELECT count(*) FROM C").fetchone()[0]


def _run_loop(fid, tid, wid, ts, price, ncand, high, low, min_cand, stale):
    corr_mag, anti_mag, n_corr, n_anti, ep_wins, ep_dev = {}, {}, {}, {}, {}, {}
    ev_fam, ev_start, ev_peak, ev_ncorr, ev_top = [], [], [], [], []

    def add(d, k, v):
        d[k] = d.get(k, 0) + v

    N = len(fid)
    i = 0
    while i < N:
        f = fid[i]
        j = i
        while j < N and fid[j] == f:
            j += 1
        nc = ncand[int(f)]
        if nc >= min_cand:
            last, lts = {}, {}
            in_ep = False
            peak = 0.0
            start = 0
            corr_ep = {}
            for k in range(i, j):
                t = int(tid[k]); now = int(ts[k]); w = int(wid[k]); p = float(price[k])
                full_before = len(last) == nc
                Sb = sum(last.values()) if (full_before and all(now - lts[x] <= stale for x in lts)) else None
                last[t] = p; lts[t] = now
                if len(last) < nc:
                    continue
                Sa = sum(last.values()) if all(now - lts[x] <= stale for x in lts) else None
                if Sb is None or Sa is None:
                    if Sa is not None and not in_ep and abs(Sa - 1) > high:
                        in_ep = True; peak = abs(Sa - 1); start = now; corr_ep = {}
                    continue
                db = abs(Sb - 1); da = abs(Sa - 1); mag = db - da
                if mag > 0:
                    add(corr_mag, w, mag); add(n_corr, w, 1)
                elif mag < 0:
                    add(anti_mag, w, -mag); add(n_anti, w, 1)
                if not in_ep and da > high:
                    in_ep = True; peak = da; start = now; corr_ep = {}
                if in_ep:
                    if db > peak: peak = db
                    if da > peak: peak = da
                    if mag > 0: add(corr_ep, w, mag)
                    if da < low:
                        top = max(corr_ep, key=corr_ep.get) if corr_ep else -1
                        if top >= 0:
                            add(ep_wins, top, 1); add(ep_dev, top, peak)
                        ev_fam.append(int(f)); ev_start.append(start); ev_peak.append(peak)
                        ev_ncorr.append(len(corr_ep)); ev_top.append(top)
                        in_ep = False
        i = j
    return (corr_mag, anti_mag, n_corr, n_anti, ep_wins, ep_dev,
            ev_fam, ev_start, ev_peak, ev_ncorr, ev_top)


def attribute(con, out_prefix: str, high=HIGH, low=LOW, min_cand=MIN_CAND, stale=STALE) -> dict:
    """Run attribution over table C (built by build_canonical for v2 or build_canonical_v1 for v1).
    Writes <prefix>_{wallets,events}.parquet. Thresholds are design choices, not proven-optimal:
    HIGH/LOW bound an episode, MIN_CAND requires a complete-enough basket, STALE caps carry-forward."""
    ncand = dict(con.execute("SELECT fid, count(DISTINCT tid) FROM C GROUP BY fid").fetchall())
    con.execute("""CREATE OR REPLACE TABLE AGG AS
      SELECT wid, any_value(wallet) wallet, sum(usdc) vol, sum(fee) fee_paid, count(*) n_trades,
             sum(CASE WHEN is_buy THEN -usdc ELSE usdc END)
               + sum(CASE WHEN is_buy THEN shares ELSE -shares END * yes_won) pnl
      FROM C GROUP BY wid""")
    a = con.execute("SELECT fid,tid,wid,ts,price FROM C ORDER BY fid, block_number, evt_index").fetchnumpy()
    out = _run_loop(a["fid"].astype(np.int64), a["tid"], a["wid"], a["ts"].astype(np.int64),
                    a["price"].astype(np.float64), ncand, high, low, min_cand, stale)
    (corr_mag, anti_mag, n_corr, n_anti, ep_wins, ep_dev, ev_fam, ev_start, ev_peak, ev_ncorr, ev_top) = out

    wids = sorted(set(corr_mag) | set(anti_mag) | set(ep_wins))
    W = pd.DataFrame({"wid": wids,
                      "corr_mag": [corr_mag.get(w, 0) for w in wids], "anti_mag": [anti_mag.get(w, 0) for w in wids],
                      "n_corr": [n_corr.get(w, 0) for w in wids], "n_anti": [n_anti.get(w, 0) for w in wids],
                      "ep_wins": [ep_wins.get(w, 0) for w in wids], "ep_dev_closed": [ep_dev.get(w, 0) for w in wids]})
    W["corr_net"] = W.corr_mag - W.anti_mag
    agg = con.execute("SELECT * FROM AGG").df()
    W = W.merge(agg, on="wid", how="right").fillna(0)
    ev = pd.DataFrame({"fid": ev_fam, "start": ev_start, "peak_dev": ev_peak,
                       "n_correctors": ev_ncorr, "top_wid": ev_top})
    ev = ev.merge(agg[["wid", "wallet"]].rename(columns={"wid": "top_wid", "wallet": "top"}),
                  on="top_wid", how="left")
    W.to_parquet(f"{out_prefix}_wallets.parquet", index=False)
    ev.to_parquet(f"{out_prefix}_events.parquet", index=False)
    return {"trades": int(len(a["fid"])), "episodes": int(len(ev)), "wallets": int(len(W)),
            "families_with_episode": int(ev.fid.nunique()) if len(ev) else 0}


def _gini(x):
    x = np.sort(np.asarray(x, float)); x = x[x >= 0]; n = len(x)
    if n == 0 or x.sum() == 0:
        return float("nan")
    return (2 * np.sum(np.arange(1, n + 1) * x) / (n * x.sum())) - (n + 1) / n


def analyze(out_prefix: str) -> dict:
    """Full RQ2 analysis from the attribution outputs: concentration, distinctness from
    volume/profit, OOS persistence, profitability net of fees, and the volume stress-test."""
    from scipy.stats import spearmanr
    W = pd.read_parquet(f"{out_prefix}_wallets.parquet").fillna(0)
    ev = pd.read_parquet(f"{out_prefix}_events.parquet").dropna(subset=["top_wid"]).copy()
    ev["top_wid"] = ev.top_wid.astype(int)
    R = {}

    s = W.ep_wins.clip(lower=0); tot = s.sum()
    R["concentration"] = {"n_correctors": int((s > 0).sum()), "gini": round(_gini(s), 3),
                          "top10_pct": round(100 * s.sort_values(ascending=False).head(10).sum() / tot, 1),
                          "top100_pct": round(100 * s.sort_values(ascending=False).head(100).sum() / tot, 1)}

    def overlap(a, b, k=100):
        A = set(W.sort_values(a, ascending=False).head(k).wallet)
        B = set(W.sort_values(b, ascending=False).head(k).wallet)
        return round(len(A & B) / k, 2)
    R["distinctness"] = {m: {"spearman_ep_wins": round(spearmanr(W.ep_wins, W[m]).correlation, 3),
                             "top100_overlap": overlap("ep_wins", m)}
                         for m in ["vol", "pnl", "fee_paid", "n_trades"]}

    C = W[W.ep_wins > 0].copy(); C["net"] = C.pnl - C.fee_paid
    vol = C.vol.sum()
    span_days = float((ev.start.max() - ev.start.min()) / 86400) if len(ev) else float("nan")
    R["profitability"] = {"correctors_gross_pnl": round(C.pnl.sum()), "correctors_fees": round(C.fee_paid.sum()),
                          "correctors_net": round(C.net.sum()), "frac_net_profitable": round((C.net > 0).mean(), 2),
                          "correctors_vol": round(vol), "span_days": round(span_days),
                          "gross_margin_bps": round(1e4 * C.pnl.sum() / vol, 1),
                          "fee_drag_bps": round(1e4 * C.fee_paid.sum() / vol, 1),
                          "net_margin_bps": round(1e4 * C.net.sum() / vol, 1),
                          "all_takers_gross_pnl": round(W.pnl.sum()), "all_takers_net": round(W.pnl.sum() - W.fee_paid.sum())}

    nf = ev.groupby("top_wid").fid.nunique(); nw = ev.groupby("top_wid").size()
    top50 = nw.sort_values(ascending=False).head(50).index
    R["generalism"] = {"top50_median_families": int(nf.loc[top50].median()),
                       "correctors_in_ge5_families": int((nf >= 5).sum())}

    tmid = ev.start.median()
    h1 = ev[ev.start < tmid].groupby("top_wid").size().rename("w1")
    h2 = ev[ev.start >= tmid].groupby("top_wid").size().rename("w2")
    P = pd.concat([h1, h2], axis=1).fillna(0); both = P[(P.w1 > 0) & (P.w2 > 0)]
    fam_both = set(ev[ev.start < tmid].fid) & set(ev[ev.start >= tmid].fid)
    evb = ev[ev.fid.isin(fam_both)]
    b1 = evb[evb.start < tmid].groupby("top_wid").size(); b2 = evb[evb.start >= tmid].groupby("top_wid").size()
    Pb = pd.concat([b1.rename("w1"), b2.rename("w2")], axis=1).fillna(0); bb = Pb[(Pb.w1 > 0) & (Pb.w2 > 0)]
    R["persistence"] = {"spearman_h1_h2": round(spearmanr(both.w1, both.w2).correlation, 3),
                        "spearman_within_recurring_families": round(spearmanr(bb.w1, bb.w2).correlation, 3) if len(bb) > 2 else None,
                        "n_both_halves": int(len(both))}

    volset = set(W.sort_values("vol", ascending=False).head(100).wallet)
    R["stress"] = {"episodes_closed_by_top100_volume_pct": round(100 * ev[ev.top.isin(volset)].shape[0] / len(ev), 1),
                   "distinct_closers": int(ev.top.nunique()),
                   "distinct_closers_pct_of_wallets": round(100 * ev.top.nunique() / len(W), 1)}
    return R

