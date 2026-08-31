# Q3 (b) one-step round trips and (c) pair aggregates, per day file, daily_aligned
import duckdb, time, glob, os, sys
BUDGET=float(sys.argv[1]) if len(sys.argv)>1 else 1e9
S="/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasB"
for sub in ["rt_daily","pairs_daily"]: os.makedirs(f"{S}/{sub}", exist_ok=True)
con=duckdb.connect()
con.execute("SET enable_progress_bar=false"); con.execute("PRAGMA threads=8"); con.execute("SET TimeZone='UTC'")
con.execute(f"SET temp_directory='{S}/duck_tmp'"); con.execute("SET memory_limit='16GB'")
files=sorted(glob.glob('data/external/polymarket_v1/daily_aligned/2025_1[0-2]_*.parquet')+glob.glob('data/external/polymarket_v1/daily_aligned/2026_0[1-4]_*.parquet'))
t0=time.time()
for f in files:
    day=os.path.basename(f)[:-8]
    if os.path.exists(f"{S}/pairs_daily/{day}.parquet"): continue
    if time.time()-t0>BUDGET: print('budget reached', flush=True); break
    t=time.time()
    con.execute("DROP TABLE IF EXISTS d")
    con.execute(f"""CREATE TEMP TABLE d AS SELECT asset_id, block_timestamp AS ts, price, maker, taker, taker_direction AS dir,
        usdc_amount AS usdc, usdc_amount/price AS sh, (fee_usdc>0) AS fee_flag, category_refined AS cat
        FROM read_parquet('{f}') WHERE price>0 AND usdc_amount>0""")
    # (b) taker orders -> one-step round trips
    con.execute(f"""COPY (
      WITH o AS (
        SELECT taker, asset_id, ts, dir, cat, sum(usdc) usdc, sum(sh) sh, max(fee_flag) fee_flag
        FROM d GROUP BY ALL),
      w AS (
        SELECT *,
          lag(ts)  OVER win AS p_ts, lag(dir)  OVER win AS p_dir, lag(sh)  OVER win AS p_sh,
          lead(ts) OVER win AS n_ts, lead(dir) OVER win AS n_dir, lead(sh) OVER win AS n_sh
        FROM o WINDOW win AS (PARTITION BY taker, asset_id ORDER BY ts, dir)),
      fl AS (
        SELECT *,
          (p_ts IS NOT NULL AND p_dir<>dir AND ts-p_ts<=600 AND least(sh,p_sh)/greatest(sh,p_sh)>=0.5) AS close_leg,
          (n_ts IS NOT NULL AND n_dir<>dir AND n_ts-ts<=600 AND least(sh,n_sh)/greatest(sh,n_sh)>=0.5) AS open_leg
        FROM w)
      SELECT DATE '{day.replace('_','-')}' AS d, cat, fee_flag,
        count(*) n_orders, sum(usdc) vol,
        sum(CASE WHEN close_leg THEN usdc ELSE 0 END) rt_close_vol,
        sum(CASE WHEN close_leg OR open_leg THEN usdc ELSE 0 END) rt_any_vol,
        sum(CASE WHEN close_leg THEN 1 ELSE 0 END) rt_close_n,
        sum(CASE WHEN close_leg OR open_leg THEN 1 ELSE 0 END) rt_any_n,
        sum(CASE WHEN close_leg AND ts-p_ts<=60 THEN usdc ELSE 0 END) rt_close_vol_60s,
        count(DISTINCT taker) n_takers,
        count(DISTINCT CASE WHEN close_leg THEN taker END) n_rt_takers
      FROM fl GROUP BY ALL) TO '{S}/rt_daily/{day}.parquet.tmp' (FORMAT PARQUET)""")
    # (c) undirected pair aggregates (self-matches kept, flagged by a=b)
    con.execute(f"""COPY (
      SELECT DATE '{day.replace('_','-')}' AS d, least(maker,taker) a, greatest(maker,taker) b, cat, fee_flag,
             count(*) n, sum(usdc) vol
      FROM d GROUP BY ALL) TO '{S}/pairs_daily/{day}.parquet.tmp' (FORMAT PARQUET)""")
    os.replace(f"{S}/rt_daily/{day}.parquet.tmp", f"{S}/rt_daily/{day}.parquet"); os.replace(f"{S}/pairs_daily/{day}.parquet.tmp", f"{S}/pairs_daily/{day}.parquet")
    print(day, round(time.time()-t,1), "s", flush=True)
print("all done", round(time.time()-t0), "s", flush=True)
