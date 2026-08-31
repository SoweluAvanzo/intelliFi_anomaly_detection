# Remote crawler bundle (Polymarket v2 tape)

Offloads part of the on-chain crawl to a non-geoblocked box (the Hetzner Helsinki
host, 46.62.163.188), so it runs in parallel with the local fleet and cannot be
reached by the Italian DNS block. Outbound-only (Etherscan V2 `getLogs`); no
inbound port; data is **pulled** back over SSH.

## Key partition (do not violate)
Etherscan's free limit is **per API key**: 3 req/s and 100k calls/day. The same
key must never run on two machines at once. Assignment:
- **Local machine:** keys 1–4  → cohorts 1–6 (block 88,080,000 → head).
- **This box:** keys 5–6  → v2 genesis gap **86,126,978 → 88,079,999** (~977 chunks).
Ranges are disjoint, so merges never collide.

## Deploy (Docker, isolated compose project)
On the box, in this directory (repo checked out or rsync'd):
```
cp .env.example .env && chmod 600 .env        # paste ETHERSCAN_KEY5/6
docker compose up -d --build                   # project name: polymarket-crawler
docker compose logs -f --tail=50
```
Guardrails baked in: dedicated network `polymarket-crawler_net`, no published
ports, `mem_limit 2500m`, `pids_limit 256`, `cpus 2.0`, `no-new-privileges`,
`cap_drop ALL`, non-root uid 10001, log rotation. Output lands in `./out` (bind).

## Pull results back (run on the LOCAL machine)
```
deploy/remote_crawler/pull_back.sh deploy@46.62.163.188 polymarket-crawler/deploy/remote_crawler/out
```
`--ignore-existing`, content-keyed chunk dirs → idempotent merge into the local
`data/parquet/tape_v2/`. The local `scripts/10_relaunch_v2_gaps.py` then sees the
genesis gap as filled and won't re-crawl it.

## Bare-metal fallback (no Docker)
`setup_remote.sh` (venv) then `run_fleet.sh 86126978 88079999` — same range, uses
`systemd-run --user --scope` caps if available, else `nice`.
