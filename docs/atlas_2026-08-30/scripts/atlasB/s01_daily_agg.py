import duckdb, time
S="/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasB"
con=duckdb.connect()
con.execute("SET enable_progress_bar=false"); con.execute("PRAGMA threads=8"); con.execute("SET TimeZone='UTC'")
con.execute(f"SET temp_directory='{S}/duck_tmp'"); con.execute("SET memory_limit='18GB'")
G="'data/external/polymarket_v1/{d}/2025_1[0-2]_*.parquet','data/external/polymarket_v1/{d}/2026_0[1-4]_*.parquet'"
for d in ["daily_aligned","daily_aligned_multi"]:
    t=time.time()
    con.execute(f"""
    COPY (
      SELECT CAST(to_timestamp(block_timestamp) AS DATE) AS d,
             category, category_refined, neg_risk,
             (fee_usdc>0) AS fee_flag,
             taker_base_fee, maker_base_fee,
             count(*) AS n_fills, sum(usdc_amount) AS vol, sum(fee_usdc) AS fee_sum,
             sum(CASE WHEN maker=taker THEN 1 ELSE 0 END) AS self_n,
             sum(CASE WHEN maker=taker THEN usdc_amount ELSE 0 END) AS self_vol,
             count(DISTINCT condition_id) AS n_cond,
             count(DISTINCT taker) AS n_takers,
             sum(CASE WHEN taker_direction='BUY' THEN usdc_amount ELSE 0 END) AS buy_vol,
             sum(usdc_amount*price*(1-price)) AS sum_pq_vol
      FROM read_parquet([{G.format(d=d)}])
      GROUP BY ALL
    ) TO '{S}/daily_agg_{d}.parquet' (FORMAT PARQUET)
    """)
    print(d, "done", round(time.time()-t), "s", flush=True)
