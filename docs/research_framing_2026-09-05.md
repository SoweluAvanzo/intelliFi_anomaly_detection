# Research framing and RQ line — 2026-09-05

Can our data + results support a **complete, coherent, publishable** line of reasoning, and
which RQs should we adapt or drop? Grounded in a literature scan (Part 1) and our own results.
**Headline: the obvious framing is already taken; the publishable line must pivot.**

---

## 1. Reality check — most of the "who-profits / concentration / skill" story is already published

Two full-population Polymarket papers, both public before any 2026 submission of ours, cover
almost exactly the concentration + skill RQ:

- **Akey, Grégoire, Harvie & Martineau (2026), "Who Wins and Who Loses in Prediction Markets?
  Evidence from Polymarket"** (CEPR DP 21615 / SSRN 6443103). Full on-chain population
  2022–2026, 2.4M users, $67B. **Top 0.1% capture 51.2% of gains, top 1% capture 76.5%, ~69%
  of users lose.** The edge is **liquidity provision** (maker share the strongest predictor),
  not calibration. A mixture model labels ~29% "skilled" but they **caution against a skill
  interpretation** (persistence "may reflect selection").
- **Gómez-Cram, Guo, Jensen & Kung (2026), "Prediction Market Accuracy: Crowd Wisdom or
  Informed Minority?"** (SSRN 6617059). 1.72M accounts; a **sign-randomization null (10,000
  sims)** finds **~3.1% skilled, ~6% worse than chance, ~91% indistinguishable**; skilled +
  makers (<3.5%) capture >30% of gains. "The majority does not produce accuracy; it funds it."
- **Convexly (2026)** practitioner study: **calibration explains ~2% of profit-rank variance**;
  sizing and event-concentration dominate.

**Our numbers replicate theirs.** Taker top-1%-of-winners 69.7%, ~67% of wallets net-negative,
Gini(+PnL) 0.954 (`concentration.json`). This is corroboration on an *independent* on-chain
reconstruction — useful, but **not a novel result**. A referee cites Akey on page 1.

**Our one divergence — "no certifiable skilled cohort" — points the *opposite* way** to both
papers and is, as it stands, **our weakest card, not our strongest.** It most likely reflects
(a) our skill test running on a **taker-side tail sample** (14,948 wallets; `/trades` is
taker-only, ~90% at p≤0.05/≥0.95) and (b) a **different null** (a paid-for-rate/calibration null
vs their sign-randomization null answer different questions). A negative result contradicting two
full-population papers will be read as an **artifact** unless we replicate on the full maker+taker
tape with a matched null.

---

## 2. Where we are actually differentiated

Neither competitor has these; this is where a publishable contribution lives:

1. **The v2 fee rollout as a natural experiment.** Akey/Gómez-Cram study the (largely pre-fee)
   trading population; **nobody has studied Polymarket's fee introduction.** Our Stage II work —
   fee **incidence and regressivity** (2.99%→1.15% across size deciles, 96% fee-paying, entrants
   ~5.7×), **integrity-under-fees** (self-matching 0, no wash rise, provider structure and order
   size unchanged), the **negRisk no-arbitrage band widening**, and the corrected **net-of-fee
   PnL** (v2 takers −$129.5M net, the fee being the dominant loss channel) — is genuinely new.
2. **A methodological reconciliation of skill nulls.** *Why* does a paid-for-rate/calibration
   null say "no skill" while a sign-randomization null says "~3% skilled" on the same platform?
   Neither paper asks this. Answering it (on our full tape, both nulls, same population) converts
   our "contradictory" result into a **contribution about what each null actually measures.**
3. **A market-integrity / harm framing.** The gambling literature (Fiedler et al.; Norway account
   records) uses **Gini-of-losses as a harm signal** correlated with problem-gambling revenue
   share — a lens the finance papers don't use and that fits our original mission. Paired with the
   **detection-ceiling nulls** (what on-chain data *cannot* reveal about coordination/insider
   timing — §1.8), this is a "limits of public-data market surveillance" contribution.

---

## 3. Adapted RQ line (coherent, and honest about novelty)

