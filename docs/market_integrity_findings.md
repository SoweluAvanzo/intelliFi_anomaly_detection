# Polymarket market-integrity findings — discovery layer (Stages A–C)

**Scope.** 100-market corpus, complete v1 archive tape (`INTELLIFI_SOURCE=archive`,
`data/corpus_cids.txt`), **taker (aggressor) side** (on the archive `trades` view
`proxy_wallet = taker`); makers/liquidity providers are the uncounted counterparty.
607,584 taker wallets. All findings are **descriptive / associational** and framed as
*suspicious* or *consistent with* — never as a legal claim of manipulation. Wallet
addresses named below are **investigation candidates, not accusations**.

Generated from `docs/{market_structure,skilled_population,wealth_edge_archive,efficiency,event_study}.json`
(`scripts/23,24,25,26`, `scripts/20`).

---

## Headline

On this corpus the market is, on average, **efficient and not exploitable**: the
directional (taker) side loses ~3M USDC net to liquidity providers, no
statistically-certifiable skilled cohort exists, prices track the eventual winner
early, and no insider *ring* is detectable. The interesting structure lives entirely
in the **tail**: a handful of large geopolitics traders, and two US–Iran event
markets where large winning-side positions were built cheaply just before the event.
That tail is *consistent with* informed trading but equally with public-escalation
speculation, and cannot be promoted to "insider" without a news timeline.

---

## Platform-wide validation (whole v1 archive, 2022–2026)

The corpus findings below were re-run on the **entire v1 archive** — 838,385 resolved
markets, 2.59M taker wallets, 730M fills (`scripts/27_platform_wide.py`,
`docs/platform_wide.json`). The story holds and strengthens at ~30× scale:

- **Takers lose −$86.07M net to makers.** Only **33% of wallets are net-positive**
  (1.73M losers vs 854k winners). (Corpus was −$2.96M.)
- **Winnings extraordinarily concentrated:** Gini(+PnL) = **0.954**; the top-20 taker
  wallets captured **+$80.3M** (single biggest +$11.5M).
- **Every category well-calibrated:** per-category taker edge |gap| < 0.8%, mostly
  slightly negative. **NB — the corpus's `politics_us` +0.94pp was a small-sample
  artifact; platform-wide it is −0.25%** (scaling *corrected* a corpus finding).

So the aggregate characterization — efficient, maker-favored, crowd loses, winnings
concentrated in a tiny elite — is **platform-wide, not corpus-scoped**. Still corpus-
scoped (pending platform-scale runs): the skilled-population test, efficiency-over-time,
and the event study. A **v1-vs-v2 comparison** needs v2 winning outcomes — the complete
v2 resolution registry (2,108,903 conditions, verified in `docs/ctf_v2_verify.json` /
`docs/audit_2026-09-05.md §5`) is **now on disk**, and a corrected deduped, net-of-fee v2
taker-PnL run (`scripts/28` → `docs/v2_platform.json`) is being produced; the comparison
must use v2 **net** of fees, since v1 was ~fee-free (see `docs/audit_2026-09-05.md §1,§7`).

---

## Q1 — Who wins, who loses, on which markets (Stage A, `scripts/24`)

- **The taker side loses ~2.96M USDC net** across 607k wallets. Directional bettors
  pay the spread; makers/liquidity providers are the structural winners.
- **Winnings are extremely concentrated** — per-market Gini of winners' PnL ~0.91–0.99
  in most categories (culture lower, ~0.63); in sports only ~4% of takers win a given market.
- **Per-category edge** (size-weighted realised hit-rate − entry price): slightly
  **negative everywhere except `politics_us` (+0.94pp)**. Sports worst (−0.42pp).
  The one positive category is driven by a *few* single-market whale wins
  (+485k, +220k, +159k, each on **one** market) — see Q5.
- **Top winners** are either broad geopolitics specialists (`0x0a854…` +506k across
  18 markets; `0x35417b…` +334k across 16 geopolitics markets) or single-market
  whales (`0x9f5a…` +485k on one politics market). **Top losers** are high-volume
  grinders and single-market whales alike (`0xdbade…` −325k/31 markets;
  `0xbacd…` −246k/61 markets/3,520 trades).
- **Caveat:** ranking by *realised* PnL is outcome-dependent (survivorship) — a "top
  winner" is defined by having won, so this is descriptive structure, not skill.

## Q2 — Is there exploitable skill / a "smart-money" cohort? (skilled-population, `scripts/23`)

Powered test on 14,948 archive wallets (≥5 informative positions), asking *"does the
population contain skill beyond chance?"* rather than certifying individuals:

- **Aggregate edge vs price: −0.0055/position** (95% CI [−0.0080, −0.0030]) — the
  average wallet wins *slightly less* than its entry price implied (fees +
  favourite–longshot bias).
- **Fewer standout winners than chance:** 123 wallets beat their paid rate at p<0.05
  vs **257 expected** under a "wins at the rate it paid" null — a *deficit*. More
  significant losers (173) than winners. Gap distribution *tighter* than the null.
