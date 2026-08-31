import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
import pandas as pd, time
con=connect()
t=time.time()
out=[]
for ym in ['2025_10','2025_11','2025_12','2026_01','2026_02','2026_03','2026_04']:
    files=glob.glob(f'{EXT}/daily_aligned/{ym}_*.parquet')+glob.glob(f'{EXT}/daily_aligned_multi/{ym}_*.parquet')
    q=f"""
    SELECT condition_id, src, CAST(to_timestamp(block_timestamp) AS DATE) AS d,
      any_value(category) category, any_value(category_refined) category_refined, any_value(neg_risk) neg_risk,
      any_value(neg_risk_market_id) neg_risk_market_id, any_value(market_slug) market_slug,
      max(taker_base_fee) taker_base_fee, max(maker_base_fee) maker_base_fee,
      min(opens_at) opens_at, min(close_at) close_at, min(resolved_at) resolved_at, any_value(resolution_status) resolution_status,
      count(*) n_fills, sum(CASE WHEN fee_usdc>0 THEN 1 ELSE 0 END) n_fee_fills,
      sum(usdc_amount) notional, sum(CASE WHEN fee_usdc>0 THEN usdc_amount ELSE 0 END) notional_fee,
      sum({FEE_VAL}) fee_val, sum(fee_usdc) fee_raw,
      sum(CASE WHEN taker_direction='BUY' THEN usdc_amount ELSE 0 END) notional_buy,
      sum(least(price,1-price)*usdc_amount/price) fee_base,
      count(DISTINCT asset_id) n_assets, min(block_timestamp) ts_min, max(block_timestamp) ts_max
    FROM ({union_sql(files)}) WHERE price>0 GROUP BY 1,2,3"""
    df=con.execute(q).df(); out.append(df); print(ym, len(df), f'{time.time()-t:.0f}s', flush=True)
md=pd.concat(out); md.to_parquet(f'{ATLAS}/market_day.parquet', index=False)
print('rows', len(md), 'markets', md.condition_id.nunique())
