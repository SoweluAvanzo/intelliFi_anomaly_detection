# Data dictionary

This dictionary documents every dataset we **collected** — the meaning and format of each column.
It covers two "eras" of trade data (the public **v1 archive** and our own **v2 on-chain tape**), the
market/resolution registries that join them, the Stage I feed-based store, and the on-chain
enrichment. The analysis *outputs* (backtest, coordination, atlas, …) are **derived, not collected**;
§8 describes each one and explains why they are defined by their producer scripts rather than
column-documented here.

## Why we collected these data

The project studies **market integrity on Polymarket**, and specifically the **make/take fee** — who
bears it, who captures the maker rebate it funds, and how trading profit and liquidity provision are
distributed across participants, alongside manipulation/anomaly patterns (flow concentration, wash
trading, coordinated timing).

Answering *who pays and who gains, at the level of individual traders* requires the **complete trade
record with the true buyer and seller of every trade**. Polymarket's public trade feed cannot support
this: it returns only a taker-side tail (≤ 4,000 recent trades per market), omits fills, and
**misreports trade direction**. Because Polymarket settles on-chain, that complete record is public, so
we take it from the blockchain rather than from the feed. Each store exists to answer a specific need:

- **v1 archive (§1–§2)** — the fully *resolved* past: realized profit/loss and concentration can be
  computed only once outcomes are known, so the "who wins / who loses" and maker-concentration results
  use it.
- **v2 tape (§3)** — the *fee era*: used to confirm the fee law, measure the maker markout, and test
  self-dealing under the fee regime.
- **registries (§4)** — attach each trade to its market, its **category** (hence fee rate / rollout
  group), and its **winning outcome**.
- **on-chain enrichment (§6)** — USDC transfers / funding graph, to resolve wallets into economic
  entities.
- **Stage I feed store (§5)** — the original feed-based corpus, kept for the earlier anomaly-detection
  work and as the cautionary baseline that motivated moving to the on-chain record.

## How they were collected (high level; the exact crawlers live in `scripts/`)

- **v1 archive** — *not* re-collected by us: the openly released Qin & Yang V1 database
  (arXiv:2606.04217, CC-BY-4.0), itself reconstructed from Polygon's settlement layer; placed on disk
  and read directly.
- **v2 tape** — reconstructed by reading the two v2 exchange contracts' on-chain event logs
  (`OrderFilled` and related) from Polygon via Etherscan, deduped by `(tx_hash, evt_index)`, and
  validated against an independent source (five markets reconcile exactly: 171,126 / 171,126 fills, with
  full conservation of shares between mint, trade, and redemption).
- **registries** — winners/resolutions from the CTF contract's `ConditionResolution` events; the
  market↔token map and category tags by cursor-enumerating the CLOB API.
- **on-chain enrichment** — USDC(.e) and ERC-1155 transfers for the universe wallets, via Etherscan.
- **Stage I feed store** — Polymarket's public Gamma / Data / CLOB APIs (a taker-side sample).

Collection writes each raw response before normalization and uses content-derived keys, so a store is
idempotent (re-running skips what already exists); the per-stage scripts in `scripts/` are the exact,
re-runnable record of how each store was built.

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
| `fee_usdc` | double | realised fee on the fill, USDC. **Dynamic**: ≈ `rate × min(price,1−price) × shares`, so it peaks near p=0.5 and →0 at the extremes. ~0 in the fee-free era, nonzero after the market's fee-start. **This is the V1 (old CTF-Exchange) `min` law at `rate=0.10`; V2 switched to a `p·(1−p)` law at lower per-category rates — see §3.** Stored in **USDC on taker-BUY rows but in outcome-token units on taker-SELL rows**, so divide SELL-row values by `price` before summing; a naive SUM over all rows overstates fees. |
| `condition_id` | string | market (CTF condition) key |
| `outcome_seq` | int64 | 1-based outcome index within the market (Yes=1/No=2 for binary) |
| `neg_risk` | string | `'t'`/`'f'` — market belongs to a negRisk family |
| `category` | string | coarse market category (e.g. `Sports`, `Up or Down`, `Politics`) |
| `category_refined` | string | finer category (e.g. `Price Action`) |
| `outcome_label` | string | label of the outcome token traded (e.g. `Up`, `Nuggets`, `Yes`) |
| `winning_outcome_label` | string | label of the outcome that ultimately won |
| `resolution_status` | string | `resolved` / `pending` / `disputed` / null |
| `taker_base_fee` | double | taker-side base fee **rate in basis points** (0 pre-rollout; `1000` = 10%). *Declared* rate only — many markets carry `1000` yet charge nothing, so define fee treatment from `fee_usdc>0`, not from this field. |
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
| `partition` | `list<string>` | outcome index-sets involved |
| `usdc_amount` | double | collateral moved, USDC |

**`redemptions.parquet`** — `PayoutRedemption` (winning shares → collateral after resolution):
`id`, `redeemer` (wallet), `collateral_token`, `parent_collection_id`, `condition_id`,
`index_sets` (`list<string>`, outcomes redeemed), `usdc_amount` (USDC paid out).

