# Q4: per-day extraction from daily_aligned_multi: hourly last YES price per candidate + per-condition metadata
import duckdb, time, glob, os
S="/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasB"
os.makedirs(f"{S}/multi_hourly", exist_ok=True); os.makedirs(f"{S}/multi_cond", exist_ok=True)
con=duckdb.connect()
con.execute("SET enable_progress_bar=false"); con.execute("PRAGMA threads=4"); con.execute("SET TimeZone='UTC'")
files=sorted(glob.glob('data/external/polymarket_v1/daily_aligned_multi/2025_1[0-2]_*.parquet')+glob.glob('data/external/polymarket_v1/daily_aligned_multi/2026_0[1-4]_*.parquet'))
t=time.time()
for f in files:
    day=os.path.basename(f)[:-8]
    if os.path.exists(f"{S}/multi_cond/{day}.parquet"): continue
    con.execute(f"""COPY (
      SELECT neg_risk_market_id, condition_id, asset_id, category, category_refined,
             (block_timestamp//3600)*3600 AS hr,
             arg_max(price, block_timestamp) AS last_px,
             arg_max(price, block_timestamp) FILTER (WHERE taker_direction='BUY') AS last_buy_px,
             arg_max(price, block_timestamp) FILTER (WHERE taker_direction='SELL') AS last_sell_px,
             count(*) AS n_fills, sum(usdc_amount) AS vol,
             sum(CASE WHEN fee_usdc>0 THEN usdc_amount ELSE 0 END) AS fee_vol,
             max(taker_base_fee) AS tbf
      FROM read_parquet('{f}') WHERE outcome_seq=1
      GROUP BY ALL) TO '{S}/multi_hourly/{day}.parquet' (FORMAT PARQUET)""")
    con.execute(f"""COPY (
      SELECT neg_risk_market_id, condition_id, category, category_refined, market_slug,
             min(block_timestamp) AS first_ts, max(block_timestamp) AS last_ts,
             count(*) AS n_fills, sum(usdc_amount) AS vol,
             sum(CASE WHEN maker=taker THEN usdc_amount ELSE 0 END) AS self_vol,
             sum(CASE WHEN fee_usdc>0 THEN usdc_amount ELSE 0 END) AS fee_vol,
             sum(fee_usdc) AS fee_sum,
             max(taker_base_fee) AS tbf,
             min(opens_at) AS opens_at, min(close_at) AS close_at, min(resolved_at) AS resolved_at,
             max(resolution_status) AS resolution_status, max(winning_outcome_label) AS winning_outcome_label,
             count(DISTINCT asset_id) AS n_assets
      FROM read_parquet('{f}') GROUP BY ALL) TO '{S}/multi_cond/{day}.parquet' (FORMAT PARQUET)""")
print("done", len(files), round(time.time()-t), "s", flush=True)
