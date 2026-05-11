"""Endpoint roots, storage paths, and tunable constants.

All paths are anchored at the repository root, resolved via ``REPO_ROOT``.
Override any value with an environment variable of the same name.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- API roots -------------------------------------------------------------
GAMMA = os.getenv("INTELLIFI_GAMMA", "https://gamma-api.polymarket.com")
CLOB = os.getenv("INTELLIFI_CLOB", "https://clob.polymarket.com")
DATA = os.getenv("INTELLIFI_DATA", "https://data-api.polymarket.com")

# --- Storage paths ---------------------------------------------------------
DATA_DIR = Path(os.getenv("INTELLIFI_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PARQUET_DIR = DATA_DIR / "parquet"
DUCKDB_PATH = Path(os.getenv("INTELLIFI_DUCKDB", REPO_ROOT / "intellifi.duckdb"))

# Parquet sub-paths (one directory per logical table)
MARKETS_PARQUET = PARQUET_DIR / "markets"
EVENTS_PARQUET = PARQUET_DIR / "events"
NEG_RISK_FAMILIES_PARQUET = PARQUET_DIR / "neg_risk_families"
TRADES_PARQUET = PARQUET_DIR / "trades"        # partitioned by condition_id
HOLDERS_PARQUET = PARQUET_DIR / "holders"      # partitioned by condition_id

# --- HTTP behaviour --------------------------------------------------------
HTTP_TIMEOUT = float(os.getenv("INTELLIFI_HTTP_TIMEOUT", "30"))
HTTP_RETRIES = int(os.getenv("INTELLIFI_HTTP_RETRIES", "5"))
HTTP_BACKOFF_BASE = float(os.getenv("INTELLIFI_HTTP_BACKOFF_BASE", "1.5"))
USER_AGENT = os.getenv(
    "INTELLIFI_USER_AGENT",
    "intellifi/0.1 (Polymarket market-integrity research; +https://github.com/)",
)

# --- Universe defaults -----------------------------------------------------
# How many days back to look for resolved markets in the vertical slice.
RESOLVED_LOOKBACK_DAYS = int(os.getenv("INTELLIFI_LOOKBACK_DAYS", "180"))

# Gamma /markets page size (max appears to be 500).
GAMMA_PAGE_SIZE = int(os.getenv("INTELLIFI_GAMMA_PAGE_SIZE", "500"))

# Data API /trades page size (max appears to be 500).
TRADES_PAGE_SIZE = int(os.getenv("INTELLIFI_TRADES_PAGE_SIZE", "500"))


def ensure_dirs() -> None:
    """Create all storage directories if missing. Idempotent."""
    for d in (
        DATA_DIR,
        RAW_DIR,
        PARQUET_DIR,
        MARKETS_PARQUET,
        EVENTS_PARQUET,
        NEG_RISK_FAMILIES_PARQUET,
        TRADES_PARQUET,
        HOLDERS_PARQUET,
    ):
        d.mkdir(parents=True, exist_ok=True)