**`resolutions.parquet`** — `ConditionResolution` (the winner): `id` (`137_<block>_<logIndex>`, so
block→time via a proxy), `condition_id`, `oracle`, `question_id`, `outcome_slot_count`,
`payout_numerators` (`list<string>`; the index with numerator 1 is the winning outcome).

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
| `fee_raw` | int64 | fee in **6-decimal USDC base units** (`/1e6` = USDC). **Nonzero only where `is_taker_order = TRUE`** (takers pay; makers are never charged). The V2 taker-fee law is **`fee = feeRate · price · (1−price) · shares`** — a *product* form, unlike V1's `min(p,1−p)` (§1) — with `feeRate` per category: **0.07 Crypto, 0.04–0.05 most others, 0 for geopolitics/world (fee-free)**. Incidence `= fee/notional = feeRate·(1−price) ≤ feeRate`, largest on low-priced ("longshot") outcomes. Confirmed on-chain by `scripts/41` (median `fee/[p(1−p)·shares]` = 0.070). Matches Polymarket's published Trading-Fees formula. |
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
| `payout_numerators` | `list<int64>` | payout vector; the `1` marks the winner |
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
| `tags` | `list<string>` | category tags (e.g. `["Ethereum","Finance","crypto"]`) — the v2 category source |
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
| outcomes | `outcomes` (`list<str>`), `clob_token_ids` (`list<str>`), `outcome_prices_final` (`list<double>`) | **positional**: `outcomes[i] ↔ clob_token_ids[i] ↔ outcome_prices_final[i]` (final price 1.0 = winner) |
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

## 8. Analysis outputs (produced, not collected)

These are **results, not primary data**, which is why they are not column-documented here. This
dictionary documents the *collected* stores — the ground truth on disk — whereas each output is
**produced by, and canonically defined by, the script that writes it** (and, for the result JSONs, by
its own self-describing keys). Pinning their columns in this file would duplicate the producers and
drift out of sync as the analysis evolves, so each output instead points to its producer, which is the
single source of truth for its schema. (Inputs follow the rule "whatever is on disk is the truth";
outputs follow "the producing script is the unit of correctness.") What each one is:

- **`backtest/`** — mirror-strategy backtest events + summary — `scripts/05_backtest_mirror.py`.
- **`convergence/`** — per-market winner-price error vs hours-to-close, and the aggregate —
  `scripts/06_convergence.py`.
- **`coordination/`** — cotrade pairs, leader–lag edges, wash round-trips, behavioural partition —
  `scripts/04_coordination_analysis.py`.
- **`wallet_graph/`** — wallet-entity communities + `partition.json` —
  `scripts/03_resolve_wallet_entities.py`.
- **`entity/`** — per-wallet account-type codes (EOA / proxy / Gnosis Safe).
- **`events/`** — the events layer derived from `gamma_v2` — `scripts/16_derive_events.py`.
- **`fills/`, `fills_reconciliation/`** — the Dune 5-market on-chain fill prototype and its
  four-invariant reconciliation — `scripts/08_fetch_fills_dune.py`.
- **`atlas/`, `atlas_v2/`** — intermediates for the three archive atlas analyses —
  `docs/atlas_2026-08-30/scripts/atlas{A,B,C}/`.
- **`tape_v2_gate/`** — the cohort-gate subset of the v2 tape — `scripts/11_gate_v2_cohort.py`.
- **`_ctf_v2_shards/`** — condition-registry shards merged into `ctf_v2_conditions.parquet` (§4) —
  `scripts/13_merge_verify_ctf_v2.py`.
- **`docs/*.json`** — the headline result artifacts the write-ups cite; each is written by a numbered
  stage script and documents its own keys. E.g. `fee_rollout_did.json` (`scripts/36`),
  `maker_economics.json` (`scripts/32`), `maker_markout.json` (`scripts/40`), `actor_taxonomy.json`
  (`scripts/39`), `fee_behavioral.json` (`scripts/33`), `gate1_fee_audit_repro.json` (`scripts/41`),
  `self_dealing.json` (`scripts/42`).

For the exact schema of any output, read its producer script (above) or `DESCRIBE` the parquet (§9).
For the **derivation rule and the rationale** behind each output — what it is computed from, how,
and why that way — see `DERIVATIONS.md`.

## 9. How to consult