| RQ | Role | Status of our evidence | Novelty |
|---|---|---|---|
| **RQ1 — Profit distribution, both sides.** How concentrated are profits; do makers or takers capture them? | **Replication baseline** (cite Akey/Gómez-Cram) | DONE — Gini 0.95/0.95, top-1% ~70%, makers win aggregate but most maker wallets also lose | Low — replication + explicit **both-sides** cut |
| **RQ2 — Do skill nulls agree?** Reconcile a calibration/paid-rate null with a sign-randomization null on the same population. | **Methodological, novel** | PARTIAL — we have the paid-rate null (no skill); need the sign-randomization null on the full tape | **Medium-high** — neither competitor does this |
| **RQ3 — The fee natural experiment.** Incidence, regressivity, and effect on integrity/quality of Polymarket's fee rollout. | **PRIMARY / novel** | STRONG — incidence + integrity nulls shipped; H1b/H2 confirmatory to land | **High** — unstudied elsewhere |
| **RQ4 — Detection ceiling.** What can on-chain data reveal about coordination/insider timing, and what is the limit? | **Framing / differentiated** | PARTIAL — nulls + Iran triage; needs a news-timeline overlay to be a clean ceiling result | **Medium** — the honest-limits angle |
| ~~Standalone "who wins/concentration"~~ | **DROP as a headline** | scooped | — |

Supporting descriptive (fold into RQ1/efficiency, not standalone): **favorite–longshot** — a mild
interior bias (longshots at implied 0.07–0.45 underperform 2–5pp, moderate favorites 0.55–0.67
outperform, extremes well-calibrated); **price efficiency** (winner 0.97 a month out). Both align
with existing work (Deleep 2026; Whelan 2025) — corroborative, not novel.

**The coherent one-paragraph thesis:** *Polymarket's introduction of trading fees is a natural
experiment. Using an independent full-population on-chain reconstruction, we (i) replicate the
extreme, maker-driven profit concentration documented for the pre-fee market, (ii) show the fee is
steeply regressive and is the dominant channel through which takers now lose, yet leaves market
integrity and provider structure unchanged, and (iii) reconcile why competing "skill" nulls give
opposite verdicts on this population — clarifying that concentrated winnings are a scale/liquidity/
survivorship phenomenon, not evidence of a forecasting elite.* Fees + reconciliation are the spine;
concentration is the replicated backdrop.

---

## 4. New analyses needed — all on data already on disk (no new collection)

1. **DECISIVE — sign-randomization skill null on the FULL archive tape (maker + taker).** Matches
   Gómez-Cram's method on 746M fills / 2.6M wallets. This is the single analysis that decides
   whether RQ2 stands: it either (a) reproduces "~3% skilled" (we reconcile with our paid-rate
   null) or (b) still shows no skill on the full population (a real, defensible divergence). Either
   way the taker-sample critique is neutralised. Feasible: per-wallet null PnL moments are
   computable; a few hundred sims suffice for a per-wallet z / tail count. **Heavy but runnable
   here** (the pattern of scripts/27/28).
