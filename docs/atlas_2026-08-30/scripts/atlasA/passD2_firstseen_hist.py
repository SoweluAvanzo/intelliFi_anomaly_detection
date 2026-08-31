import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
import pandas as pd, time, os
con=connect()
os.makedirs(f'{SCR}/firstseen', exist_ok=True)
t=time.time(); BUDGET=float(sys.argv[1]) if len(sys.argv)>1 else 1e9
allf=sorted(glob.glob(f'{EXT}/daily_aligned/*.parquet')+glob.glob(f'{EXT}/daily_aligned_multi/*.parquet'))
chunks={}
for f in allf:
    tag=os.path.basename(f)[:7]
    if tag>='2025_10': continue      # Oct 2025 onward comes from passC2 chunks
    chunks.setdefault(tag,[]).append(f)
for tag,files in sorted(chunks.items()):
    outp=f'{SCR}/firstseen/fs_{tag}.parquet'
    if os.path.exists(outp): continue
    if time.time()-t>BUDGET: print('BUDGET_STOP', flush=True); sys.exit(0)
    fl="', '".join(files)
    df=con.execute(f"""
      SELECT addr, min(CASE WHEN rl='t' THEN ts END) first_taker, min(CASE WHEN rl='m' THEN ts END) first_maker, min(ts) first_any,
             sum(CASE WHEN rl='t' THEN usdc ELSE 0 END) taker_notional, sum(CASE WHEN rl='m' THEN usdc ELSE 0 END) maker_notional
      FROM (SELECT taker addr, block_timestamp ts, 't' AS rl, usdc_amount usdc FROM read_parquet(['{fl}'], union_by_name=true)
            UNION ALL SELECT maker, block_timestamp, 'm' AS rl, usdc_amount FROM read_parquet(['{fl}'], union_by_name=true))
      GROUP BY 1""").df()
    df['ym']=tag; df.to_parquet(outp, index=False)
    print(tag, len(df), f'{time.time()-t:.0f}s', flush=True)
print('ALL_HIST_DONE')
