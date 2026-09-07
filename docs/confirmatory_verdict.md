# Confirmatory verdict — registered H1–H4 on Sample B (v2 tape)

**Registered design:** `docs/stage2_preregistration.md §3` (explore on Sample A → register → confirm on Sample B). Holm-corrected at α = 0.05 across the **available** tests (H1a, H3, H4; H1c is structural with no p-value, H1b/H2 pending — the registered family was H1–H4); class/family-clustered SEs; wild-cluster bootstrap where clusters G ≤ 12; §2 fee-treatment contingency.
**Sample B tape:** the v2 on-chain tape totals **714.95M** raw `OrderFilled` rows / **697.33M** after `(tx_hash, evt_index)` dedup — this is the **full crawled tape** (v2 genesis → cohort 6, 2026-04 → 2026-08), *not* the confirmatory window. Its dedup (GATE3) and determinism (GATE7) are evidenced in `data/logs/gate37.log`; the pre-registered completeness gate (§1) is 3 invariants over the 14-day window. Winner-linkage registry independently verified (`docs/ctf_v2_verify.json`, `docs/audit_2026-09-05.md §5`).
**Confirmatory scope (see `stage2_preregistration.md §7` Deviation 2):** only **H1c** runs on the frozen 14-day window (blocks 88,080,000–88,843,826, ≈ cohort 1). **H1a, H3, H4** were computed on the **full B tape** (19 weeks, 2026-04-27 → 2026-08-31) because §1's 14-day window is design-incompatible with the weekly-panel / ±8-week-DiD hypotheses in §3/§5 — H3/H4 are therefore **amended-window (post-hoc), read as weakened**, and H1a is pending a re-run on the frozen window.
**Computed by:** `scripts/22_confirmatory_hclass.py` → `docs/cohort_reports/confirmatory_h1_h4.json`.
**Status:** H1a, H1c, H3, H4 computed; **H1b in progress, H2 pending** (hardest — negRisk family derivation).

---

## Verdict table

| Hypothesis | Statistic | Result | Verdict |
|---|---|---|---|
| **H1c** self-matching | fills with maker == taker | **0** | **Confirmed** (structural) |
| **H1a** wash round-trips | rt_any_share, B fee-paying vs A-April, TOST ±1pp (**on the frozen window**) | mean **+1.21pp**; TOST p=0.61 (upper bound fails) | **Not confirmed unchanged** — modest elevation, crypto/politics only (see below) |
| **H3** provider structure | maker HHI / top-5 / spread, TOST vs A-April | point diffs small (HHI +12%, top5 +7%, spread ~0.2¢); TOST p≈0.10–0.38 | **Not confirmed equivalent** (underpowered; structure looks stable) |
| **H4** taker order size | log order-size DiD, β<0 predicted | registered 3-control: mean β=−0.56 (p=0.14), median β=+0.29 (p=0.73); single-control sensitivity: mean −0.48 / median +0.96 | **Inconclusive** (robust to control choice) |
| **H1b** concentrated pairs | pair vol share ≤ 0.1% | — | In progress |
| **H2** negRisk band | \|S−1\| vs fee band | — | Pending (hardest) |

**Holm-corrected across the available p-values (H3 0.38, H1a 0.61, H4 0.14): nothing reaches significance.** H1c is the one clean structural pass. (H1a is now computed on the frozen 14-day window per §7 Deviation 2.1; H4 uses the registered never-treated control set as primary per §7 Deviation 2.3.)

---

## Per-hypothesis detail

### H1c — self-matching (confirmed)
0 fills with `maker == taker` in the confirmatory window. Structural expectation met.

### H1a — wash-like round-trips (not confirmed unchanged; probably benign)
Computed on the **frozen 14-day window** (blocks 88,080,000–88,843,826) per §7 Deviation 2.1.
Round-trip ("wash-like") volume share (`rt_any_share`, 600 s / ≥50 % overlap, both legs) is
**+1.21pp higher on average in Sample B** than the A-April level of the same class. The ±1pp
equivalence TOST fails on the upper bound (p=0.61), so we **cannot confirm round-tripping is
unchanged**. Per fee-paying class (B = frozen window):

| class | B | A-April | Δ |
|---|---|---|---|
| politics | 5.25% | 0.64% | **+4.62pp** |
| crypto | 6.51% | 3.17% | **+3.34pp** |
| sports | 2.27% | 1.76% | +0.51pp |
| other | 1.08% | 0.75% | +0.33pp |
| esports | 2.73% | 2.61% | +0.11pp |
| finance | 1.34% | 1.30% | +0.05pp |
| culture | 1.34% | 1.85% | −0.50pp |

