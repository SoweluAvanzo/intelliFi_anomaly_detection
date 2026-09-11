# Internal verification & citation-integrity notes — NOT for the collaborator-facing report

Internal tracking only. These caveats were moved out of `research_plan_technical_report.md`
(which is meant to be presentable to collaborators). Collaborators will independently verify
everything if and when we pursue the plan; this file is our own checklist.

## Citation integrity
Every claim attributed to prior work in the report is stated as that work reports it, per two
independent literature reviews conducted for this project. Two items could **not** be fully
verified against primary text and must be re-checked against the live sources before any
submission or any "first-to" claim:

1. **Akey et al. (SSRN 6443103) full feature schema.** The SSRN PDF returned HTTP 403 on fetch, so
   the complete ~87-feature list could not be read; a hidden on-chain account-type column cannot be
   100% excluded. Re-pull and confirm before claiming the account-type axis is new to the literature.
2. **Public dashboards.** Confirm no public Dune (or similar) dashboard already reports a
   proxy / Gnosis-Safe / EOA population split for Polymarket, for the same reason.

## Preprint versions to re-pull at submission time
All 2026 preprints (Akey; Gómez-Cram; Nechepurenko; Mitts & Ofir; Qin & Yang) should be re-pulled
at their then-current versions and citations re-checked. In particular, Nechepurenko (arXiv
2605.11640) has a superseded "behavioral tiers" v1 and a later "identification limits" version —
cite the version actually relied upon.

## Author-initial gaps
Several 2026-preprint author initials are unconfirmed and must be completed from the primary
sources before submission (Akey co-authors; Gómez-Cram co-authors; Nechepurenko; Ofir; Qin; Yang;
Al-Chami).

## Methodological caveats already reflected in the report's Limitations section
- Fee event study is confounded with platform growth and cross-category substitution → the
  participation-response magnitude is an association until a placebo / synthetic-control design is run.
- MM/HFT labels are heuristic behavioral classes (public fills lack the order/quote lifecycle;
  cf. Nechepurenko) — functional classes, not identified roles.
- All PnL is realised, outcome-dependent, survivorship-subject — descriptive, not risk-adjusted skill.
- The account-type axis should be shown to add signal orthogonal to the onboarding channel.

## Provenance of figures
All quantitative figures in the report trace to the project result artifacts in `docs/*.json`
(post-audit corrected values; see `docs/audit_2026-09-05.md` and `docs/FINAL_SYNTHESIS_2026-09-06.md`).
