# Stage II atlas — exploration on the v1 archive (Sample A), 2026-08-30

Three independent analyses on the public Polymarket-v1 archive (Oct 2025 → Apr 2026 for the fee questions; 2023-01 → 2026-04 for the structural ones), run under the §10 explore/confirm protocol. Full reports: `A_fee_rollout_liquidity.md`, `B_wash_negrisk_fees.md`, `C_minting_convergence_makers.md`; intermediates in `data/parquet/atlas/`; scripts in `scripts/`.

| Q | Question | Verdict | Headline |
|---|---|---|---|
| Q1 | Fee-rollout treatment identification | **publishable** | Fee status attaches at market birth (345,605/345,646); 11 weekly cohorts Jan 5 → Apr 20; 103 never-treated tags; `taker_base_fee` is not a valid indicator (`fee_usdc>0` is); fee = 0.10·shares·min(p,1−p) |
| Q2 | Liquidity provision under fees (DiD) | needs more | Maker HHI / top-5 / spread proxy: no pre-trend, no post effect (HHI CI ±25 %, spread ±0.5 c); volume, participation, order size not identified (treated categories were growing; ≤3 post weeks for 49 % of tags) |
| Q3 | Fee incidence | **publishable (descriptive)** | Zero exemptions; incidence = exposure × price mix; regressive within-market rate (7.9 % small long-shot takers vs 4.4 % whales); post-rollout entrants pay 5.7× via exposure |
| Q3′ | Wash-like activity under fees | needs more | Self-match = 0 of 663.5 M fills (also 2024–25); round-trip share 1–2 %, lower in fee fills in 7/8 classes; DiD +0.1…+0.3 pp n.s.; concentrated pairs ≤0.02 % of fee volume; rebate farming not supported on any proxy |
| Q4 | negRisk no-arbitrage bounds under fees | **publishable** | median |S−1| 0.012 → 0.031, p90 0.075 → 0.116; +3.4…+4.2 pp (SE 0.002–0.003) with month×size×class FE; 16,718 families / 311 k hours; signed mean unchanged |
| Q5 | Share creation vs secondary trading | **publishable** | Exchange minting = 1.6–3.5× fill notional every month since 2024; ≈71 % of binary share volume is mint/merge; the tape-only same-second rule under-identifies it 2.7× (exact tx-level identity on 5 markets) |
| Q6a | Resolution-anchored convergence platform-wide | needs more | Exact on 262,612 markets but 63 % of resolved markets have NULL `resolved_at` (all negRisk); bimodal 1 h distribution (median 0.001, p90 0.51) driven by in-play sports and clock-resolved price-action; corpus check h1 median 0.001 reproduced; CTF-block resolution times validated (median +216 s vs Gamma) as the fix |
| Q6b | Maker concentration platform-wide | **publishable** | 40 monthly observations: 14 effective makers (2023-01) → 400–560 (2026); top-10 share 69 % → 9–12 %; top-10 fill share 47 % → 1–5 %; persistence 0.7–0.9 → ~0.4 |

Cross-cutting facts: fee status is market vintage, not a switch (identification caveat for every fee DiD); v1 CLOB never self-crosses (maker == taker is 0 of 663.5 M fills; note that the ~1 % median in arXiv:2604.24366 is a two-tier rule — self-match OR flipped maker/taker pair within 128 blocks — so it is not contradicted; a decomposition of that rule on the same window is the right comparison); archive `resolved_at` is NULL for all negRisk markets and most pre-2026 binaries; `taker_base_fee` is decorative. Fee *levels* implied by the archive (platform take 3.2 % of taker notional by April) must be verified against fee-collector transfers before quoting dollars; relative results are unaffected.

Pre-registration for Sample B (v2 tape) must be written from these results before any v2 statistic is computed (spec §10.2).
