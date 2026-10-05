# Literature review and impact assessment — Polymarket fee study

*Internal working document. 2026-10-05. Source: the reading pack in `docs/lieterature to review 5_11_26/` read in full, plus the decision-relevant works each source cites.*

## Scope of the review

Reviewed in full: the thirteen items in the pack — Qin & Yang; Dubach; the two Polymarket help pages on trading fees and maker rebates; Malinova & Park; Galati; Cipriani & Guarino; Rothschild & Sethi; Callaway & Sant'Anna; Sun & Abraham; Bertrand, Duflo & Mullainathan; Kober; and the avdheshcharjan markouts finding — together with the works they cite that bear on our four research questions.

Added on 2026-10-05 and read: Akey, Grégoire, Harvie & Martineau 2026, *Who Wins and Who Loses in Prediction Markets? Evidence from Polymarket*, manuscript dated 21 June 2026. It is the closest competitor to the who-captures and who-trades questions and is treated as a primary source below.

Unavailable, cited only by DOI: Brauneis et al. 2022, Waitz & Mild 2020, Whelan 2023. These are confirmatory, not load-bearing.

Still to obtain: Gómez-Cram, Guo, Jensen & Kung 2025/2026, cited by Akey for the price-discovery result; confirmatory for the informativeness discussion, not load-bearing.

Identity settled (Gate-0, verified 2026-10-05 against the paper's front matter): the pack paper is Qin & Yang (Boka Qin, Rui Yang), *Polymarket-v1 Database*, arXiv 2606.04217v2, June 2026 — a **dataset and trade-classification paper**, not a fee study. Its three findings are the near-random aggregate accuracy of the tick rule and bulk-volume classification and its correctable price-level gradient, the propagation of that classification error into VPIN and transaction-cost analysis, and ground-truth microstructure quality predicting forecasting. It contains **no fee difference-in-differences**. It is distinct from **Tsang & Yang 2026** (the 2024-election microstructure and Kyle's-λ paper, which it cites separately as "Yang and Tsang 2026", alongside Dubach and Akey). Consequence: an earlier pass that read Qin & Yang as a staggered-fee market-quality difference-in-differences was mistaken, and **no reviewed paper contains an empirical Polymarket fee study** — the fee lead is un-scooped.

## Per-source summary

