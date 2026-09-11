# Data dictionary

Every dataset we have collected, with the meaning and format of each column. Two "eras" of trade
data (the public **v1 archive** and our own **v2 on-chain tape**), the market/resolution
registries that join them, the Stage I feed-based store, and the on-chain enrichment. Analysis
*outputs* (backtest, coordination, atlas, …) are listed at the end but not column-documented — they
are produced by the scripts, not collected.

## Conventions (apply everywhere unless noted)
- **Addresses** — lowercase 0x-hex strings (wallets, contracts, tx hashes).
- **Timestamps** — `ts_utc` is `timestamp[us, UTC]`; `block_timestamp` is Unix epoch **seconds** (int).
- **price** — a probability in **[0, 1]**, i.e. USDC per share (a share pays \$1 if its outcome wins).
- **shares / size** — number of outcome-token shares (each redeems for \$1 if winning). `shares = usdc / price`.
- **usdc / usdc_amount / notional** — USDC in human units (dollars), `double`.
- **_raw** integer amounts — base units. USDC has **6 decimals**, so `fee_raw / 1e6 = USDC`.
- **token_id / asset_id** — the ERC-1155 outcome-token id (also the CLOB `asset_id`); one per outcome.
- **condition_id** — the CTF condition hash; the canonical market key.
- **Dedup** — the v2 tape can double-write a fill across overlapping chunk files; always dedup by
  `(tx_hash, evt_index)`. Archive rows are already unique.

---

## 1. v1 archive — trade fills (`data/external/polymarket_v1/`)
arXiv:2606.04217, CC-BY-4.0. **One row per maker fill.** `daily_aligned/*.parquet` (1,247 daily
files, standard binary markets) and `daily_aligned_multi/*.parquet` (856 files, negRisk markets —
identical schema plus `neg_risk_market_id`). Nov 2022 – Apr 2026.

| column | type | meaning |
|---|---|---|
| `asset_id` | string | outcome-token id (CLOB asset) traded on this fill |
| `block_timestamp` | int64 | fill time, Unix epoch **seconds** |
| `price` | double | fill price ∈ [0,1] (implied probability; USDC/share) |
| `maker` | string | maker wallet (resting-order owner) |
| `taker` | string | taker wallet (aggressor) |
| `taker_direction` | string | `BUY` / `SELL`, from the taker's side |
| `usdc_amount` | double | fill notional in USDC (= `price × shares`) |
| `fee_usdc` | double | realised fee on the fill, USDC. **Dynamic**: ≈ `rate × min(price,1−price) × shares`, so it peaks near p=0.5 and →0 at the extremes. ~0 in the fee-free era, nonzero after the market's fee-start |
| `condition_id` | string | market (CTF condition) key |
| `outcome_seq` | int64 | 1-based outcome index within the market (Yes=1/No=2 for binary) |
| `neg_risk` | string | `'t'`/`'f'` — market belongs to a negRisk family |
| `category` | string | coarse market category (e.g. `Sports`, `Up or Down`, `Politics`) |
| `category_refined` | string | finer category (e.g. `Price Action`) |
| `outcome_label` | string | label of the outcome token traded (e.g. `Up`, `Nuggets`, `Yes`) |
| `winning_outcome_label` | string | label of the outcome that ultimately won |
| `resolution_status` | string | `resolved` / `pending` / `disputed` / null |
| `taker_base_fee` | double | taker-side base fee **rate in basis points** (0 pre-rollout; `1000` = 10%) |
| `maker_base_fee` | double | maker-side base fee rate in basis points |
| `opens_at` | timestamp[us,UTC] | market open time |
| `close_at` | timestamp[us,UTC] | **scheduled** close/deadline — *not* the actual end of trading; prefer a resolution time |
| `resolved_at` | timestamp[us,UTC] | actual resolution time (**null for ~4%**, incl. markets resolved before `close_at`) |
| `market_slug` | string | human-readable market slug |
| `p_event` | double | archive implied probability of the outcome at the fill (equals `price` in observed rows) |
| `D` | int8 | signed taker direction: **+1 = BUY, −1 = SELL** |
| `neg_risk_market_id` | string | *(multi only)* negRisk family id linking the outcomes |

Note: in v1 the fee is recorded **on the maker-fill row** (`fee_usdc`); in the v2 tape it lives on
the taker-order row instead (see §3).

## 2. v1 archive — CTF lifecycle (`data/external/polymarket_v1/CTF/`)
On-chain Conditional-Tokens Framework events (market creation, collateral↔share conversions,
redemptions, resolution). 5 files.