2. **Condition winning on maker-share** (Akey's key predictor) — decompose our concentration into
   liquidity-provision vs forecasting, so we don't mislabel spread capture as skill. We have both
   `maker` and `taker` per fill.
3. **Whole-population top-k + Lorenz on signed PnL** for direct numeric comparability with Akey
   (we currently report winners-only Gini, a more extreme cut reviewers will question).
4. **Land the fee confirmatory** — H2 (negRisk band, within-B) and H1b (concentrated pairs); and
   **re-run the position-skill test on the v2 fee tape** so RQ3 has a within-fee-era skill read.
5. **Optional for RQ4** — a news-timeline overlay (spec Stage D) to promote the insider triage to
   a detection-ceiling result; needs external news data (the one place collection *would* help).

---

## 5. Recommendation

- **Do not submit a "who-profits/concentration on Polymarket" paper** — it is scooped by two
  strong 2026 full-population papers; we would be a replication.
- **Lead with the fee natural experiment (RQ3)**, use the concentration/who-profits as the
  replicated backdrop (RQ1, citing Akey/Gómez-Cram), and add the **skill-null reconciliation
  (RQ2)** as the methodological hook. Frame the whole around **market integrity and the limits of
  public-data surveillance (RQ4)** — our original mission, now honestly a *negative/limits* result.
- **Before any of it, run analysis #1** (full-tape sign-randomization null). It is the gate on
  whether our distinctive skill claim survives contact with the two competing papers.

Positioning memory: `[[project_literature_positioning]]`. Competitor data is public (Akey:
HuggingFace `vgregoire/polymarket-users`) — we can benchmark directly.

---

## 6. SHARPENED strategy after the deep-literature pass (2026-09-05, late)

A second literature scan on the four *pivot* topics changes the recommendation and must
override §3–§5 where they conflict.

**The lead paper is the FEE EXPERIMENT (Topic 1) — it has no direct competitor.**
- Title: **"Taxing liquidity on a prediction market: the incidence of a dynamic transaction
  fee and who captures the maker subsidy."** Topic 1 (fee) lead + Topic 2 (maker heterogeneity)
  companion — mechanically the *same* economics: Polymarket's taker fee funds the maker rebate,
  so "what the fee does" and "which makers capture the subsidy / escape adverse selection" are
  two sides of one question.
- **The clean design is the staggered fee rollout as a DiD**: fees phased in by category
  (crypto ~2026-01-05 → sports ~2026-02-18 → all ~2026-03-30), captured in the archive's
  `fee_usdc` (the archive spans the introduction; v2 is the mature regime). Treated-category
  vs not-yet-treated DiD on: participation/composition (who trades less), order size,
  round-trips, and the taker→maker transfer. **Lead with COMPOSITION and INCIDENCE, not
  headline volume** (volume elasticity is likely null — "within normal variance").
- Novel vs the FTT/tick-size canon (Umlauf 1993; Colliard-Hoffmann 2017; SEC tick pilot;
  **Whelan's prediction-market-fees paper** = the anchor): per-ORDER incidence by size
  (2.99%→1.15%), the **dynamic p(1−p) fee** that taxes exactly the informative 50¢ region, and
  the named-beneficiary transfer. Frame = microstructure + public finance
  (*J. Financial Markets / JFE-micro / Management Science*; policy cut → *J. Public Economics*).

**Topic 2 (maker adverse selection) — companion, REFRAMED.** Concede the average
maker-wins/taker-loses SIGN to Akey (SSRN 6443103) and the fill-side tiers to **Nechepurenko
(arXiv 2605.11640)**; our defensible residual is (a) **within-maker heterogeneity** (637k/1.21M
makers lose; counterparty-win-rate↔PnL Spearman −0.58; professional elite escapes AS), (b) the
**adverse-selection mechanism** (counterparty informedness), and (c) the **fee interaction** (the
elite captures the rebate). Must separate adverse selection from latency ("picked off before
cancel") and use an ex-ante skill instrument, not the ex-post volume sort, for the elite/amateur
split (else tautological). Grounding: Glosten-Milgrom (1985); LVR (Milionis et al. 2022) as the
AMM contrast (a CLOB prediction market sits between the two literatures).

**Topics 3 (entity concentration) & 4 (syndicate graph) → ROBUSTNESS sections, not papers.**
- T3 is incremental (Akey's wallet-level top-1%=76.5% is the baseline; "entities more
  concentrated" is expected) and validation-limited (CEX/relay/proxy false merges inflate it) —
  keep as a magnitude-and-validation robustness note; method borrowed from Meiklejohn (2013) /
  Victor (2020) / airdrop-sybil lit.
- T4 is in **direct tension with our own coordination null** (CLAUDE.md) AND with Gómez-Cram's
  "persistence = skill"; co-trading is confounded by common-information co-movement, and shared
  funding ≠ coordination. Keep strictly DESCRIPTIVE/triage, survive the *same* activity-preserving
  nulls that killed the earlier signal, and distinguish from **Mitts & Ofir (2026)** (per-pair
  suspicion score, ~$143M flagged — the insider competitor) and Dai/Jia/Yu (settlement manipulation).

**The skill reconciliation (RQ2)** remains a useful methodological section (sign-flip over-counts
via correlation; persistence rho ≈ 0.11 = weak real skill) but is background to the fee paper, not
a lead — Gómez-Cram own the skill headline.

**Net:** ONE strong paper (fee incidence + maker subsidy), with concentration/skill/entity/
syndicate as replicated-backdrop and robustness. The overnight compute (skill, entity, graph)
supplies those robustness pieces; the **archive staggered-rollout fee DiD (`scripts/36`)** is the
lead paper's core identification and is the priority build.
