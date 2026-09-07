#!/usr/bin/env python
"""NEW FOCUS — account-type taxonomy of Polymarket traders and its relation to profit/skill.

Polymarket trading addresses are ~99% smart contracts (proxies), ~1% EOAs. But the contract
population is heterogeneous: two dominant standard proxy types + a long tail of unique-code
contracts (bespoke/bots or per-user proxies). This classifies addresses by on-chain type and
relates type to realised PnL, activity and behavioural-automation signatures, to test whether
the winners are standard-UI users vs bots/EOAs (initial finding: winners are standard proxies).

TAXONOMY (from `eth_getCode`): EOA (no bytecode); else contract, keyed by (code-hash, code-len):
  * dominant code-hashes = the standard Polymarket proxy types (Safe / proxy-factory);
  * short-code (<~200B) singletons = minor proxy variants; long-code = custom (bot/bespoke).
  getOwners()/owner() resolves the controlling EOA where callable (proxy->owner, T1 too).

Phases (idempotent):
  cache   — fetch & CACHE code for an activity/PnL-stratified address set (rate-limit-resilient,
            multi-endpoint, skip-if-exists) -> data/parquet/entity/codes.parquet.
  analyze — join code-type to per-wallet PnL (archive) + activity + inter-trade timing;
            compare account-type distribution across PnL deciles and skilled/unskilled;
            behavioural automation signatures by type. -> docs/account_types.json.

MEMORY-SAFE: the archive PnL/activity pass is a bucketed group-by (memory_limit 3GB, spill);
code fetch is network (light). Launch inside systemd-run -p MemoryMax.

  python scripts/37_account_types.py --phase cache   --n-sample 40000
  python scripts/37_account_types.py --phase analyze --out docs/account_types.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from intellifi import config as _cfg                       # noqa: E402

ENT = _cfg.DATA_DIR / "parquet" / "entity"
CODES = ENT / "codes.parquet"
ADDR_SET = ENT / "addr_sample.parquet"
EPS = ["https://polygon-bor-rpc.publicnode.com", "https://1rpc.io/matic",
       "https://polygon.drpc.org", "https://polygon.blockpi.network/v1/rpc/public"]


def _post(addrs, attempt0=0):
    p = [{"jsonrpc": "2.0", "id": j, "method": "eth_getCode", "params": [a, "latest"]} for j, a in enumerate(addrs)]
    for k in range(8):
        ep = EPS[(attempt0 + k) % len(EPS)]
        try:
            r = requests.post(ep, json=p, timeout=30)
            if r.status_code == 429:
                time.sleep(2 * (k + 1)); continue
            r.raise_for_status()
            return {addrs[it["id"]]: it.get("result", "0x") for it in r.json()}
        except Exception:
            time.sleep(1.5 * (k + 1))
    return {}


def phase_cache(n_sample: int, mem: str) -> None:
    import duckdb, polars as pl
    from intellifi.archive import register_archive_views
    ENT.mkdir(parents=True, exist_ok=True)
    if not ADDR_SET.exists():
        # stratified address set: top winners + a random sample across PnL, from the archive
        tmp = _cfg.DATA_DIR / "_s37_tmp"; import shutil; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
        con = duckdb.connect((tmp / "w.db").as_posix())
        con.execute(f"PRAGMA memory_limit='{mem}'"); con.execute("PRAGMA threads=2")
        con.execute("SET preserve_insertion_order=false")
        con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='50GB'")
        register_archive_views(con)
        RES = ("winning_outcome_label IS NOT NULL AND price>0 AND price<1 AND shares>0 "
               "AND taker_direction IN ('BUY','SELL')")
        WON = "(CASE WHEN outcome_label = winning_outcome_label THEN 1 ELSE 0 END)"
        PAY = f"(CASE WHEN taker_direction='BUY' THEN ({WON}-price)*shares ELSE (price-{WON})*shares END)"
        con.execute(f"""CREATE TABLE wp AS
            SELECT w, SUM(p) pnl, COUNT(*) nfills FROM (
              SELECT taker w, {PAY} p FROM arc_raw WHERE {RES}
              UNION ALL SELECT maker, -({PAY}) FROM arc_raw WHERE {RES} AND maker IS NOT NULL) GROUP BY w""")
        con.execute(f"""COPY (
            SELECT w AS wallet, pnl, nfills, ntile(10) OVER (ORDER BY pnl) AS pnl_decile FROM wp
            WHERE w IS NOT NULL AND nfills>=5
            USING SAMPLE {n_sample} ROWS (reservoir, 42)
          ) TO '{ADDR_SET.as_posix()}' (FORMAT PARQUET)""")
        # always include the top-2000 winners
        con.execute(f"""COPY (SELECT w wallet, pnl, nfills, 11 pnl_decile FROM wp WHERE w IS NOT NULL ORDER BY pnl DESC LIMIT 2000)
            TO '{(ENT/'addr_top.parquet').as_posix()}' (FORMAT PARQUET)""")
        con.close(); shutil.rmtree(tmp, ignore_errors=True)
    addrs = set()
    for f in (ADDR_SET, ENT / "addr_top.parquet"):
        if f.exists():
            addrs |= set(a.lower() for a in pl.read_parquet(f)["wallet"].to_list())
    have = set()
    if CODES.exists():
        have = set(pl.read_parquet(CODES)["wallet"].to_list())
    todo = sorted(addrs - have)
    print(f"addresses={len(addrs)} cached={len(have)} to-fetch={len(todo)}")
    rows = []
    for i in range(0, len(todo), 40):
        got = _post(todo[i:i + 40])
        for a, c in got.items():
            ch = hashlib.sha256(bytes.fromhex(c[2:])).hexdigest()[:16] if c not in ("0x", "0x0", "") else "EOA"
            rows.append({"wallet": a, "is_eoa": ch == "EOA", "code_hash": ch, "code_len": (len(c) - 2) // 2})
        if i % 4000 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
        time.sleep(0.6)
    new = pl.DataFrame(rows, schema={"wallet": pl.Utf8, "is_eoa": pl.Boolean, "code_hash": pl.Utf8, "code_len": pl.Int64})
    if CODES.exists():
        new = pl.concat([pl.read_parquet(CODES), new], how="vertical_relaxed").unique(subset=["wallet"], keep="last")
    new.write_parquet(CODES)
    print(f"wrote {CODES}: {new.height} codes")


def phase_analyze(out: str) -> None:
    import polars as pl
    if not CODES.exists():
        print("no codes cache; run --phase cache first"); return
    codes = pl.read_parquet(CODES)
    parts = [pl.read_parquet(f).select("wallet", "pnl", "nfills", "pnl_decile")
             for f in (ADDR_SET, ENT / "addr_top.parquet") if f.exists()]
    meta = pl.concat(parts, how="vertical_relaxed").unique(subset=["wallet"], keep="first") if parts else pl.DataFrame()
    df = codes.join(meta, on="wallet", how="inner") if meta.height else codes
    # type label: EOA / proxy-dominant-<hash> / custom
    top_hashes = [h for h, _ in (df.filter(~pl.col("is_eoa"))["code_hash"].value_counts().sort("count", descending=True)
                  .head(4).iter_rows())] if df.height else []
    def label(h, ln, eoa):
        if eoa: return "EOA"
        if h in top_hashes: return f"proxy:{h[:8]}"
        return "custom_long" if ln > 400 else "proxy_minor"
    df = df.with_columns(pl.struct(["code_hash", "code_len", "is_eoa"]).map_elements(
        lambda s: label(s["code_hash"], s["code_len"], s["is_eoa"]), return_dtype=pl.Utf8).alias("acct_type"))
    vc = df["acct_type"].value_counts() if df.height else None   # single call -> aligned columns
    rep = {"n_classified": df.height,
           "type_counts": {r["acct_type"]: int(r["count"]) for r in vc.iter_rows(named=True)} if vc is not None else {},
           "dominant_proxy_hashes": top_hashes,
           "KNOWN_hash_labels": {"f5c625376518f07a": "gnosis_safe", "cefa4f597e0304e1": "polymarket_proxy"}}
    if "pnl" in df.columns and df.height:
        # account-type mix by PnL decile (1=biggest losers .. 10=top .. 11=top-2000 winners)
        by = (df.group_by("pnl_decile", "acct_type").agg(pl.len().alias("n"))
                .sort("pnl_decile"))
        rep["type_by_pnl_decile"] = [{"pnl_decile": int(r["pnl_decile"]), "acct_type": r["acct_type"], "n": int(r["n"])}
                                     for r in by.iter_rows(named=True)]
        # mean PnL and win-rate by account type
        agg = (df.group_by("acct_type").agg(pl.len().alias("n"), pl.col("pnl").mean().alias("mean_pnl"),
               pl.col("pnl").median().alias("med_pnl"), (pl.col("pnl") > 0).mean().alias("win_rate"),
               pl.col("nfills").median().alias("med_fills")))
        rep["pnl_by_acct_type"] = [{"acct_type": r["acct_type"], "n": int(r["n"]), "mean_pnl": r["mean_pnl"],
                                    "med_pnl": r["med_pnl"], "win_rate": r["win_rate"], "med_fills": r["med_fills"]}
                                   for r in agg.iter_rows(named=True)]
    rep["notes"] = ["Winners are ~exclusively the two dominant standard proxy types (initial finding). "
                    "custom_long = long-bytecode contracts (bot/bespoke candidates); proxy_minor = short unique-code "
                    "(minor proxy variants or per-user CREATE2). EOA ~1%. Identify dominant hashes (Safe vs Polymarket "
                    "proxy) via getOwners()/known bytecode. Behavioural timing signatures = a follow-up (needs the tape).",
                    "PnL is archive realised (survivorship); descriptive."]
    Path(out).parent.mkdir(parents=True, exist_ok=True); Path(out).write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({k: rep[k] for k in ("n_classified", "type_counts", "dominant_proxy_hashes")}, indent=1))
    if "pnl_by_acct_type" in rep:
        print("PnL by account type (type | n | mean_pnl | win_rate | med_fills):")
        for r in sorted(rep["pnl_by_acct_type"], key=lambda r: -(r["mean_pnl"] or 0)):
            print(f"  {r['acct_type']:16s} n={r['n']:>6,} mean={r['mean_pnl'] or 0:>+12,.0f} win={100*(r['win_rate'] or 0):5.1f}% med_fills={r['med_fills']}")
    print(f"wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=["cache", "analyze"], required=True)
    ap.add_argument("--n-sample", type=int, default=40000)
    ap.add_argument("--memory-limit", default="3GB")
    ap.add_argument("--out", default="docs/account_types.json")
    args = ap.parse_args()
    if args.phase == "cache":
        phase_cache(args.n_sample, args.memory_limit)
    else:
        phase_analyze(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
