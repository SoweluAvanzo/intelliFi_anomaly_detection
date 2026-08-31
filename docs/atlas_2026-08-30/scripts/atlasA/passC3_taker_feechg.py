import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
import pandas as pd, datetime as dt, time, os
con=connect()   # PRAGMA memory_limit='4GB', threads=4, scratch temp dir
mf=pd.read_parquet(f'{ATLAS}/market_fee_start.parquet', columns=['condition_id','fee_share_life'])
mf=mf[mf.fee_share_life>=0.5][['condition_id']]
con.register('feechg', mf); con.execute("CREATE TABLE fc AS SELECT condition_id FROM feechg"); del mf
os.makedirs(f'{SCR}/takerc3', exist_ok=True)
t=time.time(); BUDGET=float(sys.argv[1]) if len(sys.argv)>1 else 1e9
w=dt.date(2026,1,5); wend=dt.date(2026,4,20)
while w<=wend:
    outp=f'{SCR}/takerc3/tk_{w}.parquet'
    if os.path.exists(outp): w+=dt.timedelta(days=7); continue
    if time.time()-t>BUDGET: print('BUDGET_STOP', flush=True); sys.exit(0)
    dfs=day_files(w, w+dt.timedelta(days=6)); files=[f for _,fs in dfs for f in fs]
    df=con.execute(f"""SELECT taker, count(*) n_fills_fc, sum(usdc_amount) notional_fc,
        sum(CASE WHEN fee_usdc=0 THEN usdc_amount ELSE 0 END) notional_fc_zerofee,
        sum(least(price,1-price)*usdc_amount/price) fee_base_fc, sum({FEE_VAL}) fee_val_fc
        FROM ({union_sql(files)}) r SEMI JOIN fc ON fc.condition_id=r.condition_id WHERE price>0 AND price<1 AND usdc_amount>0 GROUP BY 1""").df()
    df['week']=pd.Timestamp(w); df.to_parquet(outp, index=False)
    print(w, len(df), f'{time.time()-t:.0f}s', flush=True); w+=dt.timedelta(days=7)
print('ALL_DONE')
pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'{SCR}/takerc3/tk_*.parquet'))]).to_parquet(f'{ATLAS}/taker_week_feecharging.parquet', index=False)