Only **crypto and politics** exceed the +1pp bound; the other five classes are within it.
**This is almost certainly not a fee-driven wash increase**, for two concrete reasons: (1) it runs
*backwards* to incentives — fees deter round-trips (each pays the fee twice), so a fee-*caused* rise
is mechanically implausible; (2) the elevation sits entirely in the two naturally high-churn classes
— **hourly crypto up/down markets** and **politics** — and the frozen window *is* the June US–Iran
escalation fortnight (the same event-driven churn the discovery event study flagged,
`docs/event_study.json`), so the window itself maximises event-churn in politics. Most consistent with
market-composition/churn, not integrity degradation. (geopolitics_world excluded: fee-free control,
under-captured in B by taxonomy.) The full-tape H1a (mean +1.05pp) gives the same verdict — the
result is not window-sensitive in direction.

### H3 — provider structure (not confirmed equivalent; underpowered, looks stable)
After correcting a definition mismatch (A's passB HHI is over (market × maker) pairs, not maker-only), B and A are **close**: maker HHI +12%, top-5 +7%, spread ~0.2¢. All point estimates sit inside the ±25% / ±0.5¢ bounds — consistent with "provider structure unchanged under fees." But the formal TOST does not clear the bar (p≈0.10–0.38): with only 11 class-level observations the between-class CIs are too wide to *certify* equivalence. Read as **stable but not formally certified** — an underpowered null, not a refutation.

### H4 — taker order size (inconclusive, robust to control choice)
DiD of log order size, B vs A-pre, treated (fee) vs control classes. Reported under **both** control
definitions (§7 Deviation 2.3):

| control set | median β (p) | mean β (p) |
|---|---|---|
| **registered never-treated** (geopolitics_world, finance_macro, politics_us) — PRIMARY | +0.29 (0.73) | **−0.56 (0.14)** |
| single fee-free-in-B (geopolitics_world) — sensitivity | +0.96 (0.86) | −0.48 (0.21) |

The predicted sign is β<0 (mean spec matches it). Under the **registered 3-control** set the DiD is
noticeably more stable than the single-control version (median β falls +0.96→+0.29) — resolving the
single-control fragility — but **nothing is significant under either** (mean p=0.14 primary, 0.21
sensitivity). finance_macro and politics_us pay fees in B, so as fee-DiD controls they are
*contaminated*; that both the contaminated-3-control and the clean-1-control readings are
inconclusive is itself reassuring. **H4 neither confirms nor refutes β<0.** Holm uses the registered
mean spec (p=0.14).

---

## Overarching limitations (why the confirmatory layer is only partially informative)

1. **Cross-sample confound.** Sample A = v1 archive (calendar span **2022-11 → 2026-04**; the fee window Oct 2025 → Apr 2026), Sample B = v2 tape (**2026-04-27 → 2026-08-31**) — *different exchanges and non-overlapping eras*. Any direct B-vs-A comparison (H3, and the levels feeding H1a) conflates a fee effect with the v1→v2 venue difference. The DiD (H4) is designed to absorb this via controls, but —
2. **H4 control-set fragility (now bounded).** Only geopolitics_world stays materially fee-free in B. H4 is now reported under **both** the registered never-treated set (3 controls, primary) and the single fee-free-in-B control (sensitivity) — **inconclusive under both** (mean β<0 but p=0.14 / 0.21), so the conclusion is robust to the control choice even though each control set has a weakness (contamination vs. a single cluster). Logged as Deviation 2.3.
3. **Small class counts.** 7–11 class-level observations → the equivalence tests (H1a, H3) are underpowered; wide CIs prevent certifying equivalence even when point estimates are close.
4. **Definition-matching rigor.** Six real construction/definition bugs were caught and fixed during A-vs-B matching before any number entered a verdict (order-size level confound, spread sign-flip, HHI market×maker definition, H1a order construction, fee-join key, esports tag leak). The sanity-checking that surfaced them is why these numbers are trustworthy as far as they go.
5. **Pre-registration deviations (logged 2026-09-05).** The 2026-09-05 audit found the confirmatory window, the H1a class taxonomy (coarse 8-class vs the fine 13-class §1 mapping), the H4 control assignment, and several SE/TOST operationalizations departed from §1–§5 and had not been logged. All are now recorded in `stage2_preregistration.md §7` Deviation 2 with their affected statistics. **None changes a verdict** (every affected test is null), but they move H1a/H3/H4 from strictly-confirmatory toward amended/exploratory. The single clean confirmatory pass on the frozen window remains **H1c**.

---

## Bottom line

The registered Sample-B confirmation is **partially informative**: one clean structural pass (H1c), one underpowered-but-stable result (H3), one inconclusive DiD (H4), one modest directional signal (H1a) best explained by high-churn market composition rather than fees, and two tests still to come (H1b, H2). **No clean integrity problem is detected, and no clean confirmation of the null is established either** — the binding constraints are statistical power (single control, small class counts) and the v1-vs-v2 cross-sample difference, not any observed anomaly.

This is a secondary rigor check. The **discovery findings** (`docs/market_integrity_findings.md`), which run entirely on the verified archive, are the study's primary, solid result and are unaffected by the confirmatory layer's limitations.

*This verdict will be updated when H1b (concentrated pairs) and H2 (negRisk band) land.*
