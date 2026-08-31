# Polymarket structural atlas — Q5 (share creation vs. secondary trading), Q6a (resolution-anchored convergence), Q6b (maker concentration)

Author: agent C (struct_*). Date: 2026-08-30. Data: public Polymarket-v1 archive (arXiv:2606.04217, CC-BY-4.0) at `data/external/polymarket_v1/` — `daily_aligned` (binary) + `daily_aligned_multi` (negRisk) maker-fill files 2022-11-21 → 2026-04-28, plus `CTF/{preparations,splits,merges,resolutions,redemptions}.parquet`. No external API was called. Everything was computed with `.venv/bin/python` + DuckDB, one daily file (or one CTF block-range chunk) per SQL statement, results written to parquet immediately, `PRAGMA memory_limit='4GB'`, `PRAGMA threads=4`, `PRAGMA temp_directory=<scratch>/duck_tmp`, each process additionally wrapped in `systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G timeout 520`. Outputs: `data/parquet/atlas/struct_*.parquet` (19 files, 3.9 GB) and CSV/log files in the scratch dir `atlasC/`.

## 0. Corpus and semantics established before answering

* Tape: **745,781,095 maker-fill rows** (601,713,694 binary + 144,067,401 negRisk), **$28,577,595,925** fill notional (Σ `usdc_amount`), **851,083 markets** (687,814 binary, 163,269 negRisk), 1,235,715 distinct makers. Row-count and notional totals of every derived table reconcile exactly to these figures (checked: `struct_condmonth`, `struct_maker_month`, `struct_mintgroups_condmonth`).
* Archive semantics, verified against the project's own tx-level on-chain fills (`data/parquet/fills/`, 5 markets, 276,837 OrderFilled rows): one row = one **maker** fill; `asset_id`/`price` are the **maker's** token and limit price; `taker_direction` is the taker's side *as counterparty of that maker* (so a maker who BUYs the complementary token appears as `taker_direction='SELL'` on that token). For the one market joined leg-by-leg (`0x4dce…`, 1,040 maker fills) 247/247 complement legs and 817/817 same-token legs matched the on-chain fills on (maker, taker, second, shares) with the archive's `asset_id` equal to the **maker's** token. Mint/merge legs are therefore not "hidden"; they simply sit on the complementary token with price ≈ 1 − taker price (median p₁+p₂ = 1.000 in same-second groups).
* `resolution_status`: resolved 843,335, pending 525, disputed 12, NULL 7,211. `resolved_at` is non-NULL for **313,026** markets only — all binary; **0 of 158,910 resolved negRisk markets** carry it, and 99.3 % of the non-NULL values are markets resolved in 2026-01…05 (Gamma only started populating it recently). Fills after `resolved_at`: 0 (checked on sample days). Fills after `close_at`: common (7–30 % of a day's rows) — `close_at` is a scheduled deadline, never used as a close here.
* Category classes: the binary files carry an 8-class `category_refined` (Sports, Politics, Crypto, Price Action, Finance, Culture, Sci-Tech, Other; "Price Action" = short-horizon crypto up/down markets). The negRisk files carry only the fine tag. Mapping (`struct_category_classmap.parquet`): a tag's class = the notional-weighted majority class it has in the binary files (1,470 tags → 842,663 markets, $27.88 B, "archive" source); 107 negRisk-only tags ($207 M, 3,521 markets) by keyword rule; 323 tags ($488 M, 4,899 markets, largest: `january 6` $226 M/3 markets, `United States` $143 M) unmapped → "Other". Class totals: Sports $10.98 B (419,511 mkts), Politics $6.76 B (35,391), Crypto $3.89 B (123,894), Price Action $3.18 B (189,791), Other $1.39 B (16,946), Finance $1.02 B (18,608), Culture $0.89 B (12,742), Sci-Tech $0.46 B (34,200).
* CTF events have block numbers but no timestamps. A block→time map was built from the fill tape without any external call: for each 10k-block bin, the intercept of `t − 2.2·block` is bracketed from above by the earliest first-fill of conditions *prepared* in the bin and from below by the latest last-fill of conditions *resolved* in the bin (2,127 bins bracketed within [−1 h, +2 h]); spikes removed, gaps interpolated; the tail (blocks ≥ 85.0 M, where the tape's own anchors thin out) uses the medians of Gamma `resolved_at` per bin (+214 s, the measured on-chain lag). **Validation on 313,026 resolutions:** on-chain resolution time − Gamma `resolved_at` = median +216 s, IQR +84…+457 s, p1/p99 −2,281/+2,580 s; implied block time 2.0–2.33 s. Month boundaries were converted to blocks with this map; the "April 2026" CTF month is cut at the tape's end (2026-04-29 00:00 UTC) so CTF and fill windows coincide. Collateral restricted to USDC.e, native USDC and the negRisk wrapped collateral (a WMATIC row with 1.0e12 "USDC" and 100+ spam tokens were excluded); `parent_collection_id` = 0 only (6 rows excluded).

## Q5 — Share creation (CTF splits) vs. secondary trading (fill notional)

### Q5.1 Monthly CTF flows vs. fill notional, 2023-01 → 2026-04 (USDC millions; `exch` = CTF-Exchange stakeholder = mint/merge matches in binary markets; `nr` = NegRiskAdapter stakeholder = negRisk exchange matches **plus** user splits and negRisk conversions; `ada` = two Polymarket vanity contracts `0xADa100…`/`0xAdA100D…` active from 2026-04; `oth` = 109k other stakeholders, i.e. wallets splitting directly on the CTF)

| ym | split_M | exch_M | nr_M | ada_M | oth_M | merge_M | redeem_M | fill_M | mint_to_fill | exch_mint_to_fill | merge_to_fill | redeem_to_fill |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023-01 | 20.3 | 0.8 | 0.0 | 0.0 | 19.5 | 1.3 | 21.1 | 0.6 | 36.625 | 1.426 | 2.260 | 38.061 |
| 2023-02 | 5.8 | 2.3 | 0.0 | 0.0 | 3.5 | 0.8 | 5.3 | 1.3 | 4.393 | 1.743 | 0.583 | 4.068 |
| 2023-03 | 7.9 | 6.2 | 0.0 | 0.0 | 1.7 | 2.8 | 3.9 | 5.9 | 1.334 | 1.045 | 0.465 | 0.652 |
| 2023-04 | 3.4 | 2.1 | 0.0 | 0.0 | 1.3 | 0.7 | 2.9 | 1.5 | 2.322 | 1.447 | 0.477 | 2.000 |
| 2023-05 | 16.0 | 4.2 | 0.0 | 0.0 | 11.8 | 1.5 | 14.1 | 3.9 | 4.099 | 1.069 | 0.380 | 3.615 |
| 2023-06 | 4.9 | 4.8 | 0.0 | 0.0 | 0.1 | 1.1 | 3.6 | 3.7 | 1.320 | 1.292 | 0.295 | 0.965 |
| 2023-07 | 4.1 | 4.0 | 0.0 | 0.0 | 0.1 | 1.0 | 2.5 | 3.3 | 1.243 | 1.213 | 0.295 | 0.761 |
| 2023-08 | 4.6 | 4.6 | 0.0 | 0.0 | 0.0 | 1.5 | 2.0 | 4.2 | 1.097 | 1.093 | 0.367 | 0.468 |
| 2023-09 | 2.2 | 2.2 | 0.0 | 0.0 | 0.0 | 0.7 | 1.6 | 1.9 | 1.137 | 1.133 | 0.386 | 0.848 |
| 2023-10 | 76.3 | 5.7 | 0.0 | 0.0 | 70.5 | 2.0 | 72.8 | 4.3 | 17.918 | 1.343 | 0.460 | 17.100 |
| 2023-11 | 4.2 | 4.2 | 0.0 | 0.0 | 0.0 | 1.9 | 2.3 | 3.3 | 1.271 | 1.261 | 0.560 | 0.697 |
| 2023-12 | 4.0 | 3.8 | 0.0 | 0.0 | 0.1 | 1.9 | 1.3 | 3.5 | 1.136 | 1.096 | 0.542 | 0.373 |
| 2024-01 | 70.4 | 16.1 | 54.2 | 0.0 | 0.2 | 9.2 | 16.9 | 28.6 | 2.459 | 2.454 | 0.320 | 0.591 |
| 2024-02 | 44.9 | 9.7 | 35.1 | 0.0 | 0.1 | 9.6 | 6.7 | 21.3 | 2.109 | 2.106 | 0.452 | 0.316 |
| 2024-03 | 48.0 | 9.4 | 38.6 | 0.0 | 0.0 | 12.3 | 8.4 | 23.8 | 2.020 | 2.019 | 0.517 | 0.354 |
| 2024-04 | 31.5 | 8.3 | 23.2 | 0.0 | 0.1 | 9.2 | 4.8 | 19.4 | 1.621 | 1.618 | 0.474 | 0.247 |
| 2024-05 | 62.5 | 13.1 | 49.3 | 0.0 | 0.1 | 13.3 | 10.8 | 31.4 | 1.990 | 1.988 | 0.422 | 0.344 |
| 2024-06 | 134.7 | 20.2 | 114.5 | 0.0 | 0.1 | 18.6 | 16.2 | 52.6 | 2.564 | 2.562 | 0.353 | 0.309 |
| 2024-07 | 606.7 | 48.5 | 558.0 | 0.0 | 0.2 | 73.5 | 35.6 | 175.1 | 3.464 | 3.463 | 0.420 | 0.203 |
| 2024-08 | 613.3 | 91.0 | 521.9 | 0.0 | 0.4 | 88.9 | 106.7 | 203.9 | 3.008 | 3.006 | 0.436 | 0.523 |
| 2024-09 | 432.9 | 97.9 | 334.8 | 0.0 | 0.2 | 107.7 | 102.4 | 238.3 | 1.817 | 1.816 | 0.452 | 0.430 |
| 2024-10 | 2,630.9 | 170.9 | 2,440.5 | 0.0 | 19.4 | 564.0 | 161.8 | 1,139.6 | 2.309 | 2.292 | 0.495 | 0.142 |
| 2024-11 | 2,296.6 | 210.0 | 2,085.2 | 0.0 | 1.4 | 387.5 | 619.0 | 1,208.3 | 1.901 | 1.900 | 0.321 | 0.512 |
| 2024-12 | 684.3 | 262.4 | 420.5 | 0.0 | 1.4 | 348.6 | 205.2 | 771.1 | 0.887 | 0.886 | 0.452 | 0.266 |
| 2025-01 | 882.4 | 339.0 | 479.1 | 0.0 | 64.3 | 252.9 | 415.3 | 544.3 | 1.621 | 1.503 | 0.465 | 0.763 |
| 2025-02 | 557.6 | 226.1 | 327.2 | 0.0 | 4.3 | 207.7 | 193.2 | 341.7 | 1.632 | 1.619 | 0.608 | 0.565 |
| 2025-03 | 1,255.5 | 283.9 | 967.3 | 0.0 | 4.2 | 197.7 | 329.6 | 388.3 | 3.233 | 3.222 | 0.509 | 0.849 |
| 2025-04 | 3,500.4 | 260.7 | 542.9 | 0.0 | 2,696.8 | 192.7 | 2,960.2 | 423.2 | 8.271 | 1.899 | 0.455 | 6.995 |
| 2025-05 | 2,605.3 | 296.2 | 2,307.8 | 0.0 | 1.4 | 212.4 | 387.3 | 544.1 | 4.789 | 4.786 | 0.390 | 0.712 |
| 2025-06 | 1,383.3 | 390.3 | 991.9 | 0.0 | 1.1 | 219.9 | 388.0 | 587.8 | 2.353 | 2.352 | 0.374 | 0.660 |
| 2025-07 | 877.3 | 480.2 | 395.6 | 0.0 | 1.5 | 194.0 | 474.8 | 543.5 | 1.614 | 1.611 | 0.357 | 0.874 |
| 2025-08 | 1,076.6 | 465.7 | 608.5 | 0.0 | 2.4 | 230.7 | 433.8 | 485.7 | 2.217 | 2.212 | 0.475 | 0.893 |
| 2025-09 | 1,389.4 | 603.2 | 783.3 | 0.0 | 3.0 | 318.5 | 651.7 | 635.6 | 2.186 | 2.181 | 0.501 | 1.025 |
| 2025-10 | 2,643.7 | 1,210.2 | 1,419.5 | 0.0 | 14.0 | 578.7 | 1,161.3 | 1,313.2 | 2.013 | 2.003 | 0.441 | 0.884 |
| 2025-11 | 3,231.6 | 1,730.4 | 1,465.0 | 0.0 | 36.2 | 694.0 | 1,739.4 | 1,689.4 | 1.913 | 1.891 | 0.411 | 1.030 |
| 2025-12 | 3,996.4 | 2,158.3 | 1,780.4 | 0.0 | 57.8 | 762.3 | 2,227.6 | 2,173.2 | 1.839 | 1.812 | 0.351 | 1.025 |
| 2026-01 | 6,128.5 | 3,298.4 | 2,692.9 | 0.0 | 137.2 | 1,190.5 | 3,513.4 | 3,260.3 | 1.880 | 1.838 | 0.365 | 1.078 |
| 2026-02 | 6,129.9 | 3,564.2 | 2,498.2 | 0.0 | 67.5 | 1,212.2 | 3,612.4 | 3,363.3 | 1.823 | 1.803 | 0.360 | 1.074 |
| 2026-03 | 8,140.6 | 4,826.7 | 3,174.4 | 0.0 | 139.5 | 1,857.4 | 4,742.3 | 4,593.8 | 1.772 | 1.742 | 0.404 | 1.032 |
| 2026-04 | 6,639.6 | 3,806.9 | 2,608.8 | 61.7 | 162.2 | 1,544.4 | 3,846.3 | 3,739.3 | 1.776 | 1.716 | 0.413 | 1.029 |

Totals 2023-01 → 2026-04: splits **$58,248 M** (exch 24,943 · nr 29,719 · ada 62 · other 3,525), merges **$11,525 M** (exch 2,010 · nr 6,566), redemptions **$28,505 M**, fill notional **$28,577 M** → **mint/fill = 2.038**, exchange+adapter mint/fill = 1.913, merge/fill = 0.403, redeem/fill = 0.997. All-time (2022-11 → 2026-05) splits are $63,648 M, of which $10,003 M sit on 449k condition-months that are absent from the fill tape (conditions never traded on the CLOB or outside the tape's coverage).

Yearly:

| yr | split_usd_M | split_exch_M | split_nradapter_M | split_other_M | merge_usd_M | redeem_usd_M | fill_usd_M | mint_to_fill | exch_mint_to_fill | merge_to_fill | redeem_to_fill |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023 | 153.7 | 44.9 | 0.0 | 108.8 | 17.0 | 133.5 | 37.4 | 4.109 | 1.201 | 0.455 | 3.569 |
| 2024 | 7,656.7 | 957.4 | 6,675.8 | 23.5 | 1,642.2 | 1,294.7 | 3,913.5 | 1.957 | 1.951 | 0.420 | 0.331 |
| 2025 | 23,399.5 | 8,444.1 | 12,068.5 | 2,886.9 | 4,061.4 | 11,362.3 | 9,669.9 | 2.420 | 2.121 | 0.420 | 1.175 |
| 2026 | 27,038.6 | 15,496.2 | 10,974.4 | 506.3 | 5,804.6 | 15,714.5 | 14,956.7 | 1.808 | 1.770 | 0.388 | 1.051 |

Reading: (i) the 2023 ratios are dominated by a handful of 'other' stakeholders splitting directly on the CTF ($19.5 M in 2023-01 against $0.55 M of fills — early liquidity provisioning); exchange-driven minting alone was 1.0–1.7× fill notional in 2023. (ii) From 2024 on, exchange-driven minting is **1.6–3.5× the fill notional every month** (2024: 1.95; 2025: 2.12; 2026: 1.78). Since a mint of N pairs books only the *maker's* leg (≈(1−p)·N) into the archive's notional, a mint/fill ratio near 2 means that roughly all traded collateral is created by the exchange rather than transferred. (iii) Redemptions ≈ 1.0× fill notional over the window (0.33 in 2024 when the election money was still locked; 1.18 in 2025 as it was paid out).

### Q5.2 By class (2023-01 → 2026-04)

| cls | split_usd_M | split_exch_M | split_nr_M | split_other_M | merge_usd_M | redeem_usd_M | fill_usd_M | mint_to_fill | exch_mint_to_fill | merge_to_fill | redeem_to_fill |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Sports | 17,541.7 | 11,106.0 | 6,337.1 | 73.7 | 3,195.1 | 11,991.5 | 10,983.3 | 1.597 | 1.588 | 0.291 | 1.092 |
| Politics | 13,927.4 | 3,155.1 | 10,594.0 | 161.0 | 3,638.2 | 3,349.4 | 6,759.8 | 2.060 | 2.034 | 0.538 | 0.495 |
| Crypto | 5,402.7 | 4,258.5 | 1,017.1 | 123.5 | 1,447.7 | 3,451.9 | 3,887.6 | 1.390 | 1.357 | 0.372 | 0.888 |
| Price Action | 5,334.0 | 4,957.7 | 17.8 | 356.8 | 696.3 | 4,632.6 | 3,183.7 | 1.675 | 1.563 | 0.219 | 1.455 |
| Other | 3,811.8 | 539.6 | 3,246.8 | 22.8 | 1,516.5 | 663.1 | 1,393.4 | 2.736 | 2.717 | 1.088 | 0.476 |
| Finance | 2,161.0 | 369.4 | 1,786.0 | 4.9 | 509.2 | 603.4 | 1,024.0 | 2.110 | 2.105 | 0.497 | 0.589 |
| Culture | 2,175.0 | 390.7 | 1,773.6 | 10.4 | 368.6 | 600.3 | 886.8 | 2.452 | 2.441 | 0.416 | 0.677 |
| Sci-Tech | 1,267.7 | 160.8 | 1,076.6 | 29.1 | 150.0 | 454.2 | 458.8 | 2.763 | 2.697 | 0.327 | 0.990 |
| not in tape | 6,627.3 | 4.9 | 3,869.6 | 2,743.3 | 3.6 | 2,758.4 |  |  |  |  |  |

Mint/fill by class and year (NaN = class has no fills that year):

| cls | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| Crypto | 1.956 | 1.106 | 1.351 | 1.472 |
| Culture | 2.88 | 1.928 | 2.367 | 2.592 |
| Finance | 1.476 | 1.502 | 1.995 | 2.254 |
| Other | 1.019 | 0.712 | 3.629 | 2.8 |
| Politics | 2.686 | 2.598 | 1.968 | 1.598 |
| Price Action | 2.207 | 1.438 | 1.65 | 1.682 |
| Sci-Tech | 1.156 | 1.041 | 4.636 | 1.76 |
| Sports | 1.424 | 0.888 | 1.744 | 1.603 |
| not in tape |  |  |  |  |

Sports and Crypto are the least mint-intensive (1.60, 1.39); Politics, Culture, Sci-Tech and 'Other' the most (2.07–2.76) — long-dated markets where both sides are bought and held rather than flipped. Politics' merge/fill (0.54) and 'Other' (1.09) are far above Sports (0.29): position unwinds in political markets go through merges (both sides sold) much more than in sports.

### Q5.3 Fills-only identification (same-second complement rule) — monthly lower bound

Rule: a maker fill is flagged as a mint/merge leg when, for the same (taker, block_timestamp, condition), rows exist on **both** outcome tokens with opposite `taker_direction` (`n_grp_x`); its shares are counted on the taker-`SELL` side (= maker BUY = mint) or the taker-`BUY` side (= maker SELL = merge). Groups with both tokens but the same direction (1.7 % of rows) and mixed groups (≥3 (token,direction) combinations, 1.0 %) are reported separately and not counted.

| ym | n_rows | x_row_share | x_sh_share | x_sell_sh_share | x_buy_sh_share | samedir |
|---|---|---|---|---|---|---|
| 2023-01 | 3,812 | 14.2% | 27.6% | 18.2% | 9.4% |  |
| 2023-02 | 7,128 | 11.6% | 21.8% | 14.3% | 7.5% |  |
| 2023-03 | 24,576 | 27.2% | 32.6% | 19.1% | 13.5% | 0.0% |
| 2023-04 | 9,419 | 11.2% | 16.6% | 12.1% | 4.5% | 0.0% |
| 2023-05 | 12,502 | 20.2% | 32.7% | 18.3% | 14.4% |  |
| 2023-06 | 16,155 | 22.5% | 27.1% | 17.1% | 10.0% |  |
| 2023-07 | 13,505 | 19.3% | 24.7% | 15.8% | 8.8% |  |
| 2023-08 | 22,880 | 24.9% | 35.8% | 21.7% | 14.1% |  |
| 2023-09 | 12,024 | 16.9% | 25.8% | 12.8% | 13.0% | 0.0% |
| 2023-10 | 24,728 | 18.6% | 29.1% | 19.3% | 9.8% |  |
| 2023-11 | 24,693 | 20.1% | 26.8% | 16.8% | 10.0% |  |
| 2023-12 | 22,058 | 20.0% | 30.3% | 17.1% | 13.2% | 0.1% |
| 2024-01 | 69,039 | 24.6% | 36.8% | 20.6% | 16.2% | 0.0% |
| 2024-02 | 69,203 | 22.7% | 28.4% | 14.2% | 14.2% | 0.0% |
| 2024-03 | 75,215 | 21.6% | 30.6% | 15.6% | 15.0% |  |
| 2024-04 | 57,788 | 25.1% | 42.6% | 20.1% | 22.6% | 0.0% |
| 2024-05 | 155,839 | 16.0% | 32.5% | 15.8% | 16.8% |  |
| 2024-06 | 360,038 | 16.7% | 31.9% | 14.5% | 17.4% |  |
| 2024-07 | 979,712 | 18.3% | 30.2% | 14.2% | 15.9% | 0.0% |
| 2024-08 | 1,587,528 | 14.6% | 26.4% | 14.1% | 12.4% | 0.0% |
| 2024-09 | 1,874,073 | 13.8% | 29.6% | 15.2% | 14.3% | 0.0% |
| 2024-10 | 6,884,331 | 9.2% | 18.2% | 10.1% | 8.1% | 0.0% |
| 2024-11 | 7,710,737 | 11.5% | 23.8% | 13.2% | 10.6% | 0.1% |
| 2024-12 | 11,400,047 | 9.5% | 13.1% | 7.2% | 5.9% | 0.0% |
| 2025-01 | 7,213,770 | 16.7% | 22.0% | 11.8% | 10.2% | 0.0% |
| 2025-02 | 4,647,353 | 18.1% | 21.6% | 11.6% | 10.0% | 0.0% |
| 2025-03 | 4,622,542 | 17.1% | 20.8% | 12.5% | 8.3% | 0.0% |
| 2025-04 | 4,267,960 | 18.3% | 24.8% | 14.8% | 10.0% | 0.0% |
| 2025-05 | 5,044,379 | 22.6% | 35.9% | 20.8% | 15.0% | 0.0% |
| 2025-06 | 5,221,201 | 25.1% | 39.8% | 24.7% | 15.1% | 0.1% |
| 2025-07 | 6,219,310 | 18.9% | 36.4% | 22.8% | 13.6% | 0.2% |
| 2025-08 | 6,586,315 | 18.5% | 27.9% | 18.1% | 9.8% | 0.3% |
| 2025-09 | 7,032,338 | 18.3% | 28.1% | 17.8% | 10.3% | 0.5% |
| 2025-10 | 16,711,099 | 20.0% | 21.2% | 12.8% | 8.5% | 0.7% |
| 2025-11 | 26,781,671 | 20.3% | 27.4% | 17.8% | 9.5% | 0.7% |
| 2025-12 | 47,775,498 | 24.0% | 30.7% | 20.4% | 10.4% | 2.0% |
| 2026-01 | 84,690,981 | 28.8% | 32.0% | 20.8% | 11.2% | 1.4% |
| 2026-02 | 137,395,500 | 25.7% | 30.9% | 20.5% | 10.4% | 2.4% |
| 2026-03 | 204,997,163 | 22.9% | 30.3% | 20.4% | 10.0% | 2.3% |
| 2026-04 | 145,155,246 | 23.5% | 33.6% | 22.7% | 10.9% | 1.5% |

Window totals: 174,147,458 of 745,779,356 rows (**23.35 %**) are in cross-token groups; 21.29 B of 75.85 B shares (**28.07 %**), of which 13.46 B (17.74 %) on the mint-consistent side and 7.84 B (10.33 %) on the merge-consistent side. By class (row share): Culture 29.7 %, Finance 27.0 %, Price Action 25.8 %, Politics 25.7 %, Crypto 23.4 %, Sci-Tech 23.1 %, Other 19.4 %, Sports 13.9 %; binary 24.8 % vs negRisk 17.4 %.

### Q5.4 Reconciliation with CTF splits — the fills-only rule is a lower bound by a factor ≈2.7

* **Exact identity at the transaction level.** On the 5 markets with tx-level on-chain fills the CTF-Exchange split amount equals, to the cent, Σ shares of maker fills whose token is the complement of the taker's token *and* whose maker side is BUY: 149,334,390.77 = 149,334,390.77 (`0x6d0e…`), 21,374,085.72 = 21,374,085.72 (`0x8134…`), 6,720,630.10 = 6,720,630.10 (`0x42d8…`); merges equal the complement legs with maker SELL (21,264,770.69; 791,496.71; 2,085,029.21). So "minted collateral = complement-leg shares" is the right accounting, and the archive carries every leg.
* **True complement-leg share in those markets:** 54.2 % of maker fills / 63.4 % of shares (`0x6d0e…`, 137,451 maker fills), 65.8 % / 77.0 % (`0x8134…`), 51.8 % / 52.2 % (`0x42d8…`); two small negRisk markets 20.9 % / 0.9 % and 21.6 % / 0.2 %. Applying the same-second rule to those same on-chain maker fills flags only **37.3 % of rows / 35.2 % of shares** — the rule cannot see a taker order whose *every* leg is a complement leg (a single-token group), and those are the majority of mint matches.
* **Platform-wide (binary markets, all-time):** CTF-Exchange splits 24,938,050,278 share-pairs vs. 9,070,206,959 mint-consistent cross-group shares → **ratio 2.749**; merges 2,009,777,764 vs. 3,944,137,479 merge-consistent shares → 0.510 (merge-side groups also contain mint groups' normal legs). Per condition (199,602 binary conditions with ≥1,000 cross shares): median ratio 3.91, IQR 2.60–6.55, Pearson r = 0.943; only 0.8 % of conditions within ±10 %.
* **Implied true figure (binary):** mint legs = 24.94 B / 37.84 B = **65.9 %** of all maker-fill shares, merge legs 5.3 % → **≈71 % of binary share volume is share creation or destruction by the exchange; ≈29 % is a transfer of existing tokens.** Monthly, exchange mints alone are 45–78 % of binary shares (`exch_mint_share_of_shares` below). For negRisk the adapter's splits (27.22 B vs 38.01 B shares, 71.6 %) are an upper bound because the NegRiskAdapter is the CTF stakeholder for exchange matches, user splits and conversions alike; the NegRisk exchange never appears as a stakeholder.

| ym | sh_M | sh_x_sell_M | exch_split_M | ratio_split_exch_over_sh_x_sell | ratio_merge_exch_over_sh_x_buy | exch_mint_share_of_shares |
|---|---|---|---|---|---|---|
| 2023-01 | 1.3 | 0.2 | 0.8 | 3.409 | 0.299 | 62.1% |
| 2023-02 | 2.9 | 0.4 | 2.3 | 5.481 | 0.431 | 78.3% |
| 2023-03 | 11.1 | 2.1 | 6.2 | 2.933 | 0.909 | 56.0% |
| 2023-04 | 3.1 | 0.4 | 2.1 | 5.761 | 0.921 | 69.5% |
| 2023-05 | 7.4 | 1.4 | 4.2 | 3.056 | 0.733 | 56.0% |
| 2023-06 | 7.3 | 1.3 | 4.8 | 3.865 | 0.457 | 66.2% |
| 2023-07 | 6.1 | 1.0 | 4.0 | 4.124 | 0.550 | 65.2% |
| 2023-08 | 7.7 | 1.7 | 4.6 | 2.726 | 0.588 | 59.3% |
| 2023-09 | 3.5 | 0.4 | 2.2 | 4.870 | 0.652 | 62.2% |
| 2023-10 | 8.9 | 1.7 | 5.7 | 3.339 | 0.606 | 64.4% |
| 2023-11 | 7.0 | 1.2 | 4.2 | 3.569 | 0.778 | 60.0% |
| 2023-12 | 6.8 | 1.2 | 3.8 | 3.316 | 0.722 | 56.6% |
| 2024-01 | 28.9 | 8.3 | 16.1 | 1.926 | 0.503 | 55.6% |
| 2024-02 | 19.5 | 4.6 | 9.7 | 2.109 | 0.690 | 49.8% |
| 2024-03 | 18.9 | 4.3 | 9.4 | 2.216 | 0.957 | 49.9% |
| 2024-04 | 15.5 | 4.1 | 8.3 | 2.005 | 0.674 | 53.3% |
| 2024-05 | 26.2 | 7.4 | 13.1 | 1.770 | 0.661 | 50.1% |
| 2024-06 | 37.0 | 11.4 | 20.2 | 1.767 | 0.525 | 54.5% |
| 2024-07 | 101.7 | 27.4 | 48.5 | 1.772 | 0.685 | 47.7% |
| 2024-08 | 162.0 | 44.8 | 91.0 | 2.029 | 0.512 | 56.2% |
| 2024-09 | 167.8 | 45.9 | 97.9 | 2.133 | 0.554 | 58.3% |
| 2024-10 | 303.9 | 81.3 | 170.9 | 2.103 | 0.661 | 56.2% |
| 2024-11 | 436.2 | 111.8 | 210.0 | 1.878 | 0.702 | 48.1% |
| 2024-12 | 587.1 | 154.9 | 262.4 | 1.693 | 0.626 | 44.7% |
| 2025-01 | 637.7 | 194.3 | 339.0 | 1.745 | 0.479 | 53.2% |
| 2025-02 | 426.9 | 109.5 | 226.1 | 2.065 | 0.704 | 53.0% |
| 2025-03 | 522.8 | 119.0 | 283.9 | 2.385 | 0.854 | 54.3% |
| 2025-04 | 477.1 | 101.1 | 260.7 | 2.579 | 0.862 | 54.6% |
| 2025-05 | 503.8 | 112.9 | 296.1 | 2.624 | 0.760 | 58.8% |
| 2025-06 | 702.1 | 192.6 | 390.3 | 2.027 | 0.597 | 55.6% |
| 2025-07 | 824.1 | 227.7 | 480.2 | 2.109 | 0.518 | 58.3% |
| 2025-08 | 702.3 | 144.0 | 465.7 | 3.233 | 0.550 | 66.3% |
| 2025-09 | 828.8 | 168.0 | 600.3 | 3.572 | 0.511 | 72.4% |
| 2025-10 | 1,841.0 | 343.6 | 1,208.6 | 3.517 | 0.664 | 65.6% |
| 2025-11 | 2,571.7 | 541.7 | 1,730.3 | 3.194 | 0.541 | 67.3% |
| 2025-12 | 3,254.6 | 782.3 | 2,158.3 | 2.759 | 0.494 | 66.3% |
| 2026-01 | 4,831.0 | 1,144.5 | 3,298.4 | 2.882 | 0.428 | 68.3% |
| 2026-02 | 5,187.3 | 1,238.5 | 3,564.1 | 2.878 | 0.471 | 68.7% |
| 2026-03 | 6,928.4 | 1,671.3 | 4,826.7 | 2.888 | 0.439 | 69.7% |
| 2026-04 | 5,625.3 | 1,460.0 | 3,806.9 | 2.607 | 0.434 | 67.7% |

**Verdict Q5: publishable** — with the CTF split/merge amounts as the primary measure (monthly, by class, 40 months, exact tx-level identity), and the tape-only same-second rule reported as a lower bound with a measured 2.7× under-identification. Not supported: separating exchange-driven from user-driven minting inside negRisk.

## Q6a — Resolution-anchored convergence platform-wide

Method: winning token = the `asset_id` whose `outcome_label` equals `winning_outcome_label`; for each horizon the last fill of that token at or before `resolved_at − h`; error = |1 − price|. Sample: `resolution_status='resolved'` **and** non-NULL `resolved_at`. **Exclusions:** of 843,335 resolved markets, **530,309 (62.9 %) have NULL `resolved_at` and were excluded** — all 158,910 negRisk markets and 371,399 binary ones; of the 313,026 usable markets, 50,414 have no fill on the winning token (winner never traded / label mismatch) and 0 have two 'winning' tokens, leaving **262,612 markets** (Price Action 146,446 · Sports 62,945 · Crypto 47,113 · Finance 2,666 · Politics 2,044 · Other 623 · Culture 463 · Sci-Tech 312); 26,984 (10.3 %) resolved **before** `close_at` ('early'). `n_with_fill` is the number of markets that have any fill at or before the horizon (a 15-minute market has none 1 h before); statistics are over those markets only.

### Q6a.1 All usable markets

| horizon | n_markets | n_with_fill | med | mean | p90 | frac_wrong_side | frac_within_5c |
|---|---|---|---|---|---|---|---|
| d14 | 262612 | 2660 | 0.130 | 0.257 | 0.730 | 0.2% | 0.3% |
| d7 | 262612 | 4457 | 0.190 | 0.288 | 0.742 | 0.4% | 0.5% |
| d3 | 262612 | 10266 | 0.200 | 0.296 | 0.740 | 0.9% | 1.1% |
| d1 | 262612 | 22417 | 0.380 | 0.352 | 0.689 | 2.8% | 1.8% |
| h6 | 262612 | 64213 | 0.500 | 0.394 | 0.590 | 10.4% | 3.9% |
| h1 | 262612 | 122267 | 0.001 | 0.195 | 0.510 | 9.8% | 27.7% |
| h0 | 262612 | 262379 | 0.010 | 0.054 | 0.110 | 3.9% | 87.9% |

### Q6a.2 By class

| grp | horizon | n_with_fill | med | mean | p90 | frac_wrong_side | frac_within_5c |
|---|---|---|---|---|---|---|---|
| Crypto | d14 | 327 | 0.060 | 0.176 | 0.550 | 0.1% | 0.3% |
| Crypto | d7 | 786 | 0.112 | 0.240 | 0.690 | 0.3% | 0.6% |
| Crypto | d3 | 2494 | 0.041 | 0.139 | 0.470 | 0.5% | 2.8% |
| Crypto | d1 | 4260 | 0.030 | 0.193 | 0.510 | 2.0% | 4.9% |
| Crypto | h6 | 10110 | 0.450 | 0.276 | 0.510 | 7.4% | 9.1% |
| Crypto | h1 | 24740 | 0.001 | 0.155 | 0.510 | 8.8% | 35.7% |
| Crypto | h0 | 47068 | 0.010 | 0.048 | 0.059 | 3.6% | 89.5% |
| Culture | d14 | 312 | 0.164 | 0.248 | 0.630 | 10.6% | 14.5% |
| Culture | d7 | 332 | 0.146 | 0.235 | 0.629 | 11.0% | 19.0% |
| Culture | d3 | 390 | 0.145 | 0.237 | 0.650 | 13.2% | 24.0% |
| Culture | d1 | 427 | 0.140 | 0.237 | 0.660 | 14.5% | 29.4% |
| Culture | h6 | 452 | 0.140 | 0.237 | 0.650 | 16.0% | 33.3% |
| Culture | h1 | 462 | 0.080 | 0.200 | 0.609 | 13.4% | 42.8% |
| Culture | h0 | 463 | 0.080 | 0.197 | 0.600 | 13.2% | 43.4% |
| Finance | d14 | 444 | 0.135 | 0.249 | 0.740 | 2.7% | 5.4% |
| Finance | d7 | 636 | 0.170 | 0.270 | 0.720 | 4.8% | 6.5% |
| Finance | d3 | 1244 | 0.160 | 0.269 | 0.720 | 9.6% | 11.9% |
| Finance | d1 | 1916 | 0.120 | 0.253 | 0.680 | 14.5% | 24.7% |
| Finance | h6 | 2439 | 0.050 | 0.169 | 0.560 | 10.8% | 45.8% |
| Finance | h1 | 2650 | 0.002 | 0.079 | 0.280 | 5.1% | 74.5% |
| Finance | h0 | 2665 | 0.002 | 0.077 | 0.263 | 4.9% | 75.7% |
| Other | d14 | 198 | 0.058 | 0.182 | 0.532 | 4.0% | 14.9% |
| Other | d7 | 253 | 0.071 | 0.193 | 0.530 | 5.0% | 17.7% |
| Other | d3 | 358 | 0.100 | 0.215 | 0.580 | 8.2% | 22.5% |
| Other | d1 | 453 | 0.160 | 0.259 | 0.650 | 14.9% | 26.5% |
| Other | h6 | 573 | 0.090 | 0.218 | 0.630 | 14.1% | 39.3% |
| Other | h1 | 621 | 0.004 | 0.107 | 0.400 | 7.4% | 70.8% |
| Other | h0 | 623 | 0.002 | 0.101 | 0.380 | 6.9% | 72.6% |
| Politics | d14 | 773 | 0.110 | 0.234 | 0.688 | 6.6% | 13.1% |
| Politics | d7 | 1040 | 0.120 | 0.235 | 0.660 | 8.2% | 17.7% |
| Politics | d3 | 1326 | 0.120 | 0.240 | 0.696 | 11.6% | 24.0% |
| Politics | d1 | 1623 | 0.110 | 0.233 | 0.660 | 14.4% | 31.8% |
| Politics | h6 | 1907 | 0.099 | 0.225 | 0.660 | 16.9% | 40.1% |
| Politics | h1 | 2040 | 0.011 | 0.143 | 0.520 | 10.5% | 63.5% |
| Politics | h0 | 2043 | 0.010 | 0.139 | 0.518 | 10.4% | 64.5% |
| Price Action | d14 | 3 | 0.400 | 0.415 | 0.584 | 0.0% | 0.0% |
| Price Action | d7 | 22 | 0.219 | 0.355 | 0.779 | 0.0% | 0.0% |
| Price Action | d3 | 88 | 0.080 | 0.225 | 0.703 | 0.0% | 0.0% |
| Price Action | d1 | 1048 | 0.510 | 0.472 | 0.510 | 0.5% | 0.0% |
| Price Action | h6 | 16028 | 0.510 | 0.504 | 0.510 | 7.5% | 0.1% |
| Price Action | h1 | 30187 | 0.510 | 0.493 | 0.510 | 12.0% | 0.3% |
| Price Action | h0 | 146296 | 0.010 | 0.050 | 0.080 | 3.2% | 89.0% |
| Sci-Tech | d14 | 159 | 0.060 | 0.176 | 0.520 | 6.1% | 22.4% |
| Sci-Tech | d7 | 174 | 0.050 | 0.174 | 0.544 | 7.1% | 26.6% |
| Sci-Tech | d3 | 196 | 0.050 | 0.192 | 0.675 | 9.0% | 31.4% |
| Sci-Tech | d1 | 235 | 0.070 | 0.213 | 0.694 | 11.5% | 34.9% |
| Sci-Tech | h6 | 282 | 0.045 | 0.192 | 0.667 | 11.9% | 46.5% |
| Sci-Tech | h1 | 298 | 0.010 | 0.123 | 0.490 | 8.3% | 65.4% |
| Sci-Tech | h0 | 312 | 0.010 | 0.113 | 0.478 | 8.0% | 71.5% |
| Sports | d14 | 444 | 0.400 | 0.430 | 0.937 | 0.3% | 0.1% |
| Sports | d7 | 1214 | 0.420 | 0.422 | 0.890 | 0.8% | 0.3% |
| Sports | d3 | 4170 | 0.440 | 0.433 | 0.860 | 2.6% | 0.5% |
| Sports | d1 | 12455 | 0.460 | 0.436 | 0.740 | 7.6% | 1.0% |
| Sports | h6 | 32422 | 0.460 | 0.411 | 0.660 | 18.9% | 5.1% |
| Sports | h1 | 61269 | 0.001 | 0.073 | 0.370 | 5.8% | 81.4% |
| Sports | h0 | 62909 | 0.001 | 0.063 | 0.270 | 5.2% | 86.0% |

### Q6a.3 Early (resolved before `close_at`) vs. at/after `close_at`

| grp | horizon | n_markets | n_with_fill | med | mean | p90 | frac_wrong_side | frac_within_5c |
|---|---|---|---|---|---|---|---|---|
| at/after close_at | d14 | 235628 | 1713 | 0.100 | 0.236 | 0.706 | 0.1% | 0.3% |
| at/after close_at | d7 | 235628 | 3162 | 0.180 | 0.282 | 0.730 | 0.3% | 0.4% |
| at/after close_at | d3 | 235628 | 7815 | 0.170 | 0.268 | 0.690 | 0.7% | 1.0% |
| at/after close_at | d1 | 235628 | 16732 | 0.340 | 0.329 | 0.650 | 2.3% | 1.7% |
| at/after close_at | h6 | 235628 | 52055 | 0.500 | 0.390 | 0.550 | 9.7% | 3.8% |
| at/after close_at | h1 | 235628 | 96136 | 0.020 | 0.233 | 0.510 | 10.4% | 21.1% |
| at/after close_at | h0 | 235628 | 235419 | 0.010 | 0.054 | 0.110 | 3.8% | 87.8% |
| early | d14 | 26984 | 947 | 0.190 | 0.294 | 0.780 | 0.8% | 1.0% |
| early | d7 | 26984 | 1295 | 0.210 | 0.302 | 0.786 | 1.1% | 1.3% |
| early | d3 | 26984 | 2451 | 0.370 | 0.383 | 0.860 | 3.1% | 1.7% |
| early | d1 | 26984 | 5685 | 0.430 | 0.417 | 0.770 | 7.7% | 2.3% |
| early | h6 | 26984 | 12158 | 0.440 | 0.412 | 0.700 | 16.3% | 4.9% |
| early | h1 | 26984 | 26131 | 0.001 | 0.058 | 0.200 | 4.7% | 84.7% |
| early | h0 | 26984 | 26960 | 0.001 | 0.053 | 0.149 | 4.4% | 88.6% |

### Q6a.4 By market notional

| grp | horizon | n_markets | n_with_fill | med | mean | p90 | frac_wrong_side | frac_within_5c |
|---|---|---|---|---|---|---|---|---|
| 10k-100k | d14 | 52664 | 642 | 0.060 | 0.189 | 0.598 | 0.2% | 0.5% |
| 10k-100k | d7 | 52664 | 1037 | 0.110 | 0.230 | 0.644 | 0.3% | 0.7% |
| 10k-100k | d3 | 52664 | 2380 | 0.150 | 0.253 | 0.660 | 0.9% | 1.6% |
| 10k-100k | d1 | 52664 | 6101 | 0.430 | 0.359 | 0.630 | 4.2% | 2.4% |
| 10k-100k | h6 | 52664 | 20020 | 0.500 | 0.432 | 0.530 | 17.8% | 4.0% |
| 10k-100k | h1 | 52664 | 31354 | 0.500 | 0.316 | 0.510 | 19.9% | 21.9% |
| 10k-100k | h0 | 52664 | 52663 | 0.009 | 0.008 | 0.010 | 0.2% | 99.4% |
| <10k | d14 | 201196 | 1707 | 0.190 | 0.299 | 0.790 | 0.2% | 0.2% |
| <10k | d7 | 201196 | 2812 | 0.220 | 0.316 | 0.790 | 0.4% | 0.3% |
| <10k | d3 | 201196 | 6409 | 0.210 | 0.309 | 0.800 | 0.8% | 0.8% |
| <10k | d1 | 201196 | 13397 | 0.330 | 0.345 | 0.740 | 2.1% | 1.5% |
| <10k | h6 | 201196 | 38744 | 0.470 | 0.373 | 0.620 | 7.7% | 3.6% |
| <10k | h1 | 201196 | 83412 | 0.001 | 0.145 | 0.510 | 6.7% | 28.5% |
| <10k | h0 | 201196 | 200964 | 0.010 | 0.068 | 0.240 | 5.0% | 84.3% |
| >=100k | d14 | 8752 | 311 | 0.039 | 0.165 | 0.540 | 0.4% | 1.9% |
| >=100k | d7 | 8752 | 608 | 0.160 | 0.256 | 0.640 | 1.5% | 2.5% |
| >=100k | d3 | 8752 | 1477 | 0.280 | 0.307 | 0.660 | 4.4% | 4.5% |
| >=100k | d1 | 8752 | 2919 | 0.440 | 0.367 | 0.620 | 11.7% | 6.3% |
| >=100k | h6 | 8752 | 5449 | 0.500 | 0.407 | 0.570 | 26.8% | 8.5% |
| >=100k | h1 | 8752 | 7501 | 0.010 | 0.248 | 0.510 | 21.6% | 43.4% |
| >=100k | h0 | 8752 | 8752 | 0.001 | 0.005 | 0.010 | 0.1% | 99.5% |

Reading: at `resolved_at` itself (h0) the winner's last price is within 5 cents of 1 in 87.9 % of markets (median |1−p| = 0.010, p90 = 0.11), but 3.9 % of markets' last trade is on the wrong side (|1−p| > 0.5). One hour before resolution the distribution is bimodal: median 0.001 but mean 0.195, p90 0.51, 9.8 % wrong side. The bimodality is structural, not noise: Sports resolves minutes after the game (h1 median 0.001, h6 median 0.46 = in-play), Price Action markets (crypto up/down) resolve at a clock time and are coin-flips until the last minutes (h1 median 0.51, h0 0.010), while Finance (h1 median 0.002, p90 0.28) and Politics (h1 0.011, p90 0.52, 10.5 % wrong side even 1 h before) keep genuine uncertainty to the end. 'Early' resolutions converge *better* at h1 (median 0.001, p90 0.20, 4.7 % wrong side) than deadline resolutions (0.020, 0.51, 10.4 %): early resolution happens because the outcome became known. Large markets (≥$100k): h0 median 0.001, p90 0.010, 99.5 % within 5 cents; but 21.6 % wrong side at h1 — those are in-play sports and price-action markets.

### Q6a.5 Consistency check on the 100-market corpus (`data/snapshots/20260829/corpus_condition_ids.txt`)

97 of 100 conditions are in the archive (6,087,176 fills). Only **1** carries an archive `resolved_at`; the other anchors are the snapshot's Gamma `closed_time` (the project's own convergence anchor) and the CTF `ConditionResolution` block converted with the block→time map (`res_t_hat`). Snapshot `closed_time` − CTF time: median −262 s (p10 −97,428 s: for a few markets Gamma closed the book long before the on-chain payout report).

| anchor | horizon | n_markets | n_with_fill | med | mean | p90 |
|---|---|---|---|---|---|---|
| resolved_at | d14 | 1 | 1 | 0.0160 | 0.0160 | 0.0160 |
| resolved_at | d7 | 1 | 1 | 0.0070 | 0.0070 | 0.0070 |
| resolved_at | d3 | 1 | 1 | 0.0020 | 0.0020 | 0.0020 |
| resolved_at | d1 | 1 | 1 | 0.0020 | 0.0020 | 0.0020 |
| resolved_at | h6 | 1 | 1 | 0.0010 | 0.0010 | 0.0010 |
| resolved_at | h1 | 1 | 1 | 0.0010 | 0.0010 | 0.0010 |
| resolved_at | h0 | 1 | 1 | 0.0010 | 0.0010 | 0.0010 |
| closed_time | d14 | 97 | 86 | 0.0155 | 0.1584 | 0.5200 |
| closed_time | d7 | 97 | 91 | 0.0070 | 0.1374 | 0.4700 |
| closed_time | d3 | 97 | 96 | 0.0030 | 0.0764 | 0.1550 |
| closed_time | d1 | 97 | 97 | 0.0020 | 0.0551 | 0.1314 |
| closed_time | h6 | 97 | 97 | 0.0010 | 0.0514 | 0.0600 |
| closed_time | h1 | 97 | 97 | 0.0010 | 0.0152 | 0.0030 |
| closed_time | h0 | 97 | 97 | 0.0010 | 0.0150 | 0.0024 |
| res_t_hat | d14 | 97 | 87 | 0.0160 | 0.1615 | 0.5120 |
| res_t_hat | d7 | 97 | 91 | 0.0070 | 0.1403 | 0.4700 |
| res_t_hat | d3 | 97 | 96 | 0.0030 | 0.0772 | 0.1500 |
| res_t_hat | d1 | 97 | 97 | 0.0020 | 0.0561 | 0.1446 |
| res_t_hat | h6 | 97 | 97 | 0.0010 | 0.0515 | 0.0618 |
| res_t_hat | h1 | 97 | 97 | 0.0010 | 0.0160 | 0.0030 |
| res_t_hat | h0 | 97 | 97 | 0.0010 | 0.0150 | 0.0020 |

**h1 median = 0.001 for all 97 markets with either anchor — the expected ≈0.001 is reproduced**, and the CTF-block anchor gives the same numbers as Gamma's `closed_time` at every horizon (h1 0.001/0.001, d1 0.002/0.002, d7 0.007/0.007), which validates the block→time map as a resolution anchor to well within an hour.

**Verdict Q6a: needs more.** The numbers are exact for the sample the archive allows, but that sample is 37 % of resolved binary markets, 0 % of negRisk, and 99 % 2026 resolutions — it is a 2026 short-horizon (Price Action + Sports) sample, not the platform's history. The corpus check passes. The fix is in hand: the CTF resolution block gives a resolution time for every one of the 841,272 resolved conditions (validated median +216 s vs Gamma), but re-anchoring the tape to it needs one more pass over the 16 GB tape (not run here to respect the memory/time constraints).

## Q6b — Maker concentration platform-wide

Method: from `struct_maker_month` (per month × maker: fills, Σ `usdc_amount`) — distinct makers and takers, HHI = Σ sᵢ² of maker notional shares, top-10 share of maker notional, share of *fills* whose maker is in that month's top-10, `eff_n` = 1/HHI, persistence = fraction of the month's top-10 makers that were top-10 in the previous month. 'Maker volume' is the notional of maker-fill rows (all rows); a maker appearing on the complementary leg of a mint counts on that token.

| ym | n_makers | n_takers | n_fills | hhi | eff_n | top1_share | top10_share | top50_share | top10_fill_share | persistence |
|---|---|---|---|---|---|---|---|---|---|---|
| 2023-01 | 142 | 391 | 3,812 | 0.0733 | 14 | 19.4% | 69.3% | 97.4% | 46.7% |  |
| 2023-02 | 205 | 585 | 7,128 | 0.0761 | 13 | 18.9% | 68.5% | 96.8% | 46.6% | 0.5 |
| 2023-03 | 679 | 2,054 | 24,576 | 0.0290 | 34 | 9.1% | 44.7% | 79.9% | 18.6% | 0.4 |
| 2023-04 | 297 | 768 | 9,419 | 0.0470 | 21 | 12.1% | 60.6% | 93.6% | 38.6% | 0.3 |
| 2023-05 | 410 | 1,085 | 12,502 | 0.0421 | 24 | 11.4% | 53.9% | 89.2% | 35.9% | 0.5 |
| 2023-06 | 604 | 1,665 | 16,155 | 0.0460 | 22 | 10.9% | 58.8% | 88.7% | 35.8% | 0.6 |
| 2023-07 | 465 | 1,160 | 13,505 | 0.0592 | 17 | 14.5% | 63.6% | 92.3% | 31.7% | 0.7 |
| 2023-08 | 617 | 1,986 | 22,880 | 0.0426 | 23 | 10.5% | 54.9% | 87.0% | 37.7% | 0.7 |
| 2023-09 | 418 | 1,163 | 12,024 | 0.0431 | 23 | 11.5% | 58.3% | 89.1% | 34.2% | 0.7 |
| 2023-10 | 550 | 1,364 | 24,728 | 0.0566 | 18 | 17.2% | 59.5% | 87.4% | 43.3% | 0.8 |
| 2023-11 | 663 | 1,739 | 24,693 | 0.0529 | 19 | 16.9% | 55.1% | 83.2% | 45.9% | 0.9 |
| 2023-12 | 578 | 1,504 | 22,058 | 0.0705 | 14 | 17.8% | 62.1% | 87.7% | 46.3% | 0.7 |
| 2024-01 | 1,081 | 3,977 | 69,039 | 0.0405 | 25 | 11.2% | 54.6% | 86.8% | 40.7% | 0.6 |
| 2024-02 | 880 | 3,251 | 69,203 | 0.0697 | 14 | 19.8% | 64.1% | 91.1% | 49.4% | 0.6 |
| 2024-03 | 850 | 3,041 | 75,215 | 0.0518 | 19 | 13.9% | 60.5% | 92.4% | 42.8% | 0.8 |
| 2024-04 | 794 | 2,562 | 57,788 | 0.0573 | 17 | 16.5% | 62.7% | 92.1% | 47.6% | 0.8 |
| 2024-05 | 1,752 | 13,363 | 155,839 | 0.0379 | 26 | 11.8% | 51.9% | 84.8% | 41.8% | 0.7 |
| 2024-06 | 4,555 | 28,758 | 360,038 | 0.0324 | 31 | 9.7% | 47.8% | 76.1% | 33.1% | 0.8 |
| 2024-07 | 14,470 | 42,783 | 979,712 | 0.0114 | 88 | 5.9% | 26.8% | 51.8% | 16.6% | 0.6 |
| 2024-08 | 18,949 | 61,858 | 1,587,528 | 0.0109 | 92 | 6.3% | 24.6% | 54.3% | 11.6% | 0.4 |
| 2024-09 | 22,676 | 87,476 | 1,874,073 | 0.0088 | 113 | 4.2% | 23.0% | 51.3% | 11.9% | 0.6 |
| 2024-10 | 75,869 | 230,797 | 6,884,331 | 0.0096 | 104 | 5.4% | 24.2% | 44.0% | 13.6% | 0.2 |
| 2024-11 | 83,045 | 296,565 | 7,710,737 | 0.0045 | 221 | 4.1% | 16.0% | 30.3% | 6.0% | 0.3 |
| 2024-12 | 107,724 | 350,298 | 11,400,047 | 0.0020 | 506 | 1.5% | 8.5% | 26.3% | 4.4% | 0.1 |
| 2025-01 | 115,118 | 454,221 | 7,213,770 | 0.0044 | 225 | 3.1% | 14.8% | 34.9% | 3.8% | 0.3 |
| 2025-02 | 107,702 | 411,832 | 4,647,353 | 0.0034 | 297 | 1.8% | 10.8% | 34.7% | 4.5% | 0.1 |
| 2025-03 | 130,086 | 371,255 | 4,622,542 | 0.0043 | 230 | 2.0% | 14.7% | 38.8% | 4.7% | 0.5 |
| 2025-04 | 105,345 | 320,102 | 4,267,960 | 0.0039 | 256 | 1.9% | 13.3% | 35.7% | 6.4% | 0.4 |
| 2025-05 | 79,092 | 269,533 | 5,044,379 | 0.0040 | 250 | 2.0% | 14.5% | 35.5% | 5.7% | 0.7 |
| 2025-06 | 70,262 | 229,903 | 5,221,201 | 0.0046 | 218 | 2.2% | 14.9% | 38.9% | 4.4% | 0.5 |
| 2025-07 | 88,373 | 275,414 | 6,219,310 | 0.0047 | 212 | 2.1% | 14.0% | 41.1% | 3.9% | 0.2 |
| 2025-08 | 72,921 | 219,224 | 6,586,315 | 0.0071 | 141 | 3.3% | 21.2% | 45.4% | 4.4% | 0.3 |
| 2025-09 | 63,733 | 226,579 | 7,032,338 | 0.0056 | 180 | 2.5% | 17.2% | 42.6% | 4.7% | 0.5 |
| 2025-10 | 133,187 | 461,488 | 16,711,099 | 0.0023 | 435 | 1.7% | 9.9% | 27.4% | 4.3% | 0.3 |
| 2025-11 | 180,536 | 479,276 | 26,781,671 | 0.0024 | 422 | 1.4% | 10.7% | 27.7% | 1.6% | 0.3 |
| 2025-12 | 182,569 | 490,564 | 47,775,498 | 0.0023 | 431 | 1.5% | 10.3% | 27.5% | 8.0% | 0.6 |
| 2026-01 | 237,913 | 606,131 | 84,690,981 | 0.0025 | 394 | 2.5% | 10.6% | 27.3% | 1.4% | 0.7 |
| 2026-02 | 259,598 | 622,812 | 137,395,500 | 0.0018 | 560 | 1.3% | 8.7% | 23.8% | 4.7% | 0.4 |
| 2026-03 | 345,959 | 733,984 | 204,997,163 | 0.0019 | 521 | 1.8% | 9.6% | 23.6% | 1.1% | 0.4 |
| 2026-04 | 254,046 | 623,638 | 145,155,246 | 0.0024 | 420 | 1.9% | 11.5% | 25.8% | 1.1% | 0.6 |

Reading: the maker side went from an oligopoly — 142 makers, HHI 0.073, top-10 = 69.3 % of maker notional and 46.7 % of fills in 2023-01; 14 'effective' makers — to a long tail: 107,724 makers and HHI 0.0020 by 2024-12 and 254k–346k makers, HHI 0.0018–0.0025, top-10 share 8.7–11.5 %, top-1 share 1.3–2.5 % in 2026. The top-10 makers' share of *fills* is far below their share of notional (1.1–4.7 % vs 8.7–11.5 % in 2026; 46.7 % vs 69.3 % in 2023-01): large makers trade size, not frequency. Persistence of the top-10 collapsed from 0.7–0.9 (2023 H2) to 0.1–0.7 (2025–26, mean 0.40): the identity of the top-10 changes by more than half each month. Makers/takers ratio: 0.36 (2023-01) → 0.47 (2026-03).

### Q6b.1 2026 by class, monthly

| ym | cls | n_makers | n_takers | hhi | top1_share | top10_share | top10_fill_share | persistence |
|---|---|---|---|---|---|---|---|---|
| 2026-01 | Crypto | 118,427 | 266,618 | 0.0044 | 3.3% | 16.5% | 18.3% |  |
| 2026-02 | Crypto | 120,730 | 294,815 | 0.0044 | 3.1% | 15.9% | 14.9% | 0.4 |
| 2026-03 | Crypto | 140,570 | 349,144 | 0.0038 | 2.7% | 14.6% | 10.7% | 0.3 |
| 2026-04 | Crypto | 81,203 | 248,602 | 0.0050 | 3.9% | 16.0% | 6.3% | 0.3 |
| 2026-01 | Culture | 21,275 | 84,353 | 0.0078 | 4.2% | 20.6% | 3.1% |  |
| 2026-02 | Culture | 26,816 | 91,373 | 0.0054 | 2.7% | 17.7% | 3.1% | 0.4 |
| 2026-03 | Culture | 49,293 | 129,486 | 0.0041 | 2.7% | 15.7% | 5.9% | 0.5 |
| 2026-04 | Culture | 33,168 | 102,093 | 0.0050 | 3.4% | 17.3% | 7.6% | 0.5 |
| 2026-01 | Finance | 41,866 | 150,547 | 0.0066 | 3.5% | 20.6% | 3.5% |  |
| 2026-02 | Finance | 40,086 | 121,964 | 0.0055 | 3.8% | 17.2% | 4.2% | 0.5 |
| 2026-03 | Finance | 56,375 | 155,231 | 0.0109 | 6.7% | 24.6% | 1.4% | 0.3 |
| 2026-04 | Finance | 25,940 | 77,434 | 0.0093 | 8.1% | 19.2% | 3.9% | 0.2 |
| 2026-01 | Other | 34,228 | 129,786 | 0.0046 | 2.4% | 15.6% | 1.2% |  |
| 2026-02 | Other | 41,708 | 131,537 | 0.0017 | 1.3% | 9.1% | 3.3% | 0.1 |
| 2026-03 | Other | 77,009 | 175,761 | 0.0025 | 1.8% | 11.6% | 0.4% | 0.0 |
| 2026-04 | Other | 61,637 | 144,457 | 0.0031 | 3.6% | 12.1% | 2.6% | 0.2 |
| 2026-01 | Politics | 58,082 | 232,220 | 0.0060 | 5.0% | 17.7% | 2.3% |  |
| 2026-02 | Politics | 63,830 | 219,087 | 0.0061 | 4.2% | 18.5% | 2.4% | 0.6 |
| 2026-03 | Politics | 116,274 | 305,618 | 0.0060 | 4.2% | 19.7% | 1.5% | 0.3 |
| 2026-04 | Politics | 92,449 | 244,116 | 0.0140 | 7.5% | 30.2% | 1.6% | 0.4 |
| 2026-01 | Price Action | 49,651 | 88,924 | 0.0076 | 3.3% | 23.2% | 22.9% |  |
| 2026-02 | Price Action | 70,598 | 159,889 | 0.0073 | 3.9% | 22.1% | 12.4% | 0.5 |
| 2026-03 | Price Action | 85,701 | 198,315 | 0.0069 | 5.6% | 18.1% | 14.3% | 0.3 |
| 2026-04 | Price Action | 60,502 | 153,667 | 0.0045 | 3.4% | 15.3% | 7.2% | 0.1 |
| 2026-01 | Sci-Tech | 19,563 | 58,771 | 0.0067 | 4.5% | 20.8% | 1.7% |  |
| 2026-02 | Sci-Tech | 19,132 | 56,764 | 0.0084 | 5.3% | 22.9% | 1.6% | 0.7 |
| 2026-03 | Sci-Tech | 39,661 | 93,280 | 0.0038 | 1.7% | 13.9% | 5.6% | 0.3 |
| 2026-04 | Sci-Tech | 37,018 | 109,482 | 0.0050 | 3.1% | 17.4% | 3.6% | 0.5 |
| 2026-01 | Sports | 77,470 | 230,199 | 0.0087 | 5.5% | 22.3% | 10.8% |  |
| 2026-02 | Sports | 87,201 | 250,951 | 0.0053 | 3.0% | 18.2% | 8.5% | 0.8 |
| 2026-03 | Sports | 156,237 | 341,705 | 0.0060 | 4.2% | 19.2% | 10.3% | 0.5 |
| 2026-04 | Sports | 116,860 | 290,078 | 0.0057 | 4.0% | 18.3% | 10.3% | 0.8 |

### Q6b.2 2026 (Jan–Apr pooled) by class

| cls | n_makers | hhi | top10_share | top10_fill_share |
|---|---|---|---|---|
| Sports | 298,863 | 0.0044 | 16.2% | 10.4% |
| Price Action | 193,721 | 0.0035 | 13.5% | 10.8% |
| Politics | 223,407 | 0.0058 | 19.6% | 1.8% |
| Crypto | 310,723 | 0.0023 | 10.7% | 5.2% |
| Finance | 119,060 | 0.0052 | 17.1% | 2.5% |
| Other | 151,061 | 0.0015 | 7.9% | 0.6% |
| Culture | 98,924 | 0.0034 | 13.4% | 2.2% |
| Sci-Tech | 89,247 | 0.0033 | 13.4% | 0.9% |

Politics is the most concentrated class by notional (pooled HHI 0.0058, top-10 = 19.6 %; monthly top-10 up to 30.2 % in 2026-04 with a single maker at 7.5 %), yet its top-10 make only 1.8 % of fills — a few large political market-makers. Sports and Price Action top-10 take 10–11 % of fills (high-frequency quoting bots). Cross-class overlap among the 80 pooled top-10 seats: one maker (`0xC8ab…6418`) is top-10 in five classes (Culture, Finance, Other, Politics, Sci-Tech), two more in four; the Sports/Price-Action/Crypto top-10s are disjoint from the political/cultural ones except two makers spanning Crypto+Price Action.

**Verdict Q6b: publishable** — 40 consecutive monthly observations of the full maker population with exact totals; the class split covers 2026 only (the per-class maker table was only accumulated for 2026 to bound memory).

## Caveats

1. **Maker-fill rows.** Every statistic is over maker fills; the taker-order aggregate is not a row. Notional counts the maker leg of a mint at the complementary price (≈(1−p)·N), so 'fill notional' is not the taker's cash — that is precisely why mint/fill ≈ 2 (Q5.1).
2. **Mint/merge identification from the tape alone is a lower bound** (Q5.4): 23.4 % of rows / 28.1 % of shares flagged vs. a CTF-implied 65.9 % of shares being mint legs in binary markets. Any paper that reports 'wash-like' same-second cross-token activity from this tape is measuring exchange mints.
3. **`resolved_at` NULL = unknown.** 530,309 resolved markets (62.9 %) — every negRisk market and most pre-2026 binary markets — were excluded from Q6a and never substituted with `close_at`. Q6a is therefore a 2026 sample dominated by 15-minute/hourly crypto markets and sports.
4. **Category granularity.** Tags are event-level marketing tags (1,900 distinct); the 8-class scheme follows the archive's own `category_refined`; 4,899 negRisk markets ($488 M, 1.7 % of notional) could not be classed and sit in 'Other', which also contains real 'Other'. 'Price Action' is a crypto subclass and is kept separate because its microstructure (clock resolution, 15-minute horizon) is different.
5. **Block→time map** is tape-derived (no RPC). Monthly assignment of CTF events is safe (validated ±40 min at p1/p99); April 2026 is cut at the tape end. CTF stakeholder classes: `0x4bFb…` CTF Exchange, `0xd91E…` NegRiskAdapter, `0xC5d5…` NegRisk Exchange (never a stakeholder), `0xADa100…`/`0xAdA100D…` unidentified Polymarket vanity contracts active from 2026-04 (splits $162 M in April 2026), 'other' = 109k distinct addresses.
6. **Universe coverage.** $10.0 B of all-time splits and $5.1 B of redemptions are on conditions absent from the fill tape; ratios are computed on tape conditions only.
7. **2026-04 is partial** (tape ends 2026-04-28) for both fills and CTF.
8. Memory bound used for every process: DuckDB `memory_limit='4GB'`, `threads=4`, spill to scratch; systemd `MemoryMax=6G`. Pass A runs were killed twice by session restarts and once for memory before the streaming rewrite; all monthly outputs were regenerated from complete inputs and reconcile exactly to the tape totals.

## Novelty vs. cited work

* **arXiv:2603.03136** (2024 election market: proper volume accounting, share creation vs trading, Kyle's λ) — one market. Here: 40 months, 851k markets, every CTF split/merge/redemption attributed to stakeholder class and market class; exact tx-level identity between exchange splits and complement legs; the finding that ≈2/3 of binary share volume is exchange minting and that the public tape under-identifies it 2.7× is new.
* **arXiv:2604.24366** (eight stylised facts, 600 markets, 52 days, 'concentrated maker diversity') — a 52-day cross-section. Here: monthly maker HHI/top-10/persistence for 40 months and 1.24 M makers; the transition from a 14-effective-maker oligopoly (2023) to a 400–560-effective-maker tail (2026), the notional-vs-fill-share wedge, and per-class concentration are new.
* **arXiv:2602.19520** (domain-specific calibration) — calibration of prices vs outcomes. Here: not calibration but *time-to-resolution* convergence anchored on the resolution instant, split early-vs-deadline and by class; the bimodal h1 distribution and the coverage warning about `resolved_at` are new, but the sample limitation (Q6a verdict) must be fixed before publication.
* **arXiv:2606.04217** (the archive paper, classifier benchmarks) — documents the tape. Here: independent verification of its leg semantics against on-chain fills and the measurement that its same-second structure cannot recover mint legs.

## One-line verdicts

* **Q5** — publishable (CTF-anchored; tape-only rule = lower bound ×2.7; negRisk exchange-vs-user minting not separable).
* **Q6a** — needs more (exact on 262,612 markets, but 63 % of resolved markets excluded for NULL `resolved_at`, 0 % negRisk, 99 % 2026; corpus check h1 median 0.001 passes; CTF-block anchor validated as the route).
* **Q6b** — publishable (40 monthly observations, exact totals; class split for 2026 only).

## Files

`data/parquet/atlas/struct_markets.parquet` (851,083 markets + class), `struct_assets.parquet`, `struct_condmonth.parquet`, `struct_maker_month.parquet`, `struct_taker_month.parquet`, `struct_mintgroups_condmonth.parquet`, `struct_winner_offsets_archive.parquet`, `struct_ctf_resolution_time.parquet` (block-derived resolution time for 841,272 conditions), `struct_category_classmap.parquet`, `struct_q5_ctf_monthly/by_class/reconciliation_*`, `struct_q5_fills_monthly/by_class`, `struct_q6a_platform/corpus`, `struct_q6b_monthly/2026_by_class`. Scripts and logs: scratch `atlasC/` (`passA2.py`, `passB_merge.py`, `passC*_*.py`, `ctf_month.py`, `q5fills.py`, `q5ctf.py`, `q6a.py`, `q6b.py`, `calib.py`).
