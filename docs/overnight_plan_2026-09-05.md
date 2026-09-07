# Overnight autonomous plan — 2026-09-05 → 2026-09-06 morning

Goal: develop the pivoted research (away from the scooped concentration/skill angle) to a
strong, publishable stage, autonomously, respecting the hard **no-OOM** constraint (the
desktop baseline is ~13 GB of 31 GB; effective headroom ~16 GB; the harness kills any
background job when system memory dips low). Every heavy job runs **sequentially** in its own
9 GB cgroup with DuckDB `memory_limit` 3 GB and wallet-hash / block-range **bucketing** so no
aggregation ever exceeds budget.

## Compute pipeline (orchestrated: `scripts/run_overnight.sh`, one sequential process)

| # | Job | Script | Output | RQ |
|---|---|---|---|---|
| 0 | Full-population skill test (running) | `31_skill_signflip.py` (12 buckets) | `docs/skill_signflip.json` | RQ2 skill reconciliation |
| 1 | Fee behavioral/welfare | `33_fee_behavioral.py` | `docs/fee_behavioral.json` | RQ-D (T2) |
| 2 | Entity concentration, top-20k tail | `34_entity_funding.py` winners→fetch→cluster | `docs/entity_concentration*.json` | T1 |
| 3 | Winning-cluster / syndicate graph | `35_winning_graph.py` | `docs/winning_graph.json` | graph idea |

The orchestrator waits for job 0 to finish, retries it with 16 buckets if it was killed, then
runs 1→3 with continue-on-error. Progress: `data/logs/overnight/_progress.log`. T1 fetch uses
the internet (Polygonscan, vetted keys only, IP-penalty pre-flight, skip-if-exists = resumable).

## Already-completed inputs (this session)
- Concentration `docs/concentration.json` (both sides; Gini 0.954/0.946; top-1% ~70%).
- Maker economics `docs/maker_economics.json` (T3: adverse selection −0.58; professional elite).
- Platform PnL v1 `docs/platform_wide.json` (−$86M) and v2 `docs/v2_platform.json` (net −$129.5M).
- Skill subset validations (z sd 1.6, symmetric ~13% inflation, persistence rho +0.11).
- Confirmatory H1–H4, favorite–longshot, efficiency, fee incidence — all on disk.

## Synthesis (done by the model as results land / in the morning)
- `docs/research_framing_2026-09-05.md` — the adapted RQ line (fee experiment lead; concentration
  as replicated backdrop; skill-null reconciliation; detection ceiling).
- `docs/research_ideas_2026-09-05.md` — methods + novel topics (T1/T2/T3 + graph).
- A concurrent literature-deepening pass positions the four pivot topics.
- Final: integrate every result into a single coherent, publishable narrative with the RQ set,
  each RQ's evidence + novelty + caveats, and the recommended paper framing.

## Guardrails honoured
- No concurrent heavy jobs (OOM). Network/LLM work (literature) may overlap (no memory).
- Vetted Etherscan keys only (ETHERSCAN_KEY,4,5,6); never the dead 2/3/7; penalty pre-flight.
- All results carry survivorship / taker-tail / cross-era caveats; nothing overclaimed.