| Source | What it establishes | Bearing on our study |
|---|---|---|
| Akey, Grégoire, Harvie & Martineau 2026 | Complete pre-fee Polymarket population, 2.4M users and $67B volume, Nov 2022 to 29 March 2026. Profits are extremely concentrated — top 0.1% capture 51.2% of gains, top 1% capture 76.5%, ~69% of users lose. Prices calibrated on aggregate; excess hit rate −15 to −18 pp in the loss tail to +20 pp at the top. The strongest cross-sectional predictor of performance is maker volume share, +1 SD giving +9.0 pp probability of positive performance; a bid-ask spread decomposition shows winners earn the spread and losers pay it, removing the minimum-tick cost moves 18.5% of losers to non-negative PnL. Heavy churn; persistence modest. Top-100 behavior inconsistent with insider trading. | The decisive competitor. It owns the **pre-fee** who-wins, maker-taker wealth-transfer, spread-decomposition, and concentration picture over the full population, and **ends on the eve of the fee launch by construction** because fees change the economics. This both scoops the static distributional picture and defines our opening: the fee-and-rebate era is exactly what Akey excludes. Its data is public on Hugging Face at `vgregoire/polymarket-users` and usable as the pre-fee baseline. |
| Qin & Yang 2026, arXiv 2606.04217 | The Polymarket-v1 dataset paper: the complete ground-truth v1 trade archive (1.2B trades, 1.3M markets), plus a microstructure benchmark showing tick-rule and bulk-volume classification are near-random in aggregate with a correctable price-level gradient, that this error biases VPIN and transaction-cost analysis, and that ground-truth microstructure quality predicts forecasting. **No fee analysis.** | Our ground-truth data source, and a methods caution on inferred trade direction. It does **not** touch the fee, fee incidence, maker-subsidy capture, adverse selection, or an account-type taxonomy, so it does not scope our contribution — it underpins the data. |
| Dubach 2026, arXiv 2604.24366 | Order-book microstructure of Polymarket: maker concentration, spreads, and a market-level Glosten–Harris spread decomposition with signed post-fill markouts against the book midpoint at a forward lag. | Owns order-book microstructure but studies no fees and targets the V1 era. Supplies the identified adverse-selection test our RQ3 needs. Its market-median markout is near zero, so our claim must live at the per-maker tail. |
| Polymarket Help — Trading Fees | `fee = C · feeRate · price · (1−price)`, taker-only, makers never charged, `feeRate ≤ 0.07`, rounds to five decimals with no minimum floor so dust rounds to zero. | Implies fee/notional = `feeRate · (1−price) ≤ 7%`. Our mature 2.7–3.2% is sound; the archive 8.8% and ~514% are impossible and must be rebuilt or dropped. |
| Polymarket Help — Maker Rebates | A daily USDC distribution funded by taker fees, 20–25% by category, performance-weighted on a fee curve, $1 minimum payout, per-market pools. | The rebate is a separate on-chain transfer, so it can be reconstructed as a ledger rather than inferred. This is what gates the who-captures question. |
| Malinova & Park 2015 | Make/take fee structure and its effect on trading costs; the distinction between posted and cum-fee spreads. | Any capture claim must be shown in fee-adjusted spreads against matched controls, not in a raw price-impact coefficient. |
| Galati 2024 | Maker-rebate economics: a rebate lifts liquidity-provider revenue, and takers fund it — "liquidity providers realize gains at the expense of takers." | Direct theoretical backing for the RQ3 thesis, with the same cum-fee requirement. |
| Cipriani & Guarino 2008 | A transaction cost's effect on price informativeness is theoretically ambiguous: it blocks marginal information aggregation while pruning noise. | Makes "no participation response identified" a principled result rather than an anomaly, and tempers any strong informativeness claim. |
| Rothschild & Sethi 2016 | A behavioral trader taxonomy of a prediction market, Intrade, by aggression, directional bias, holding duration, margin, and profitability. | Prior art for the taxonomy itself. Novelty for us survives only in the on-chain account-type axis and its crossing with function and outcomes. Supplies ready features and a same-second holding-collapse rule. |
| Callaway & Sant'Anna 2021 | Group-time average treatment effects ATT(g,t) under staggered adoption, with not-yet-treated or never-treated controls. | The correct estimator for the fee rollout; replaces the two-way fixed-effects event study, which is biased under staggered timing. |
| Sun & Abraham 2021 | TWFE event-study coefficients are contaminated across cohorts under heterogeneous timing; the interaction-weighted estimator fixes it. | Confirms why our pooled event study must be replaced, and offers the fallback estimator. |
| Bertrand, Duflo & Mullainathan 2004 | DiD serial correlation inflates significance; naive inference over-rejects badly with few clusters. | Treatment varies at the category level, roughly nine clusters, which is too few for cluster-robust standard errors. Inference must be permutation across categories plus a collapsed pre/post test. |
| Kober 2026 | On-chain reconstruction of Polymarket fees and rebates — $131.4M in fees and $29.23M in maker rebates — from known distribution addresses to recipient wallets. | Demonstrates the rebate ledger is recoverable with the exact method and infrastructure we already run. |
| avdheshcharjan markouts | Practitioner computation of maker markouts by volume decile on Polymarket. | Independent corroboration of the volume-tier profitability pattern, with scope and data-quality caveats; not a peer-reviewed result. |

## Findings that change the paper

### Akey et al. redraws the competitive map, and our opening with it

Akey, Grégoire, Harvie & Martineau is the single most consequential item in the review. On the complete population it already documents what we treated as part of our contribution: extreme profit concentration, the maker-taker wealth transfer, the bid-ask spread decomposition in which winners earn the spread and losers pay it, the dominance of liquidity provision as the predictor of performance, churn, and the behavioral characteristics of the top accounts. The decisive fact is their sample boundary: they run from November 2022 to 29 March 2026 and stop there deliberately, because Polymarket introduced fees on all markets on 30 March 2026 and that "materially changes the economics." So Akey is the definitive statement of the **pre-fee** distributional picture, and it leaves the **fee-and-rebate era untouched by construction**.

This narrows and sharpens our differentiator in one move. The pre-fee who-wins picture is no longer open to us and must be cited, not claimed. What remains ours is everything the fee introduces: who bears the new charge, whether and how it shifts the maker-taker transfer Akey measured, and who captures the fee-funded maker rebate that did not exist in Akey's window. Our study becomes the fee-and-rebate overlay on the distributional baseline Akey establishes — a cleaner and more defensible frame than competing on the baseline itself. Their data, public on Hugging Face, can serve directly as that pre-fee baseline, which also eases the Gate-0 reconciliation. Two of their cited contemporaries matter for our scoping: Della Vedova 2026 already classifies users as human or bot and decomposes profit into directional and execution components, so that axis of RQ4 is occupied; Becker 2025 documents the maker-taker wealth transfer on Kalshi, a centralized venue, which is the analogue our on-chain fee-era version extends.

### Positioning — which claims must be ceded, and which survive

