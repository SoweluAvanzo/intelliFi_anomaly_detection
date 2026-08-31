# Stage II, Sample B — cohort schedule (two-week windows of the v2 tape)

Block bounds use 54,559 blocks/day (measured 28 Apr → 29 Aug 2026); exact timestamps come from the crawled blocks.

| cohort | blocks | approx. dates | role |
|---|---|---|---|
| 1 | 88,080,000 – 88,843,826 | 8 Jun – 22 Jun 2026 | confirmatory (pre-registered) |
| 2 | 88,844,000 – 89,607,826 | 22 Jun – 6 Jul | replication |
| 3 | 89,608,000 – 90,371,826 | 6 Jul – 20 Jul | replication |
| 4 | 90,372,000 – 91,135,826 | 20 Jul – 3 Aug | replication |
| 5 | 91,136,000 – 91,899,826 | 3 Aug – 17 Aug | replication |
| 6 | 91,900,000 – latest | 17 Aug – today | replication (open-ended; end block advanced at each relaunch) |
| 0 | 86,126,978 – 88,079,999 | 28 Apr – 8 Jun | v2 genesis gap, crawled last |

Each cohort: crawl (4 keys × 4 segments) → `scripts/11_gate_v2_cohort.py` → analyses per `docs/stage2_preregistration.md` (cohort 1) or the same statistics as replication (cohorts 2+). Chunks already on disk are skipped on every relaunch.
