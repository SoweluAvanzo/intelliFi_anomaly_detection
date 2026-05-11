"""DuckDB views over the parquet files written by Phase 1/2 loaders.

A single ``open_warehouse()`` call returns a DuckDB connection with the
following views materialised:

* ``markets``            — 1 row per market (Phase 1 Gamma).
* ``neg_risk_families``  — 1 row per (family, member) pair.
* ``trades``             — 1 row per trade.
* ``holders``            — 1 row per (market, outcome, wallet) snapshot.
* ``winning_outcomes``   — derived: 1 row per market with the winning
                            outcome_index (max of ``outcome_prices_final``).

Views are recreated on every call so schema drift in upstream parquet
propagates immediately.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from . import config


def _parquet_glob(d: Path) -> str:
    """A DuckDB-readable glob for partitioned parquet under ``d``."""
    return str(d / "**" / "*.parquet")


def open_warehouse(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open (or create) a DuckDB database with views over the parquet store.

    Pass ``db_path=":memory:"`` for an ephemeral analysis session.
    """
    db_path = db_path or config.DUCKDB_PATH
    con = duckdb.connect(str(db_path))

    con.execute(f"""
        CREATE OR REPLACE VIEW markets AS
        SELECT * FROM read_parquet('{_parquet_glob(config.MARKETS_PARQUET)}');
    """)
    con.execute(f"""
        CREATE OR REPLACE VIEW neg_risk_families AS
        SELECT * FROM read_parquet('{_parquet_glob(config.NEG_RISK_FAMILIES_PARQUET)}');
    """)
    con.execute(f"""
        CREATE OR REPLACE VIEW trades AS
        SELECT * FROM read_parquet('{_parquet_glob(config.TRADES_PARQUET)}',
                                   hive_partitioning = false);
    """)
    con.execute(f"""
        CREATE OR REPLACE VIEW holders AS
        SELECT * FROM read_parquet('{_parquet_glob(config.HOLDERS_PARQUET)}',
                                   hive_partitioning = false);
    """)

    # Winning outcome for each resolved market: index of the entry in
    # outcome_prices_final that is closest to 1.0. In resolved markets the
    # winning entry should equal 1.0 and others should equal 0.0.
    con.execute("""
        CREATE OR REPLACE VIEW winning_outcomes AS
        WITH unnested AS (
            SELECT condition_id, slug, question, neg_risk, event_id,
                   outcomes, outcome_prices_final, clob_token_ids,
                   generate_subscripts(outcome_prices_final, 1) AS idx,
                   unnest(outcome_prices_final) AS p
            FROM markets
            WHERE condition_id IS NOT NULL
        ),
        ranked AS (
            SELECT *,
                   row_number() OVER (PARTITION BY condition_id
                                      ORDER BY p DESC NULLS LAST, idx ASC) AS rk
            FROM unnested
        )
        SELECT condition_id, slug, question, neg_risk, event_id,
               (idx - 1) AS winning_outcome_index,
               outcomes[idx] AS winning_outcome_name,
               clob_token_ids[idx] AS winning_token_id,
               p AS winning_outcome_price
        FROM ranked
        WHERE rk = 1 AND p IS NOT NULL AND p >= 0.5;
    """)

    return con
