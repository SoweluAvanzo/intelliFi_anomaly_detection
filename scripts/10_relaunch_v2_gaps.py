#!/usr/bin/env python
"""Relaunch v2 tape crawlers on whatever block ranges are still missing.

Reads ``data/parquet/tape_v2/blocks=<a>-<b>`` partitions, computes the gaps in
the cohort plan (docs/stage2_cohorts.md), splits them into one segment per
crawler slot (4 per key by default, ``--max-calls`` each so 4 x 25k = the free
daily quota), and launches ``scripts/10_fetch_v2_tape.py`` detached via
``setsid``.  Idempotent: skips slots whose key already has running crawlers
unless ``--force``.  Meant to be run once a day just after 00:00 UTC.
"""
from __future__ import annotations
import argparse, os, re, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TAPE = REPO / "data" / "parquet" / "tape_v2"
LOGS = Path(os.getenv("INTELLIFI_V2_LOG_DIR", REPO / "data" / "logs"))
GENESIS = 86_126_978
COHORT_START = 88_080_000          # cohort 1 start (docs/stage2_cohorts.md)
KEYS = ["ETHERSCAN_KEY", "ETHERSCAN_KEY2", "ETHERSCAN_KEY3", "ETHERSCAN_KEY4", "ETHERSCAN_KEY5", "ETHERSCAN_KEY6"]


def on_disk() -> list[tuple[int, int]]:
    rs = []
    for d in TAPE.iterdir() if TAPE.exists() else []:
        m = re.match(r"blocks=(\d+)-(\d+)$", d.name)
        if m and (d / "part.parquet").exists():
            rs.append((int(m.group(1)), int(m.group(2))))
    return sorted(rs)


def gaps(lo: int, hi: int, rs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out, cur = [], lo
    for a, b in rs:
        if b < lo or a > hi:
            continue
        if a > cur:
            out.append((cur, a - 1))
        cur = max(cur, b + 1)
    if cur <= hi:
        out.append((cur, hi))
    return out


def latest_block(api_key: str) -> int:
    sys.path.insert(0, str(REPO / "src"))
    from intellifi.onchain import Polygonscan
    return Polygonscan(api_key=api_key, max_calls=None).latest_block()


def split(ranges: list[tuple[int, int]], n: int) -> list[list[tuple[int, int]]]:
    """Greedy split of ranges into n contiguous-ish buckets of similar block count."""
    total = sum(b - a + 1 for a, b in ranges)
    target = max(1, total // n)
    buckets, cur, cur_n = [], [], 0
    for a, b in ranges:
        while b - a + 1 > 0:
            room = target - cur_n
            if len(buckets) == n - 1:  # last bucket takes the rest
                cur.append((a, b)); cur_n += b - a + 1; break
            take = min(b - a + 1, room)
            cur.append((a, a + take - 1)); cur_n += take; a += take
            if cur_n >= target:
                buckets.append(cur); cur, cur_n = [], 0
    if cur:
        buckets.append(cur)
    return [b for b in buckets if b]


def running(key_env: str) -> int:
    """Count live crawler processes for a key by scanning /proc directly."""
    n = 0
    for pid in Path("/proc").iterdir():
        if not pid.name.isdigit():
            continue
        try:
            args = (pid / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if len(args) < 3 or not args[0].endswith(b"python") or b"10_fetch_v2_tape" not in args[2]:
            continue
        sa = [a.decode(errors="replace") for a in args]
        key = sa[sa.index("--api-key-env") + 1] if "--api-key-env" in sa else "ETHERSCAN_KEY"
        if key == key_env:
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-key", type=int, default=4)
    ap.add_argument("--max-calls", type=int, default=25_000)
    ap.add_argument("--min-interval", type=float, default=1.4)
    ap.add_argument("--include-genesis", action="store_true", help="also crawl 86,126,978 .. cohort-1 start")
    ap.add_argument("--to-block", type=int, default=None, help="default: latest block from Etherscan")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="launch even if crawlers for that key are running")
    ap.add_argument("--skip-keys", default="", help="comma-separated key env names to leave alone")
    args = ap.parse_args()

    # keys come from .env* via intellifi.config
    sys.path.insert(0, str(REPO / "src"))
    from intellifi import config  # noqa: F401  (loads .env files)
    skip = {k.strip() for k in args.skip_keys.split(',') if k.strip()}
    # keys reserved for the remote (Helsinki) box — never run them locally (per-key rate limit is global)
    skip |= {k.strip() for k in os.getenv('INTELLIFI_REMOTE_KEYS', 'ETHERSCAN_KEY5,ETHERSCAN_KEY6').split(',') if k.strip()}
    keys = [k for k in KEYS if os.getenv(k) and k not in skip]
    if not keys:
        print("no Etherscan keys in environment", file=sys.stderr); return 2
    hi = args.to_block or latest_block(os.environ[keys[0]])
    rs = on_disk()
    missing = gaps(COHORT_START, hi, rs)
    if args.include_genesis:
        missing = gaps(GENESIS, COHORT_START - 1, rs) + missing
    n_blocks = sum(b - a + 1 for a, b in missing)
    print(f"to_block={hi:,} partitions={len(rs)} missing_ranges={len(missing)} missing_blocks={n_blocks:,} (~{n_blocks/2000:.0f} chunks)")
    if not missing:
        return 0
    slots = [k for k in keys for _ in range(args.per_key)]
    segs = split(missing, len(slots))
    LOGS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M", time.gmtime())
    launched = 0
    for i, (key, seg) in enumerate(zip(slots, segs)):
        if not args.force and running(key) >= args.per_key:
            print(f"slot {i} {key}: {args.per_key} crawlers already running, skip"); continue
        # one process per contiguous range in the segment, run sequentially in a shell
        cmds = []
        for a, b in seg:
            cmd = [str(REPO / ".venv/bin/python"), "-u", "scripts/10_fetch_v2_tape.py",
                   "--from-block", str(a), "--to-block", str(b), "--chunk-blocks", "2000",
                   "--max-calls", str(args.max_calls), "--min-interval", str(args.min_interval)]
            if key != "ETHERSCAN_KEY":
                cmd += ["--api-key-env", key]
            cmds.append(" ".join(cmd))
        shell = " && ".join(cmds)
        log = LOGS / f"v2_{stamp}_slot{i}_{key}.log"
        print(f"slot {i} {key}: {sum(b-a+1 for a,b in seg):,} blocks in {len(seg)} ranges -> {log.name}")
        if not args.dry_run:
            subprocess.Popen(["setsid", "nohup", "bash", "-c", shell], cwd=REPO,
                             stdout=open(log, "ab"), stderr=subprocess.STDOUT, start_new_session=True)
            launched += 1
    print("launched", launched)
    return 0


if __name__ == "__main__":
    sys.exit(main())
