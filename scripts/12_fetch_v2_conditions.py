"""Stage II, Sample B: on-chain condition registry for the v2 period.

Fetches ConditionPreparation and ConditionResolution events of the shared
Conditional Tokens contract from the v2 genesis block onward (Etherscan V2
getLogs, bisected), derives both outcome-token ids per condition (USDC.e
collateral for standard markets, wrapped collateral for negRisk — the v2
exchanges' constructor args confirm the same collateral pair as v1) and
writes data/parquet/ctf_v2_conditions.parquet. This is the ground truth the
Sample B analyses use for winners, resolution times and token → market mapping.

    python scripts/12_fetch_v2_conditions.py --from-block 86126978 --api-key-env ETHERSCAN_KEY2
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import polars as pl
from eth_hash.auto import keccak

from intellifi import config
from intellifi.ctf import position_id, USDC_E, WRAPPED_COLLATERAL
from intellifi.fills import fetch_logs_bisect, latest_block
from intellifi.onchain import Polygonscan, POLYMARKET_CTF, POLYMARKET_NEGRISK_ADAPTER
from intellifi.resolutions import CONDITION_RESOLUTION_TOPIC, decode_resolution

CONDITION_PREPARATION_TOPIC = "0x" + keccak(b"ConditionPreparation(bytes32,address,bytes32,uint256)").hex()
OUT = config.PARQUET_DIR / "ctf_v2_conditions.parquet"


def decode_preparation(log: dict) -> dict:
    t = log["topics"]
    return {"condition_id": t[1].lower(), "oracle": ("0x" + t[2][-40:]).lower(), "question_id": t[3],
            "outcome_slot_count": int(log["data"][2:66], 16),
            "prepared_block": int(log["blockNumber"], 16),
            "prepared_ts_utc": datetime.fromtimestamp(int(log["timeStamp"], 16), tz=timezone.utc)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-block", type=int, default=86_126_978)   # 2026-04-28 11:00 UTC
    ap.add_argument("--to-block", default="latest")
    ap.add_argument("--api-key-env", default=None)
    ap.add_argument("--min-interval", type=float, default=0.5)
    args = ap.parse_args()
    key = os.getenv(args.api_key_env, "") if args.api_key_env else (config.ETHERSCAN_API_KEY or "")
    c = Polygonscan(api_key=key, min_interval_s=args.min_interval, max_calls=60_000, max_retries=12)
    to_block = latest_block(c) if args.to_block == "latest" else int(args.to_block)
    print(f"registry: blocks {args.from_block} -> {to_block}")
    prep = [decode_preparation(l) for l in fetch_logs_bisect(c, POLYMARKET_CTF, 0, CONDITION_PREPARATION_TOPIC, args.from_block, to_block)]
    print(f"  ConditionPreparation: {len(prep):,} (calls {c.calls_made})", flush=True)
    p = pl.DataFrame(prep).unique(subset=["condition_id"], keep="first") if prep else pl.DataFrame()
    del prep  # 2 M dicts ~ GBs; free before the second fetch (OOM-killed 2026-08-31 in a 4G scope)
    res = [decode_resolution(l) for l in fetch_logs_bisect(c, POLYMARKET_CTF, 0, CONDITION_RESOLUTION_TOPIC, args.from_block, to_block)]
    print(f"  ConditionResolution: {len(res):,} (calls {c.calls_made})", flush=True)
    r = (pl.DataFrame(res).with_columns(pl.col("condition_id").str.to_lowercase())
           .select("condition_id", "resolved_block", "resolved_ts_utc", "payout_numerators", "winning_outcome_index")
           .unique(subset=["condition_id"], keep="last")) if res else pl.DataFrame()
    df = p.join(r, on="condition_id", how="left") if r.height else p
    neg = pl.col("oracle") == POLYMARKET_NEGRISK_ADAPTER
    df = df.with_columns(neg.alias("neg_risk"))
    tok0, tok1 = [], []
    for cid, n, isneg in zip(df["condition_id"], df["outcome_slot_count"], df["neg_risk"]):
        coll = WRAPPED_COLLATERAL if isneg else USDC_E
        tok0.append(str(position_id(coll, cid, 1)) if n == 2 else None)
        tok1.append(str(position_id(coll, cid, 2)) if n == 2 else None)
    df = df.with_columns(pl.Series("token0", tok0), pl.Series("token1", tok1))
    df.write_parquet(OUT, compression="zstd")
    print(f"wrote {OUT}: {df.height:,} conditions, {df['resolved_ts_utc'].is_not_null().sum():,} resolved, negRisk {int(df['neg_risk'].sum()):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
