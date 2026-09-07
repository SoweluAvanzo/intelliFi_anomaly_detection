"""Human-meaningful market categories for the analysis stack.

Maps each market's CLOB `tags` (data/parquet/clob_markets/tokens.parquet) to the
atlas fee-class taxonomy (data/parquet/atlas/category_to_feeclass_mapping.csv:
tag -> cls), taking the primary = most-common mapped class across a market's
tags. Validated 2026-09-03: 100/100 corpus markets classified, 0 unmapped.

Decoupled from the archive/tape views (it reads the CLOB registry directly and
filters to the condition_ids present in `trades`), so it works identically at
any scope (100-market corpus, sub-groups, whole dataset). Registers a temp
table `mktcat(condition_id, category, slug)` in the given connection.
"""
from __future__ import annotations

import collections
import csv

from . import config

CLOB_TOKENS = config.PARQUET_DIR / "clob_markets" / "tokens.parquet"
ATLAS_MAP = config.PARQUET_DIR / "atlas" / "category_to_feeclass_mapping.csv"


def load_tag_to_class() -> dict[str, str]:
    if not ATLAS_MAP.exists():
        raise FileNotFoundError(f"need {ATLAS_MAP} for category mapping")
    out: dict[str, str] = {}
    with open(ATLAS_MAP) as f:
        for row in csv.DictReader(f):
            out[row["category"].strip().lower()] = row["cls"].strip()
    return out


def register_market_categories(con, *, table: str = "mktcat") -> int:
    """Register temp table ``table``(condition_id, category, slug). Only markets
    present in the `trades` view are mapped (never materialises the whole CLOB
    enumeration). Returns the number of mapped markets."""
    if not CLOB_TOKENS.exists():
        raise FileNotFoundError(f"need {CLOB_TOKENS} for category mapping")
    tag2cls = load_tag_to_class()
    cids = [r[0] for r in con.sql("SELECT DISTINCT lower(condition_id) AS cid FROM trades").fetchall()]
    if not cids:
        raise RuntimeError("no condition_ids in `trades`")
    in_list = ",".join("'" + c.replace("'", "") + "'" for c in cids)
    rows = con.sql(f"""
        SELECT lower(condition_id) AS condition_id,
               any_value(market_slug) AS slug,
               any_value(tags) AS tags
        FROM read_parquet('{CLOB_TOKENS.as_posix()}')
        WHERE lower(condition_id) IN ({in_list})
        GROUP BY lower(condition_id)
    """).fetchall()
    cid_l, cat_l, slug_l = [], [], []
    for cid, slug, tags in rows:
        cats = [tag2cls.get(t.strip().lower()) for t in (tags or [])]
        cats = [c for c in cats if c]
        cid_l.append(cid)
        cat_l.append(collections.Counter(cats).most_common(1)[0][0] if cats else "other")
        slug_l.append(slug)
    import polars as pl
    mdf = pl.DataFrame({"condition_id": cid_l, "category": cat_l, "slug": slug_l})
    con.register(f"{table}_df", mdf.to_arrow())
    con.execute(f"CREATE TEMP TABLE {table} AS SELECT * FROM {table}_df")
    return len(cid_l)
