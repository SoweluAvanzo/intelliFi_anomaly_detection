"""CLOB API client: ``/prices-history`` for resolved-market price trajectories.

Notes from the v2 spec (§4.3):

* ``/prices-history.t`` is **seconds** since epoch. Always canonicalised into
  a tz-aware ``ts_utc`` column.
* The endpoint is rate-limited but unauthenticated.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import polars as pl

from . import config
from .http import get_json
from .normalize import safe_float, to_utc_from_seconds

log = logging.getLogger(__name__)


PRICES_HISTORY_DIR = config.PARQUET_DIR / "prices_history"


def fetch_prices_history(
    token_id: str,
    *,
    start_ts: int | None = None,
    end_ts: int | None = None,
    interval: str = "1h",
    fidelity: int | None = None,
) -> list[dict[str, Any]]:
    """Pull the raw ``prices-history`` series for one CLOB token id.

    ``interval`` is a **lookback window ending now** in the CLOB API (``"1m"``
    = one month, ``"1w"``, ``"1d"``, ``"6h"``, ``"1h"``, ``"max"``), not a
    sampling resolution; resolution is ``fidelity`` (minutes). The 2026-05-11
    corpus was fetched with the default and every non-empty series spans
    exactly the 30 days before the fetch at 600 s spacing, so only markets
    that closed inside that window have history. For a full-lifetime series
    pass ``start_ts``/``end_ts`` (market ``created_at`` → ``closed_time``)
    with an explicit ``fidelity``.
    """
    params: dict[str, Any] = {"market": str(token_id), "interval": interval}
    if start_ts is not None:
        params["startTs"] = int(start_ts)
    if end_ts is not None:
        params["endTs"] = int(end_ts)
    if fidelity is not None:
        params["fidelity"] = int(fidelity)
    data = get_json(f"{config.CLOB}/prices-history", params=params)
    if isinstance(data, dict) and "history" in data:
        return data.get("history", []) or []
    if isinstance(data, list):
        return data
    return []


def history_parquet_path(token_id: str) -> Path:
    return PRICES_HISTORY_DIR / f"{token_id}.parquet"


_HISTORY_SCHEMA: dict[str, pl.DataType] = {
    "token_id": pl.Utf8,
    "ts_utc": pl.Datetime("us", "UTC"),
    "price": pl.Float64,
}


def to_dataframe(rows: list[dict[str, Any]], token_id: str) -> pl.DataFrame:
    cleaned = []
    for r in rows:
        t = r.get("t") or r.get("timestamp")
        p = r.get("p") or r.get("price")
        ts = to_utc_from_seconds(t)
        price = safe_float(p)
        if ts is None or price is None:
            continue
        cleaned.append({"token_id": str(token_id), "ts_utc": ts, "price": price})
    return pl.DataFrame(cleaned, schema=_HISTORY_SCHEMA,
                        orient="row" if cleaned else None)


def fetch_and_store(
    token_id: str,
    *,
    interval: str = "1h",
    overwrite: bool = False,
) -> tuple[Path, int]:
    """Idempotent fetch + parquet write for a single token's price history."""
    PRICES_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = history_parquet_path(token_id)
    if path.exists() and not overwrite:
        existing = int(pl.scan_parquet(path).select(pl.len()).collect().item())
        return path, existing

    rows = fetch_prices_history(token_id, interval=interval)
    raw_dir = config.RAW_DIR / "clob" / "prices_history"
    raw_dir.mkdir(parents=True, exist_ok=True)
    with (raw_dir / f"{token_id}.jsonl").open("w") as fh:
        fh.write(json.dumps(rows, default=str) + "\n")

    df = to_dataframe(rows, token_id)
    df.write_parquet(path, compression="zstd")
    return path, df.height


# ---------------------------------------------------------------------------
# Complete market enumeration via cursor pagination (no offset ceiling).
# Gamma /markets caps pagination at offset ~2000 and drops markets on dense
# endDate days; the CLOB /markets endpoint is cursor-paged and lossless, and is
# token/condition-native — the correct source for a complete market list to join
# to the on-chain tape by conditionId (verified 2026-08-31).
# ---------------------------------------------------------------------------

def iter_clob_markets(*, page_log_every: int = 25):
    """Yield every CLOB market dict via ``/markets?next_cursor=`` pagination.

    Response shape: ``{"data": [...up to 1000...], "next_cursor": "...", "count": N}``.
    Pagination ends when ``next_cursor`` is empty or the sentinel ``"LTE="``.
    """
    import logging
    log = logging.getLogger(__name__)
    cursor = ""
    page = 0
    seen_cursor: set[str] = set()
    while True:
        params = {"next_cursor": cursor} if cursor else {}
        resp = get_json(f"{config.CLOB}/markets", params=params)
        if not isinstance(resp, dict):
            raise RuntimeError(f"unexpected CLOB /markets shape: {type(resp).__name__}")
        data = resp.get("data") or []
        for m in data:
            yield m
        nxt = resp.get("next_cursor") or ""
        page += 1
        if page % page_log_every == 0:
            log.info("CLOB /markets page %d (cursor=%s, batch=%d)", page, cursor[:12], len(data))
        if not nxt or nxt == "LTE=" or nxt in seen_cursor or not data:
            return
        seen_cursor.add(nxt)
        cursor = nxt


def clob_market_token_rows(m: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten one CLOB market into per-token rows for the tape join.

    Defensive ``.get`` throughout — the CLOB object shape is confirmed against a
    live spot-check before analysis relies on the family/category fields.
    """
    cid = m.get("condition_id") or m.get("conditionId")
    tags = m.get("tags")
    if not isinstance(tags, list):
        tags = [tags] if tags else []
    base = {
        "condition_id": (str(cid).lower() if cid else None),
        "question": m.get("question"),
        "market_slug": m.get("market_slug") or m.get("slug"),
        "neg_risk": m.get("neg_risk"),
        "neg_risk_market_id": m.get("neg_risk_market_id") or m.get("neg_risk_request_id"),
        "closed": m.get("closed"),
        "active": m.get("active"),
        "archived": m.get("archived"),
        "event_id": m.get("event_id") or m.get("event_slug"),
        "end_date_iso": m.get("end_date_iso") or m.get("end_date"),
        "tags": [str(x) for x in tags],   # CLOB category source (event_id is absent)
    }
    rows = []
    for tok in (m.get("tokens") or []):
        tid = tok.get("token_id") if isinstance(tok, dict) else None
        if not tid:  # negRisk markets return empty token_id — skip the blank leg
            continue
        rows.append({**base, "token_id": str(tid),
                     "outcome": (tok.get("outcome") if isinstance(tok, dict) else None)})
    if not rows:
        # negRisk / tokenless market: emit one condition-level row so it is not
        # lost (join to the tape by condition_id via CTF token derivation).
        rows.append({**base, "token_id": None, "outcome": None})
    return rows
