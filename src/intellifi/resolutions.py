"""On-chain resolution ground truth from the Conditional Tokens contract.

``ConditionResolution(bytes32 indexed conditionId, address indexed oracle,
bytes32 indexed questionId, uint256 outcomeSlotCount, uint256[] payoutNumerators)``
is emitted once per resolved condition. Together with the position-id
derivation in :mod:`intellifi.ctf` it yields, for every market that ever
resolved on Polymarket: the resolution block/time, the payout vector (hence
the winning outcome) and both outcome-token ids — no API involved, so the
wallet-level analyses are no longer confined to the 100-market corpus.

The oracle address tells the collateral: negRisk markets resolve through the
NegRisk adapter and their tokens are minted against the wrapped collateral.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
from eth_hash.auto import keccak

from . import config
from .ctf import position_id, USDC_E, WRAPPED_COLLATERAL
from .fills import fetch_logs_bisect, latest_block
from .onchain import POLYMARKET_CTF, POLYMARKET_NEGRISK_ADAPTER

CONDITION_RESOLUTION_TOPIC = "0x" + keccak(
    b"ConditionResolution(bytes32,address,bytes32,uint256,uint256[])").hex()
CTF_DEPLOY_BLOCK = 4_000_000          # Polymarket CTF on Polygon predates the exchanges
OUT = config.PARQUET_DIR / "ctf_resolutions.parquet"
RAW = config.RAW_DIR / "etherscan" / "ctf_resolutions.jsonl"

SCHEMA = {"condition_id": pl.Utf8, "oracle": pl.Utf8, "question_id": pl.Utf8,
          "outcome_slot_count": pl.Int64, "payout_numerators": pl.List(pl.Int64),
          "resolved_block": pl.Int64, "resolved_ts_utc": pl.Datetime("us", "UTC"),
          "tx_hash": pl.Utf8, "neg_risk": pl.Boolean,
          "winning_outcome_index": pl.Int32, "token0": pl.Utf8, "token1": pl.Utf8}


def decode_resolution(log: dict[str, Any]) -> dict[str, Any]:
    t = log["topics"]
    d = log["data"][2:]
    w = [int(d[i * 64:(i + 1) * 64], 16) for i in range(len(d) // 64)]
    slot_count, offset = w[0], w[1] // 32
    n = w[offset]
    payouts = w[offset + 1: offset + 1 + n]
    cid, oracle = t[1], "0x" + t[2][-40:]
    neg = oracle.lower() == POLYMARKET_NEGRISK_ADAPTER
    total = sum(payouts)
    win = (max(range(len(payouts)), key=lambda i: payouts[i]) if total and n == 2
           and max(payouts) * 2 > total else None)          # None: tie / non-binary / invalid
    coll = WRAPPED_COLLATERAL if neg else USDC_E
    return {"condition_id": cid, "oracle": oracle, "question_id": t[3],
            "outcome_slot_count": slot_count, "payout_numerators": payouts,
            "resolved_block": int(log["blockNumber"], 16),
            "resolved_ts_utc": datetime.fromtimestamp(int(log["timeStamp"], 16), tz=timezone.utc),
            "tx_hash": log["transactionHash"], "neg_risk": neg,
            "winning_outcome_index": win,
            "token0": str(position_id(coll, cid, 1)) if n == 2 else None,
            "token1": str(position_id(coll, cid, 2)) if n == 2 else None}


def fetch_all_resolutions(client, *, from_block: int = CTF_DEPLOY_BLOCK,
                          to_block: int | None = None) -> pl.DataFrame:
    """Every ConditionResolution on Polymarket's CTF; raw JSONL then parquet."""
    to_block = to_block or latest_block(client)
    # topic1 filter unused: we want all conditions -> bisect on the bare topic0
    logs = fetch_logs_bisect(client, POLYMARKET_CTF, 0, CONDITION_RESOLUTION_TOPIC, from_block, to_block)
    RAW.parent.mkdir(parents=True, exist_ok=True)
    with RAW.open("w") as fh:
        for lg in logs:
            fh.write(json.dumps(lg) + "\n")
    rows = [decode_resolution(lg) for lg in logs]
    df = pl.DataFrame(rows, schema=SCHEMA, orient="row" if rows else None).unique(subset=["condition_id"], keep="last")
    df.write_parquet(OUT, compression="zstd")
    return df


def load_resolutions() -> pl.DataFrame:
    return pl.read_parquet(OUT)
