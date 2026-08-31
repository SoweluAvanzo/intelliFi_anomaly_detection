import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
import pandas as pd, datetime as dt, time
con=connect()
t=time.time()
# monthly overview by category x fee params, one pass per month
rows=[]
for ym in ['2025_10','2025_11','2025_12','2026_01','2026_02','2026_03','2026_04']:
    files=glob.glob(f'{EXT}/daily_aligned/{ym}_*.parquet')+glob.glob(f'{EXT}/daily_aligned_multi/{ym}_*.parquet')
    q=f"""
    SELECT '{ym}' AS ym, src, category, category_refined, taker_base_fee, maker_base_fee,
      count(*) n_fills, sum(usdc_amount) notional,
      sum(CASE WHEN fee_usdc>0 THEN 1 ELSE 0 END) n_fee_fills,
      sum({FEE_VAL}) fee_val,
      count(DISTINCT condition_id) n_markets,
      sum(CASE WHEN taker_direction='BUY' THEN 1 ELSE 0 END) n_buy,
      min(block_timestamp) ts_min, max(block_timestamp) ts_max
    FROM ({union_sql(files)}) GROUP BY ALL"""
    df=con.execute(q).df(); rows.append(df); print(ym, len(df), df.n_fills.sum(), f'{time.time()-t:.0f}s', flush=True)
ov=pd.concat(rows); ov.to_parquet(f'{ATLAS}/explore_month_category_feeparams.parquet', index=False)
print(ov.groupby('ym')[['n_fills','notional','n_fee_fills','fee_val','n_markets']].sum().to_string())
print(ov.groupby(['taker_base_fee','maker_base_fee'])[['n_fills','n_fee_fills','fee_val']].sum().to_string())
print('n categories', ov.category.nunique(), 'n refined', ov.category_refined.nunique())