Always use the project venv (base Python's older pyarrow cannot read these files):

```bash
cd /path/to/IntelliFi_anomaly_detection && source .venv/bin/activate
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

## 10. Fees and rebates — the full model

Takers pay a trading fee; **makers are never charged**. Those fees **fund a daily rebate to makers**.
The fee *formula and rate changed* when Polymarket migrated from the first-generation exchange
("V1") to the second ("V2") on **28 April 2026**, so the two records use different laws: `fee_usdc`
(§1, V1) and `fee_raw` (§3, V2). Everything below is the **taker** fee unless stated.

### 10.1 Contracts, price, notional

A **share** of an outcome pays **$1 if that outcome occurs and $0 otherwise**. Its **price `p` ∈ (0,1)**
is the USDC cost of one share and equals the market's implied probability of the outcome; for a binary
market `p_Yes + p_No = 1`. A trade of `s` shares at price `p` has **notional (dollar value) `= p · s`**
USDC. (In the tables `s` is `shares`; the Polymarket docs call this quantity `C`.)

### 10.2 The taker fee

**V1 (old CTF-Exchange, ~Nov 2022 → 28 Apr 2026).** `fee = 0.10 · min(p, 1−p) · s` (rate = 1000 bps =
10%). Recorded as `fee_usdc` (§1), **in USDC on taker-BUY rows and in outcome-token units on
taker-SELL rows** — divide SELL values by `p` before summing; a naive SUM of the raw field overstates
fees (the archive's implied total is several times the fees actually collected). `taker_base_fee=1000`
is a *declared* rate that many markets carry without charging, so fee treatment in the V1 data is taken
from `fee_usdc > 0`.

**V2 (new exchange, 28 Apr 2026 →).** `fee = feeRate · p · (1−p) · s`. Recorded as `fee_raw` on the
taker-order row (§3). `feeRate` is set per **category**:

| Category | Taker `feeRate` | Maker rebate share |
|---|---|---|
| Crypto | 0.07 | 20% |
| Sports | 0.05 | 20% |
| Economics / Culture / Weather / Other–General | 0.05 | 25% |
| Finance / Politics / Tech / Mentions | 0.04 | 25% |
| **Geopolitics / world events** | **0 (fee-free)** | — |

(Polymarket sets these at its discretion and may change them; the rebate column is explained in §10.3.)

**Fee-curve properties.** Both `p(1−p)` (V2) and `min(p,1−p)` (V1) are **symmetric** — a trade at `p`
and the matching trade at `1−p` pay the same dollar fee (a 30¢ buy ≡ a 70¢ buy) — **zero at the
extremes** (near-certain outcomes are ~free to trade) and **largest in the middle** (the dollar fee
peaks at `p = 0.5`).

**Incidence (fee as a share of money staked), V2.** Since notional is `p·s`,
`incidence = fee / (p·s) = feeRate · (1−p)` — at most `feeRate`, and **largest for low-priced
("longshot") outcomes**, so the fee is **regressive by price**: the cheaper the outcome, the higher the
rate on the money put in. (For V1's `min` law the within-fee-market rate is flat at `rate` for `p<0.5`.)

**Worked example (V2 Crypto, `feeRate = 0.07`, buy `s = 100` shares):**

| price `p` | fee `= 0.07·p·(1−p)·100` | notional `p·s` | incidence `= 0.07·(1−p)` |
|---|---|---|---|
| 0.10 (longshot) | $0.63 | $10 | 6.3% |
| 0.50 (even) | $1.75 (max dollar fee) | $50 | 3.5% |
| 0.90 (favorite) | $0.63 | $90 | 0.7% |

**Precision and eligibility.** Fees round to 5 decimals; the smallest charge is 0.00001 USDC, so very
small trades near the extremes can round to **no fee**. V2 fees apply only to markets **deployed on/after
the activation date** in fee-enabled categories (`feesEnabled` flag per market); geopolitics/world is
excluded. In the **V1 archive window** the rollout was still staggered across categories, so many
categories (politics, most sports until spring 2026, …) were effectively un-charged even though they are
fee-enabled on V2.

### 10.3 The maker rebate (V2) — and why it is not a column here

Taker fees fund a **daily USDC rebate to makers**. It is **not stamped on any fill**, so it does not
appear in §1–§3; it is a separate per-market, per-day aggregate. Mechanism (Polymarket "Maker Rebates
Program"):

- A per-category **share `ρ` of the taker fees collected in a market** forms that market's daily
  **rebate pool** (`ρ` = 20% for Crypto/Sports, 25% for the other fee-enabled categories; geopolitics is
  fee-free).
- Each filled maker order is scored with the **same curve**: `fee_equivalent = feeRate · p · (1−p) · s`.
- A maker's **daily rebate** is its share of the pool, computed **per market**:
  `rebate = (your fee_equivalent / total fee_equivalent in that market that day) · rebate_pool`.
- Paid daily in USDC, with a **$1 minimum** accrual before payout.

**Consequence.** Only 20–25% of collected fees are returned, so being both the taker and the maker of
one's own trade (self-dealing to harvest the rebate) is a **guaranteed net loss**. Because the rebate is
unobservable in the trade record, "who the rebate rewards" is studied through the **return to providing
liquidity** (maker markout and realized PnL), not through rebate payments.

### Sources

Polymarket Help — *Trading Fees* (`help.polymarket.com/en/articles/13364478-trading-fees`) and *Maker
Rebates Program* (`…/13364471-maker-rebates-program`), retrieved 5 Oct 2026. The V1 `min` law is
confirmed on-chain against the CTF-Exchange `calculateFee` (`fee_usdc/(s·min(p,1−p)) = 0.100` across all
price deciles); the V2 `product` law is confirmed by `scripts/41_fee_rate_audit.py`
(median `fee/[p(1−p)·s] = 0.070`).