**`preparations.parquet`** — `PrepareCondition` (market created): `id` (event id), `condition_id`,
`oracle` (UMA adapter), `question_id`, `outcome_slot_count` (# outcomes).

**`splits.parquet`** — `PositionSplit` (collateral → a full set of outcome shares) and
**`merges.parquet`** — `PositionsMerge` (outcome shares → collateral). Both:

| column | type | meaning |
|---|---|---|
| `id` | string | event id |
| `stakeholder` | string | wallet performing the split/merge |
| `collateral_token` | string | collateral address (USDC) |
| `parent_collection_id` | string | CTF parent collection (0x0 for top-level) |
| `condition_id` | string | market key |
| `partition` | list<string> | outcome index-sets involved |
| `usdc_amount` | double | collateral moved, USDC |

**`redemptions.parquet`** — `PayoutRedemption` (winning shares → collateral after resolution):
`id`, `redeemer` (wallet), `collateral_token`, `parent_collection_id`, `condition_id`,
`index_sets` (list<string>, outcomes redeemed), `usdc_amount` (USDC paid out).

**`resolutions.parquet`** — `ConditionResolution` (the winner): `id` (`137_<block>_<logIndex>`, so
block→time via a proxy), `condition_id`, `oracle`, `question_id`, `outcome_slot_count`,
`payout_numerators` (list<string>; the index with numerator 1 is the winning outcome).

## 3. v2 on-chain tape (`data/parquet/tape_v2/**/part.parquet`)
Our extraction of the two v2 exchange contracts' logs on Polygon; **one row per log**, 8,960 chunk
files, Apr–Aug 2026. `tape_v2_other/` = same-signature events from the third contract; `tape_v2_gate/`
= the cohort-gate subset. **Dedup by `(tx_hash, evt_index)`.**

| column | type | meaning |
|---|---|---|
| `exchange` | string | `v2_a` or `v2_b` (the two v2 CTF-exchange contracts) |
| `block_number` | int64 | Polygon block |
| `ts_utc` | timestamp[us,UTC] | block time |
| `tx_hash` | string | transaction hash (with `evt_index`, the unique fill key) |
| `evt_index` | int64 | log index within the tx |
| `event` | string | log type (`OrderFilled` is the per-fill record used for analysis) |
| `order_hash` | string | on-chain order hash |
| `maker` | string | maker wallet |
| `taker` | string | taker wallet |
| `side` | string | `BUY`/`SELL` — the maker order's side on this row |
| `token_id` | string | outcome-token id traded |
| `maker_amount_raw` | int64 | raw amount the maker gave (base units) |
| `taker_amount_raw` | int64 | raw amount the taker gave (base units) |
| `fee_raw` | int64 | fee in **6-decimal USDC base units** (`/1e6` = USDC). **Nonzero only where `is_taker_order = TRUE`** |
| `builder` | string | block-builder address (usually null/0x0) |
| `metadata` | string | auxiliary log metadata (usually empty) |
| `usdc` | double | fill notional, USDC (derived) |
| `shares` | double | fill size, shares (derived) |
| `price` | double | fill price ∈ [0,1] (derived) |
| `is_taker_order` | bool | TRUE = this row is the taker-order aggregate — **the fee lives here**; PnL is read from the maker-fill rows (`FALSE`) |

`data/parquet/wallet_fills/*.parquet` is the same fill schema keyed per universe wallet (Etherscan
`getLogs` per wallet), with extra `maker_asset_id`, `taker_asset_id`, `maker_side`, and a `wallet`
column (the wallet the file belongs to).

## 4. Market & resolution registries
**`ctf_v2_conditions.parquet`** (v2 winners) and **`ctf_resolutions_corpus.parquet`** (corpus-wide;
same schema, `winning_outcome_index` is int64 there):

| column | type | meaning |
|---|---|---|
| `condition_id` | string | market key |
| `oracle` | string | UMA adapter address |
| `question_id` | string | UMA question id |
| `outcome_slot_count` | int64 | number of outcomes |
| `payout_numerators` | list<int64> | payout vector; the `1` marks the winner |
| `resolved_block` | int64 | block of `ConditionResolution` |
| `resolved_ts_utc` | timestamp[us,UTC] | resolution time (the canonical "close" for v2) |
| `tx_hash` | string | resolution tx |
| `neg_risk` | bool | negRisk market |
| `winning_outcome_index` | int32/int64 | 0-based winning outcome |
| `token0`, `token1` | string | the two outcome-token ids (Yes, No) |

**`clob_markets/tokens.parquet`** — token→market join with category tags (one row per market token;
negRisk markets get a condition-level row with empty `token_id`):

| column | type | meaning |
|---|---|---|
| `condition_id` | string | market key |
| `question`, `market_slug` | string | market text / slug |
| `neg_risk` | bool | negRisk market |
| `neg_risk_market_id` | string | negRisk family id |
| `closed`, `active`, `archived` | bool | market status flags |
| `event_id` | int32 | parent event id |
| `end_date_iso` | string | scheduled end date (ISO) |
| `tags` | list<string> | category tags (e.g. `["Ethereum","Finance","crypto"]`) — the v2 category source |
| `token_id` | string | outcome-token id (empty for negRisk — join by `condition_id`) |
| `outcome` | string | outcome label for `token_id` |

**`neg_risk_families/families.parquet`** — negRisk family membership: `family_event_id`,
`family_event_slug`, `neg_risk_market_id`, `member_condition_id`, `member_token_id_yes`,
`member_token_id_no`, `member_slug`, `member_outcome_name`.

**`gamma_v2/markets_v2.parquet`** — v2 market metadata from Gamma; **same schema and field meanings
as the Stage I `markets` table (§5)**.

## 5. Stage I feed store (the 100-market feed corpus)
**`markets/markets.parquet`** — one row per market, full Gamma metadata.

| group | columns | meaning |
|---|---|---|
| identifiers | `id`, `slug`, `question`, `condition_id`, `question_id`, `event_id`, `event_slug` | market/event ids and text |
| outcomes | `outcomes` (list<str>), `clob_token_ids` (list<str>), `outcome_prices_final` (list<double>) | **positional**: `outcomes[i] ↔ clob_token_ids[i] ↔ outcome_prices_final[i]` (final price 1.0 = winner) |
| status | `closed`, `active`, `archived`, `accepting_orders`, `enable_order_book`, `clear_book_on_start` | lifecycle flags |
| resolution | `uma_resolution_statuses` (str), `closed_time` (ts) | UMA status; **`closed_time` = actual close of trading — use this, not `end_date`** |
| negRisk | `neg_risk`, `neg_risk_other`, `neg_risk_request_id`, `event_neg_risk`, `event_neg_risk_market_id` | negRisk membership |
| prices | `best_bid`, `best_ask`, `spread`, `last_trade_price`, `one_month_price_change` | last-seen book/price snapshot |
| volume | `volume`, `volume_clob`, `volume_24hr`, `volume_24hr_clob`, `volume_1wk_clob`, `volume_1mo_clob`, `volume_1yr_clob` | **share volumes, not USDC** (`volume_clob = Σ taker-order shares`) |
| liquidity | `liquidity`, `liquidity_clob` | resting-book depth |
| rewards | `rewards_min_size`, `rewards_max_spread`, `holding_rewards_enabled` | maker-reward program params |
| config | `order_price_min_tick_size`, `order_min_size` | order constraints |
| UMA | `uma_bond`, `uma_reward` | dispute bond/reward (USDC) |
| timestamps | `start_date`, `end_date`, `created_at`, `updated_at`, `accepting_orders_timestamp`, `deploying_timestamp`, `uma_end_date`, `game_start_time` | lifecycle times (`end_date` = scheduled, not actual close) |

**`trades/condition_id=…/part.parquet`** — Data-API taker-side tail (one row per taker fill; ≤4000
per market; ~90% at p≤0.05 or ≥0.95):

| column | type | meaning |
|---|---|---|
| `condition_id` | string | market key |
| `asset_id` | string | outcome-token traded |
| `outcome`, `outcome_index` | string / int32 | outcome label and 0-based index |
| `proxy_wallet` | string | the taker wallet |
| `pseudonym`, `name`, `verified` | string / bool | display profile (often null) |
| `side` | string | `BUY`/`SELL` (taker) |
| `price` | double | fill price ∈ [0,1] |
| `size` | double | shares |
| `notional_usdc` | double | USDC notional |
| `ts_utc` | timestamp[us,UTC] | fill time |
| `tx_hash` | string | tx (unique per taker fill) |
| `event_slug`, `market_slug`, `title` | string | event/market text |

**`holders/condition_id=…/part.parquet`** — holder snapshot (≤500 per outcome): `condition_id`,
`asset_id`, `outcome_index`, `proxy_wallet`, `pseudonym`, `name`, `verified`, `amount` (shares held),
`snapshot_ts_utc`.

**`universe.parquet`** — per-wallet aggregates over the corpus: `proxy_wallet`, `total_notional`
(USDC), `n_trades`, `n_markets`, `realised_pnl` (USDC), `n_bets`, `realised_hit_rate`,
`mean_implied_p`, `calibration_gap` (= hit_rate − implied_p), `rk_notional`, `rk_pnl`, `rk_skill`
(rank columns).

**`prices_history/<token_id>.parquet`** — per-token price series: `token_id`, `ts_utc`, `price`.

## 6. On-chain enrichment (`data/parquet/onchain_transfers/`, one file per universe wallet)
**`usdc_e/` and `usdc_native/`** — ERC-20 USDC transfers (bridged USDC.e and native USDC):

| column | type | meaning |
|---|---|---|
| `owner` | string | the universe wallet this file tracks |
| `token`, `contract_address` | string | token address |
| `block_number` | int64 | block |
| `ts_utc` | timestamp[us,UTC] | time |
| `tx_hash` | string | tx |
| `from_address`, `to_address` | string | transfer endpoints |
| `value` | double | transfer amount (token units; see `token_decimal`) |
| `token_symbol` | string | e.g. `USDC`, `USDC.e` |
| `token_decimal` | int32 | token decimals (6 for USDC) |

**`erc1155/`** — outcome-token (CTF share) transfers: `owner`, `contract_address`, `block_number`,
`ts_utc`, `tx_hash`, `from_address`, `to_address`, `token_id` (outcome-token = CLOB asset id),
`token_value` (shares). Note: these are **fill settlements, not relationships** — excluded from the
entity graph.

**`entity/codes.parquet`** — account-type classification cache (from `eth_getCode`): `wallet`,
`is_eoa` (bool — no contract code = raw key), `code_hash` (bytecode hash identifying the proxy type:
`f5c625376518f07a` = Gnosis Safe / browser-wallet users, `cefa4f597e0304e1` = Polymarket factory
proxy / email·Magic users), `code_len` (bytecode length).

## 7. Analysis views (built at query time, not stored)
`intellifi.archive.register_archive_views(con)` builds these over the v1 archive under the names the
Stage I code expects:
- **`arc_raw`** — one row per maker fill (the workhorse): `condition_id, token_id, outcome_index,
  ts_utc, block_timestamp, maker, taker, taker_direction, D, price, usdc_amount, fee_usdc,
  shares, neg_risk, category, category_refined, market_slug, outcome_label, winning_outcome_label,
  resolution_status, opens_at, close_at, resolved_at, p_event`.
- **`markets`** — one row per condition (slug, neg_risk, category, `created_at`, `end_date`,
  `closed_time`, `clob_token_ids`, `volume_clob`, `winning_outcome_label`/`_index`).
- **`trades`** — maker fills aggregated into taker orders per (second, taker, token, direction):
  `condition_id, asset_id, proxy_wallet, side, price (VWAP), size, notional_usdc, ts_utc, …`.
- **`fills`** — canonical maker-record schema (matches the v2 tape fill schema; `is_taker_order`
  is FALSE for every archive row; `tx_hash` is a synthetic key).
- **`winning_outcomes`**, **`prices_history`** — resolution and minute-VWAP helpers.

The warehouse also exposes a **`v2_raw`** view over the v2 tape (`INTELLIFI_SOURCE=tape_v2`) that
auto-dedups by `(tx_hash, evt_index)`.

## 8. Analysis outputs (produced, not collected — see the scripts)
Not column-documented here; each is written by its stage script and consumed by the notebooks/report:
`backtest/`, `convergence/`, `coordination/`, `wallet_graph/`, `entity/` (beyond `codes`), `events/`,
`fills/` + `fills_reconciliation/` (Dune 5-market prototype), `atlas/` + `atlas_v2/` (the archive
atlas), `tape_v2_gate/`, `_ctf_v2_shards/`. The headline result artifacts are the `docs/*.json`
files (e.g. `fee_behavioral.json`, `maker_economics.json`, `actor_taxonomy.json`).

## 9. How to consult
Always use the project venv (base Python's older pyarrow cannot read these files):

```bash
cd /home/sowelo/Scrivania/IntelliFi_anomaly_detection && source .venv/bin/activate
```

Schema + peek of any store (DuckDB over the parquet glob):
```bash
python -c "import duckdb; duckdb.sql(\"DESCRIBE SELECT * FROM 'data/parquet/tape_v2/**/*.parquet'\").show()"
python -c "import duckdb; duckdb.sql(\"SELECT * FROM 'data/parquet/ctf_v2_conditions.parquet' LIMIT 5\").show()"
```

The v1 analysis views:
```python
import sys, duckdb; sys.path.insert(0, "src")
from intellifi.archive import register_archive_views
con = duckdb.connect(); con.execute("PRAGMA memory_limit='3GB'")
register_archive_views(con)                      # optional: start=, end=, condition_ids=
con.sql("DESCRIBE arc_raw").show()
```

For full-tape scans set `PRAGMA memory_limit` and bucket by wallet-hash / block-range (uncapped
DuckDB scans have OOM-ed the box); always dedup the v2 tape by `(tx_hash, evt_index)`.
