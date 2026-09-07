# Polymarket study — integrated synthesis (2026-09-06)

## Lead paper — "Taxing liquidity on a prediction market: incidence of a dynamic fee and who captures the maker subsidy"
Fee rollout = natural experiment (scripts/36 fee_rollout_did.json). Staggered adoption recovered from data:
crypto-updown Jan 2026 -> most categories Mar -> culture/finance/tech Apr. Event study (months rel. to each
category's own fee-start): fee 0% pre -> 3.3% at month 0 -> ~12% by +3. Behavioural/welfare response:
median order size $6.9 -> $2.9 (halves+); new-wallet entry 317k -> 89k over 3 post-fee months (confounded with
growth). Steep regressivity (fee-rate falls monotonically by order-size decile; v2 tape clean 2.7%->1.0%).
Transfer: hundreds of $M taker fees -> maker rebates+platform. Companion = maker adverse selection (T3):
637k/1.21M makers lose; counterparty-informedness<->PnL Spearman -0.58; top-decile makers escape AS (+$1,061).

## THE UNIFYING ECONOMICS (fee -> maker subsidy -> automated winners) — the spine of the paper
The three threads are ONE story. The dynamic taker fee FUNDS a maker rebate; the makers who capture it are NOT the
amateur LPs (637k/1.21M lose to adverse selection, Spearman -0.58) but the PROFESSIONAL/AUTOMATED liquidity
providers — precisely the actor-taxonomy WINNERS: market_makers (+$1,991) and HFT bots (+$1,152, near-24/7). Mean-
while the payers are small DIRECTIONAL retail takers, who under the fee trade smaller ($6.9->$2.9 median order) and
whose new-entry collapses (317k->89k/mo). So the fee is a REGRESSIVE TRANSFER from small directional retail takers
to a small automated market-making elite that captures the subsidy. "Who captures the maker subsidy" = the MM/HFT
winners; "who pays" = the regressive taker incidence + the directional retail who lose. That is the paper in one line.

## Supporting / robustness
- Who wins/loses: takers lose -$86M (v1) and -$129.5M net (v2) — both eras. Winnings Gini 0.95 (replicates Akey).
- Skill reconciliation (RQ2): full-pop sign-flip ~4.3% certifiably skilled (matches Gomez-Cram ~3%); earlier
  "no skill" was a taker-tail artifact. Persistence rho +0.15. Skill = breadth (skilled: 313 markets, 85%
  market win-rate, low concentration) — not one lucky win.
- Trader taxonomy: ~97% proxy wallets (Gnosis Safe/browser 74.5%, Polymarket-proxy/email 21%, EOA 3.3%; the
  "custom contracts" are inactive/low-activity, absent from active traders & winners — NOT characterised as bots).
  CORRECTED FINDING (behavioural, see actor-taxonomy below): automation + liquidity provision DO confer edge —
  market-makers (+$1,991) and HFT bots (+$1,152) WIN via spread capture; directional retail/active humans LOSE.
  EOAs are low z-SIDE-SELECTION-skill, but that is orthogonal to spread-capture PnL; most EOAs are behavioural
  retail, a minority HFT bots. No AMMs (CLOB); LLM-agents not on-chain-identifiable. Bot-vs-human = behavioural.
- Entity/syndicate (negative): funding-graph collapse ~3-5% sybil (funders are relayer hubs -> proxy->owner is
  the right method); co-trade graph = one blob = co-movement not coordination -> no winning syndicate.

## Positioning
Concentration/skill/who-profits are SCOOPED (Akey SSRN 6443103; Gomez-Cram SSRN 6617059) and insider scooped
(Mitts & Ofir) -> REPLICATED BACKDROP, cite & distinguish, never lead. The un-pre-empted, novel core is the FEE
EXPERIMENT + MAKER SUBSIDY (none of them touch fees, maker heterogeneity, or the behavioural actor taxonomy).

## PUBLISHABLE LINE OF REASONING (papers + target journals)
Arc: an efficient, maker-favoured on-chain prediction market introduces a dynamic fee; the fee is a regressive
transfer from small directional retail to an automated market-making elite that captures the subsidy. That single
natural experiment carries the whole program; the who-profits/skill work is the replicated backdrop.

PAPER 1 (LEAD, top-field) — "Taxing liquidity on a prediction market: the incidence of a dynamic transaction fee
and who captures the maker subsidy."
  Argument: fee rollout = staggered natural experiment (DiD). (a) INCIDENCE is steeply regressive (per-order,
  2.7%->1.0% clean; small orders far more). (b) BEHAVIOUR/WELFARE: order size halves, new-entry collapses. (c) the
  taker fee FUNDS a maker rebate captured NOT by amateur LPs (637k/1.21M lose, AS -0.58) but by professional/
  AUTOMATED makers (actor taxonomy: MM +$1,991, HFT +$1,152 win) -> a named-beneficiary regressive transfer.
  Novelty: first fee-INTRODUCTION study on an on-chain prediction market; per-order incidence; the transfer with
  behaviourally-identified beneficiaries. Anchors: Whelan (PM fees), Umlauf 1993 / Colliard-Hoffmann 2017 (FTT),
  SEC tick-size pilot, Glosten-Milgrom (AS). TARGET: JFE (micro) / RFS / J. Financial Markets / Management Science;
  policy cut -> J. Public Economics.
PAPER 2 (COMPANION or standalone microstructure) — "Who provides liquidity and who bears adverse selection in a
decentralized prediction market."
  Argument: maker-side heterogeneity + the behavioural ACTOR taxonomy (MM/HFT win via spread capture; directional
  retail/active humans lose; automation confers edge, reconciling with Akey). A CLOB prediction market sits between
  the equities-microstructure (Glosten-Milgrom) and AMM-LVR (Milionis 2022) literatures. Distinguish Nechepurenko
  (fill-side tiers) and Akey (average maker sign). TARGET: J. Financial Markets / Review of Asset Pricing Studies /
  Financial Cryptography / AFT / Management Science. (Can be folded into Paper 1 as its "who captures it" half.)
NOVELTY CHECK (2026-09-07) on the actor/account taxonomy — verdict: incremental-but-publishable, novelty rests
almost ENTIRELY on the account-TYPE leg.
- (a) on-chain account/contract TYPE (EOA/Safe/proxy/custom): NOT addressed in PM lit — but the types are a
  DOCUMENTED product fact (Polymarket CLOB signature_type 0/1/2 = EOA / Poly-proxy(email) / Gnosis-Safe(browser)),
  so novelty = quantifying the population split + crossing with function/PnL, NOT "discovering" the types. Reviewers
  will demand account-type adds ORTHOGONAL signal beyond onboarding channel, else it's descriptive plumbing.
- (b) behavioural function (MM/HFT via timing/24-7): PARTIAL — Nechepurenko (2605.11640) attempted fill-side tiers
  then RETRACTED, concluding PUBLIC FILLS CANNOT IDENTIFY MARKET-MAKING without the quote lifecycle. Our MM/HFT
  labels are fills-only -> SAME identification-limit critique; present as heuristic behavioural classes, not proven MM.
- (c) function->profit (LP/automation captures the edge): ALREADY the headline of Akey (6443103) & Gomez-Cram
  (6617059) -> our corrected "automation wins" is a REPLICATION, not a contribution. Cite & distinguish both.
=> actor/account taxonomy = SUPPORTING section (defensible core = the account-type axis; method borrowed from
Meiklejohn/Victor/MEV-searcher classification). Does NOT change the hierarchy: fee experiment + maker subsidy is the
only un-scooped LEAD. TODO before any "first to" claim: check Akey's full 87-feature schema for a hidden account-type
column; check Dune dashboards for a prior proxy/Safe/EOA population split.

PAPER 3 (MEASUREMENT/METHODS, short or appendices) — skill-null reconciliation + on-chain trader taxonomy.
  Content: skilled fraction is sample/null-dependent (full-pop sign-flip ~4% = Gomez-Cram; taker-tail paid-rate = 0),
  skill = breadth + spread-capture not forecasting; the account-type taxonomy (~99% proxies, onboarding paths); the
  NEGATIVE coordination results (no syndicate; funding-graph weak -> proxy->owner). TARGET: a measurement/finance-
  data venue, or absorbed as robustness appendices to Papers 1-2. Cite Gomez-Cram, Convexly, Meiklejohn/Victor.

RECOMMENDATION: submit PAPER 1 (fee + maker subsidy) as the flagship, fold PAPER 2 in as its second half (they are
one economics), and use PAPER 3 material as robustness. Do NOT submit a standalone who-profits/concentration paper.

Full numbers/caveats: docs/fee_rollout_did.json, actor_taxonomy.json, research_framing_2026-09-05.md §6,
research_ideas_2026-09-05.md §5, audit_2026-09-05.md, plus concentration/platform_wide/v2_platform/maker_economics/
skill_signflip/skill_breadth/entity_concentration/winning_graph/account_types .json.

## Actor taxonomy (scripts/39, behavioural) — appended 2026-09-06, CORRECTS the "automation != edge" claim
1.52M wallets (>=20 fills). Functional classes (maker_share / fills-per-day / 24-7 hour-entropy / mean PnL / win-rate):
- market_maker    n=84,120   mk=0.84 fpd=16  h24=0.72  mean +$1,991  47% win   <- BEST
- hft_bot         n=50,441   mk=0.22 fpd=109 h24=0.96  mean +$1,152  29% win   <- POSITIVE (24/7 automated)
- active_trader   n=274,031  mk=0.13 fpd=32  h24=0.63  mean -$312    21% win   <- LOSE (directional)
- retail_casual   n=1,086,388 mk=0.18 fpd=4  h24=0.67  mean -$89     32% win   <- LOSE
- one_shot        n=23,961   mk=0.11 fpd=13  h24=0.31  mean -$346    23% win

CORRECTION: the behavioural evidence REFUTES the earlier "automation does not confer edge / human-UI beats
automation" claim. The WINNERS are market-makers (+$1,991) and HFT bots (+$1,152, near-24/7); the LOSERS are
DIRECTIONAL retail/active humans (-$89 / -$312). So automation + liquidity provision DO confer edge (aligns with
Akey: edge = liquidity provision, not forecasting). Reconciles with the low z-skill of winners: they win via
SPREAD CAPTURE, not side-selection skill.

EOA/bot question (account-type mix per class): most EOAs are retail_casual (~62% of classified EOAs) = human-paced,
NOT bots; EOAs are modestly OVER-represented among hft_bot (~6.3% vs ~3.4% baseline) so a minority of EOAs are bots,
but the bot class is proxy-dominated (Safe+Polymarket). => cannot claim "EOAs are not bots"; most EOAs behave like
retail humans, a minority are HFT bots. Bot-vs-human is behavioural (this table), not account-type.