- **Skill beyond the favourite–longshot bias** (within-decile shuffle): observed
  top-tail (+0.252) marginally exceeds the null (+0.245, p=0.001) but the effect is
  trivial (+0.007) and consistent with within-wallet correlated-markets, not skill.

**Verdict: no statistically-certifiable skilled cohort.** The positive point
estimates that "break the null" do not, collectively, exceed chance.

## Q3 — Do bigger accounts win more in longshots? (`scripts/20`, archive)

- **Not a clean yes.** Top-quartile accounts have a reliably *higher* low-p edge than
  the bottom quartile (Q4−Q1 = **+0.47pp**, 95% CI [+0.05, +0.82]) — but the top
  quartile's *absolute* longshot edge is **~0** (+0.10pp, CI includes 0); small
  accounts lose slightly. So big accounts **avoid the longshot loss** rather than
  extracting an edge.
- **Confound:** account size = cumulative taker notional is outcome-dependent (winners
  accumulate), so the gradient is partly mechanical. Associational, not causal.

## Q4 — Market efficiency over time, by category (Stage B, `scripts/25`)

Winner-outcome price convergence at horizons before close:

- **Efficient in aggregate:** the *median* market prices the eventual winner at **0.97
  a full month before close**, 0.99 by a week out. No time-based free lunch.
- **But resolution type splits the tail:**
  - **Scheduled macro (Fed/FOMC) — textbook efficient, the low-insider control:** the
    December rate decision moved 0.68 (30d) → 0.94 (7d) → 0.97 (24h) → 0.999, a
    *gradual* convergence as public data/communications arrived, **no jump** at the
    meeting.
  - **Surprise geopolitical events — flat then a sharp jump at the event:** "US strikes
    Iran" winner 0.06 at 24h → 1.00 at ~1h; "US–Iran ceasefire" 0.14 → 1.00.
  - **Elections (Romania) — late upsets:** underpriced the eventual winner until
    election night (~0.33 at 7d), then converged.
  - **One anomaly:** a QatarEnergy LNG market's winning outcome stuck at ~0.06 to 1h
    before close (likely illiquid/stale, possibly a resolution to check).

## Q5 — Insider-timing event study (Stage C, `scripts/26`)

For each event-jump market, who positioned on the winning side *before* the jump, at
what price (YES-equivalent):

- **"US strikes Iran by Feb 28"** (jump ~3.5h before close; winner ~0.14 until then):
  large cheap winning-side positions — top wallet **784k sh @ $0.21 → +$623k**;
  others at **$0.10–0.12** (+$315k, +$227k, +$185k…). 3,440 winning-side positioners.
- **"US–Iran ceasefire by Apr 15"** (winner drifted 0.18→0.26→0.48 over the final
  12h): top **156k sh @ $0.12 → +$137k**. 2,138 positioners.

**Honest read — triage, not a smoking gun:**
- Positioning is **broad** (3,440 / 2,138 wallets), not a small ring → consistent with
  mass speculation on publicly-visible escalation.
- **No wallet front-ran both** Iran events (zero cross-event overlap among cheap-entry
  winners) → no coordinated-insider signature.
- **Fed control clean** (no jump, no pre-jump positioners); **elections/crypto**
  positioners entered at **fair ~$0.50** (winning a coin flip, not informed).
- **Ties to Q1/Q2:** the biggest cheap-entry Iran positioners (`0x35417b…`, which tops
  the geopolitics-category leaderboard, and `0x1caa6a…`, a top-overall Stage A winner
  (#6, +237.8k)) are among the large Stage A winners — a coherent large-geopolitics-trader
  cohort — yet they do **not** beat the Q2 skilled-population null.

**The one test that could promote "suspicious" → "informed"** — did the accumulation
*lead* the first public report? — needs a **news timeline overlay (Stage D)**, not yet run.

---

## Synthesis

The corpus tells a consistent story across all five analyses: an **efficient,
maker-favoured market with no detectable skilled cohort and no insider ring**, whose
only anomalous structure is a thin tail of **large geopolitics traders taking cheap
winning-side positions before surprise events**. Whether that tail reflects skill,
public-information speed, or private information is **undetermined by trade data
alone** — and, statistically, the tail does not exceed what chance plus a broad,
liquid market produces.

## Limitations

- **Taker side only**; makers uncounted. **Realised-PnL rankings are outcome-dependent.**
  **Corpus of 100 markets** (thin for some categories). **Account-size proxy is
  endogenous.** **Insider attribution is impossible from trade data** — every Q5 signal
  is *consistent with* informed trading, never proof.

## Next steps

1. **Stage D — news timeline** on the flagged US–Iran markets (does price/positioning
   lead the first public report?). Needs external news data (geo-block caveat).
2. **Confirmatory H1–H4** (`scripts/22`, `docs/stage2_preregistration.md §3`) — the
   registered fee-integrity layer (wash / negRisk-bounds / provider / order-size DiD)
   on the v2 Sample-B panel; single fee-free control (geopolitics_world) caveat.
3. **Scope widening** — sub-groups then the whole archive, per the staged plan.
