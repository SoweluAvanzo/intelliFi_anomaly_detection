#!/usr/bin/env python
"""Stage C — insider-timing event study on late-resolving ("jump") markets.

Stage B (scripts/25) showed most markets price the winner early, but a tail
resolves in a sharp jump at an event (e.g. "US strikes Iran": winner 0.06 at 24h
-> 1.00 at 1h). This script inspects those jumps for the insider-timing
signature: reconstruct the winner-outcome price path, locate the jump, and ask
whether the price DRIFTED UP over the hours BEFORE the jump (informed
accumulation) or moved instantaneously (news-driven / efficient). Then it names
the wallets that positioned on the winning side in the pre-jump window at cheap
prices — the informed-trading candidates for investigative triage.

This is triage, NOT proof: pre-jump drift is "consistent with" informed trading;
distinguishing a leak from public-info incorporation needs a news timeline
(Stage D). Scheduled-macro markets (Fed/FOMC) act as the low-insider control:
they converge gradually with no jump, so they should surface no pre-jump
positioners of note.

Auto-selects targets = markets whose winner price is still < --late-threshold at
24h before close (the jump/event-driven tail). Source-agnostic; use
INTELLIFI_SOURCE=archive.

  INTELLIFI_SOURCE=archive INTELLIFI_ARCHIVE_CIDS=corpus.txt \
      python scripts/26_event_study.py --out docs/event_study.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from intellifi.warehouse import open_warehouse            # noqa: E402
from intellifi.categories import register_market_categories  # noqa: E402
from intellifi import config as _cfg                       # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/event_study.json")
    ap.add_argument("--late-threshold", type=float, default=0.7,
                    help="winner price at 24h below this => a jump/event-driven target")
    ap.add_argument("--pre-jump-hours", type=float, default=48.0,
                    help="pre-jump window length for identifying early positioners")
    ap.add_argument("--jump-cross", type=float, default=0.5,
                    help="winner price level whose first crossing marks the jump")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--memory-limit", default="8GB")
    args = ap.parse_args()
    import polars as pl

    con = open_warehouse(":memory:")
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute("SET preserve_insertion_order=false")
    _tmp = _cfg.DATA_DIR / "_s26_tmp"
    _tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{_tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='40GB'")
    register_market_categories(con)

    # Hourly winner-outcome price path over the last 30 days before close.
    path = con.sql("""
        WITH px AS (
            SELECT condition_id, outcome_index, date_trunc('hour', ts_utc) AS ts,
                   SUM(price*size)/NULLIF(SUM(size),0) AS price
            FROM trades WHERE price>0 AND price<1 AND size>0 GROUP BY 1,2,3
        )
        SELECT px.condition_id, c.category, c.slug, px.ts, px.price AS winner_price,
               DATE_DIFF('second', px.ts, m.closed_time)/3600.0 AS h2c
        FROM px
        JOIN winning_outcomes w ON w.condition_id=px.condition_id AND px.outcome_index=w.winning_outcome_index
        JOIN markets m ON m.condition_id=px.condition_id
        JOIN mktcat c ON c.condition_id=px.condition_id
        WHERE m.closed_time IS NOT NULL AND px.ts < m.closed_time
          AND px.ts >= m.closed_time - INTERVAL 720 HOUR
        ORDER BY px.condition_id, px.ts
    """).pl()
    if path.is_empty():
        print("no price paths", file=sys.stderr); return 2

    # Per market: winner price at ~24h, jump time (first hour crossing --jump-cross),
    # and the pre-jump drift shape.
    targets = []
    for (cid,), g in path.group_by(["condition_id"]):
        g = g.sort("ts")
        h2c = g["h2c"].to_numpy(); wprice = g["winner_price"].to_numpy()
        ts = g["ts"].to_list()
        # winner price at the observation closest to 24h before close
        p24 = float(wprice[np.argmin(np.abs(h2c - 24))]) if len(wprice) else None
        if p24 is None or p24 >= args.late_threshold:
            continue  # not a late/jump market
        # jump = the FINAL surge: the first hour at/after the last time the winner
        # was still doubted (< jump_cross). Robust to early transient crossings in
        # oscillating markets (e.g. a market that blips up, falls back, then surges).
        below = np.where(wprice < args.jump_cross)[0]
        if len(below) == 0:
            jump_i = 0  # winner never doubted within the 30d window
        else:
            jump_i = min(int(below[-1]) + 1, len(wprice) - 1)
        cat = g["category"][0]; slug = g["slug"][0]
        rec = {"condition_id": cid, "category": cat, "slug": slug,
               "winner_price_24h": round(p24, 4),
               "winner_price_start": round(float(wprice[0]), 4),
               "path_hours": int(len(wprice))}
        if jump_i is not None:
            jt = ts[jump_i]
            # drift shape: how much of the rise happened in the hours BEFORE the crossing.
            # look at the 12h and 3h windows before the crossing hour.
            def price_at_h_before(hours):
                tgt = jt.timestamp() - hours*3600
                idx = np.argmin(np.abs(np.array([t.timestamp() for t in ts]) - tgt))
                return float(wprice[idx])
            rec.update({
                "jump_ts": jt.isoformat(),
                "jump_hours_before_close": round(float(h2c[jump_i]), 2),
                "winner_price_12h_before_jump": round(price_at_h_before(12), 4),
                "winner_price_3h_before_jump": round(price_at_h_before(3), 4),
                "winner_price_1h_before_jump": round(price_at_h_before(1), 4),
            })
        targets.append(rec)

    rep: dict = {"source": os.getenv("INTELLIFI_SOURCE", "parquet"),
                 "late_threshold": args.late_threshold, "pre_jump_hours": args.pre_jump_hours,
                 "n_target_markets": len(targets), "targets": targets}

    # For markets with a detected jump, find the pre-jump winning-side positioners.
    jumped = [t for t in targets if "jump_ts" in t]
    if jumped:
        tg = pl.DataFrame([{"condition_id": t["condition_id"], "jump_ts": t["jump_ts"]} for t in jumped])
        con.register("tg_df", tg.to_arrow())
        con.execute(f"""CREATE TEMP TABLE tgt AS
            SELECT condition_id, jump_ts::TIMESTAMPTZ AS jump_ts,
                   jump_ts::TIMESTAMPTZ - ({args.pre_jump_hours} * INTERVAL 1 HOUR) AS pre_ts
            FROM tg_df""")
        # Winning-side positioning on a consistent YES-equivalent scale: a BUY of
        # the winning outcome enters at `price`; a SELL of the losing outcome is
        # the same directional bet, entering at `1 - price`. Rank by shares held.
        pos = con.sql("""
            WITH f AS (
                SELECT t.condition_id, t.proxy_wallet, t.size,
                       ((t.side='BUY'  AND t.outcome_index =  w.winning_outcome_index)
                     OR (t.side='SELL' AND t.outcome_index <> w.winning_outcome_index)) AS winning_side,
                       CASE WHEN t.side='BUY' THEN t.price ELSE 1.0 - t.price END AS yes_equiv_price
                FROM trades t
                JOIN winning_outcomes w ON w.condition_id = t.condition_id
                JOIN tgt g ON g.condition_id = t.condition_id
                WHERE t.ts_utc >= g.pre_ts AND t.ts_utc < g.jump_ts
                  AND t.price>0 AND t.price<1 AND t.size>0
            )
            SELECT condition_id, proxy_wallet,
                   SUM(CASE WHEN winning_side THEN size ELSE 0 END) AS winner_side_shares,
                   SUM(CASE WHEN winning_side THEN yes_equiv_price*size END)
                     / NULLIF(SUM(CASE WHEN winning_side THEN size END),0) AS avg_entry_yes_equiv,
                   COUNT(*) AS n_fills
            FROM f GROUP BY 1,2
            HAVING SUM(CASE WHEN winning_side THEN size ELSE 0 END) > 0
        """).pl()
        by_market = {}
        for r in pos.to_dicts():
            by_market.setdefault(r["condition_id"], []).append(r)
        for t in jumped:
            rows = sorted(by_market.get(t["condition_id"], []),
                          key=lambda r: -r["winner_side_shares"])[:args.top_k]
            t["pre_jump_winner_side_positioners"] = [{
                "wallet": r["proxy_wallet"],
                "winner_side_shares": round(float(r["winner_side_shares"]), 1),
                "avg_entry_price": round(float(r["avg_entry_yes_equiv"]), 4) if r["avg_entry_yes_equiv"] else None,
                "position_cost_usdc": round(float(r["winner_side_shares"]) * float(r["avg_entry_yes_equiv"]), 2)
                    if r["avg_entry_yes_equiv"] else None,
                "implied_profit_if_win": round(float(r["winner_side_shares"]) * (1.0 - float(r["avg_entry_yes_equiv"])), 2)
                    if r["avg_entry_yes_equiv"] else None,
                "n_fills": int(r["n_fills"]),
            } for r in rows]
            t["n_pre_jump_positioners"] = len(by_market.get(t["condition_id"], []))

    rep["notes"] = [
        "TARGET = winner price < late_threshold at 24h before close (event/jump-driven tail).",
        "Pre-jump positioners = takers with net winning-SIDE notional in the [jump - pre_jump_hours, jump) window "
        "at cheap prices; ranked by that notional. These are informed-trading CANDIDATES, not proof.",
        "Read the drift shape: winner_price_12h/3h/1h_before_jump rising steadily => gradual accumulation "
        "(inspect for leak); flat then instantaneous => news-driven (efficient). Needs a news timeline (Stage D) to attribute.",
        "avg_entry_price is the size-weighted winning-side entry in the pre-jump window; implied_profit_if_win "
        "= notional*(1/avg_entry_price - 1) (they did win, since it's the winning side).",
    ]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}  (source={rep['source']}, {len(targets)} jump/event targets, {len(jumped)} with a detected jump)")
    for t in targets:
        head = f"  [{t['category']}] {str(t['slug'])[:46]:46s} p24={t['winner_price_24h']:.2f}"
        if "jump_ts" in t:
            head += (f" jump@{t['jump_hours_before_close']:.0f}h  "
                     f"12h_before={t['winner_price_12h_before_jump']:.2f} 3h={t['winner_price_3h_before_jump']:.2f}")
            pp = t.get("pre_jump_winner_side_positioners", [])
            if pp:
                head += (f"  | top early: {pp[0]['winner_side_shares']:,.0f} sh @ {pp[0]['avg_entry_price']}"
                         f" -> +{pp[0]['implied_profit_if_win']:,.0f} if win")
        print(head)
    con.close()
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