The fee itself is un-scooped: no reviewed paper runs an empirical Polymarket fee study, and Qin & Yang — despite an earlier mis-reading — is a dataset and trade-classification paper, not a fee difference-in-differences. What *is* taken: Akey owns the pre-fee who-wins and maker-taker distribution; Rothschild & Sethi already built a behavioral trader taxonomy of a prediction market, so the MM–HFT–retail axis is not itself novel; Dubach owns order-book microstructure; Della Vedova owns human-versus-bot and the direction-versus-execution split. What remains genuinely open, and is where the contribution must be planted: per-order and trader-level fee incidence and regressivity; maker-subsidy capture measured from an actual on-chain rebate ledger and paired with identified per-maker adverse selection; the on-chain account-type crossing with function and outcomes; and a harmonized wallet-level accounting across the two fee regimes. The fee claims may be stated as "no empirical Polymarket fee study exists in the reviewed literature" rather than an absolute first.

### A correctness fix in the fee series

The fee formula caps fee/notional at the fee rate, at most 7%. The mature-era 2.7–3.2% figure is consistent with this; the archive 8.8% and the ~514% outlier are not physically possible. The dust-to-large gradient is the signature of a multi-fill fee double-count — one taker-order fee attributed to each maker leg without deduplication by the fill key — compounded by a field-scaling inconsistency and by projecting the 2026 schedule backward onto pre-fee trades. There is no minimum fee floor; dust rounds to zero. The series must be rebuilt by deduplicating on the fill key and auditing the denominator, or dropped. No regressivity claim can be headlined until this is done.

### RQ3 is salvageable and better identified

This is the most consequential positive update. The maker rebate is a daily on-chain USDC distribution, and Kober reconstructed it from known distribution addresses to recipient wallets. We can therefore build the actual rebate ledger with the Etherscan USDC-transfer infrastructure already in the pipeline, which closes the one gap the referees flagged as blocking the who-captures claim. Dubach supplies the identified adverse-selection test: a signed post-fill markout and Glosten–Harris spread decomposition against a forward price, which breaks the mechanical zero-sum payoff identity that confounds our −0.58 correlation. His market-median markout is near zero, so the claim must be made at the per-maker tail, not the market average. Malinova & Park and Galati give the economics and insist the capture be shown in cum-fee spreads against matched controls.

### The participation null is expected, and the estimator is fixed

Cipriani & Guarino make a fee's effect on informativeness theoretically ambiguous, so "no participation response identified" is a principled outcome. Methodologically, the descriptive balanced panel must become a Callaway–Sant'Anna ATT(g,t) with not-yet-treated controls aggregated to event time. The binding constraint is that treatment varies at the category level, roughly nine clusters, far too few for cluster-robust or bootstrap standard errors; by Bertrand–Duflo–Mullainathan, naive DiD over-rejects. Inference must be a permutation test across categories plus a collapsed pre/post Donald–Lang statistic, and the honest reading of a null at this cluster count is underpowered, not proof of no effect.

### RQ4 reframes and gains a method

Cite Rothschild & Sethi as the prior taxonomy; claim novelty only for the on-chain account-type axis and its crossing with function and outcomes. Adopt their features — aggression as taker share, directional bias, normalized holding duration, margin — and their same-second holding-collapse rule, which aligns with our distinct-second convention. Resolve the sample-versus-census inconsistency: report either "among sampled wallets" with weights and intervals, or a full census.

## Impact per research question

- **RQ1, who pays and regressivity.** Keep; genuinely open. Fix the fee series first, then extend from a posted-charge-by-order-size statement to incidence across traders, since a small order need not come from a small trader. Mostly existing data.
- **RQ2, behavior and participation.** Partly scooped, theoretically ambiguous, and underpowered at nine clusters. Keep only as a conservative null with the Callaway–Sant'Anna estimator and permutation inference, or demote to context — see the strategic fork below. Add churn, which is currently asserted but unmeasured.
- **RQ3, who captures the subsidy and why.** The flagship, and now buildable, but its frame must move. Akey already owns the pre-fee maker-taker wealth transfer and the spread decomposition, so our claim is no longer "makers capture the spread" but "the fee and its rebate redistribute that transfer, and here is who captures the rebate." Replace the archive maker-PnL association with the mature-era rebate ledger and a per-maker post-fill markout, and present it explicitly as the fee-era overlay on Akey's baseline. New on-chain collection, feasible with current infrastructure.
- **RQ4, who trades and how account type maps to payment and capture.** The weakest-novelty question after Akey and Della Vedova, who together occupy behavioral characteristics, human-versus-bot classification, and the direction-versus-execution profit split. What survives is narrow: the on-chain account implementation type — externally owned account, smart-contract wallet, proxy — which neither resolves, crossed with fee payment and rebate capture. Keep only in that narrowed form with Rothschild & Sethi and Della Vedova cited and the sampling language fixed, or fold it into RQ3 as a dimension of capture rather than a standalone question. Mostly existing data.

## References to add

- Make/take fee theory and empirics: Colliard & Foucault 2012; Foucault, Kadan & Kandel 2013; Angel, Harris & Spatt 2011; Chao, Yao & Ye 2019; Bloomfield, O'Hara & Saar 2005; Ellis, Michaely & O'Hara 2002; Brauneis et al. 2022.
- Adverse selection and markouts: Glosten & Milgrom 1985; Kyle 1985; Glosten & Harris 1988; Huang & Stoll 1997; Lee & Ready 1991; O'Hara 1995; Hasbrouck 2007; Easley, López de Prado & O'Hara 2012; Easley et al. 1996.
- Trader taxonomy lineage: Rothschild & Sethi 2016; Kirilenko et al. 2011; Baron, Brogaard & Kirilenko 2012; Copeland & Galai 1983; Waitz & Mild 2020; Della Vedova 2026 for human-versus-bot classification and the direction-versus-execution profit split.
- Who-wins and maker-taker distribution: Akey, Grégoire, Harvie & Martineau 2026; Becker 2025 for the Kalshi maker-taker wealth transfer; Barber, Lee, Liu & Odean 2009, 2014 for the Taiwan sophistication result; Reichenbach & Walther 2025 for skill persistence.
- Information aggregation: Cipriani & Guarino 2008; Avery & Zemsky 1998; Lee 1998; Miller 1977; Harrison & Kreps 1978.
- Difference-in-differences methods: Callaway & Sant'Anna 2021; Sun & Abraham 2021; Bertrand, Duflo & Mullainathan 2004; Goodman-Bacon 2021; de Chaisemartin & D'Haultfœuille 2020; Conley & Taber 2011; Ferman & Pinto 2019.
- Polymarket-specific: Qin & Yang 2606.04217; Dubach 2604.24366; the Polymarket fee and rebate help pages; Kober; avdheshcharjan markouts; Sirolly et al. 2025 on wash trading; Gómez-Cram, Guo, Jensen & Kung 2025/2026 on price discovery.

## Revised plan and time

| Work | Data | Est. |
|---|---|---|
| Gate 0 reconcile — align the fill grain on the fill key, the relayer-routed share, nominal vs economic volume; settle the Qin & Yang versus Tsang & Yang identity and whether it contains a fee design; cross-check our pre-fee baseline against the public Akey dataset — and ship artifacts | existing, public | 2–3 d |
| Gate 1 fee-number fix — deduplicate the multi-fill fee, audit the denominator and scaling, drop the backward projection | existing | 2–3 d |
| Positioning, claim relabels, and the new references | none | 3–5 d |
| RQ2 Callaway–Sant'Anna ATT(g,t) with permutation and collapsed pre/post inference, plus churn | existing | 4–6 d |
| RQ3a per-maker post-fill markout and cum-fee spreads | existing | 4–6 d |
| RQ1 trader-level incidence of fees against size | existing | 1–2 d |
| RQ4 account-type crossing with function, plus sampling weights and labels | existing | 2–3 d |
| Gate 3 build the on-chain maker-rebate ledger by the Kober method | new, feasible | 1–2 wk |
| Position against Akey — cite the pre-fee distributional baseline, reframe RQ3 and RQ4 as the fee-and-rebate overlay, drop every claim Akey already makes | none | 1–2 d |
| Optional order-book snapshots for book-midpoint markouts | new | 2–4 wk |

Total to a defensible submission is roughly five to seven weeks of focused work without the optional order-book collection; the rebate ledger is the pacing new-data item.

## Verdict

The right response is the middle path, now evidence-grounded. Keep the two-era data and the descriptive backbone; fix the one real correctness bug in the fee series; recalibrate the claims, add the references, and drop every first-mover claim; run the identifying analyses mostly on data already in hand; and collect one new on-chain dataset, the maker-rebate ledger, which the literature shows is recoverable and which secures the flagship question rather than forcing a narrow measurement paper.

Akey sharpens rather than threatens this. By owning the pre-fee distributional picture and stopping at the fee launch, it hands us a clean, uncontested thesis: the fee and its rebate are the one thing no published study measures, and our paper is the overlay that shows who pays the fee and who captures the rebate against the baseline Akey establishes. The strongest version of the paper is built squarely on that fee-and-rebate gap, which is also the argument for trimming the questions that sit outside it.
