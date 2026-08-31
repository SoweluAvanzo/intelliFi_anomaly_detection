import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
import pandas as pd, datetime as dt, time, os
con=connect()   # 4GB / 4 threads / scratch temp dir
md=pd.read_parquet(f'{ATLAS}/market_class.parquet', columns=['condition_id','cls'])
con.register('mkt_cls', md); con.execute("CREATE TABLE mcls AS SELECT * FROM mkt_cls"); del md
os.makedirs(f'{SCR}/takerc', exist_ok=True)
t=time.time(); BUDGET=float(sys.argv[1]) if len(sys.argv)>1 else 1e9
w=dt.date(2025,9,29); wend=dt.date(2026,4,27)
while w<=wend:
    outp=f'{SCR}/takerc/tk_{w}.parquet'
    if os.path.exists(outp): w+=dt.timedelta(days=7); continue
    if time.time()-t>BUDGET: print('BUDGET_STOP', flush=True); sys.exit(0)
    dfs=day_files(w, w+dt.timedelta(days=6)); files=[f for _,fs in dfs for f in fs]
    if not files: w+=dt.timedelta(days=7); continue
    src=f"""(SELECT taker, maker, coalesce(m.cls,'meta_other') cls, block_timestamp ts, price, usdc_amount usdc, {FEE_VAL} fee_val,
              (fee_usdc>0) is_fee, (taker_base_fee>0) fee_mkt, least(price,1-price)*usdc_amount/price fee_base, (taker_direction='BUY') is_buy
            FROM ({union_sql(files)}) r LEFT JOIN mcls m ON m.condition_id=r.condition_id WHERE price>0 AND price<1 AND usdc_amount>0)"""
    tk=con.execute(f"""SELECT taker, cls, count(*) n_fills, sum(usdc) notional, sum(CASE WHEN is_fee THEN usdc ELSE 0 END) notional_fee,
        sum(CASE WHEN fee_mkt THEN usdc ELSE 0 END) notional_feemkt, sum(fee_val) fee_val, sum(fee_base) fee_base,
        sum(CASE WHEN is_fee THEN fee_base ELSE 0 END) fee_base_fee, sum(CASE WHEN fee_mkt THEN fee_base ELSE 0 END) fee_base_feemkt,
        sum(CASE WHEN is_buy THEN usdc ELSE 0 END) notional_buy, sum(usdc*price) px_w, min(ts) ts_min, max(ts) ts_max
        FROM {src} GROUP BY 1,2""").df()
    tk['week']=pd.Timestamp(w); tk.to_parquet(outp, index=False)
    mk=con.execute(f"""SELECT maker, cls, count(*) n_fills, sum(usdc) notional, sum(CASE WHEN is_fee THEN usdc ELSE 0 END) notional_fee,
        sum(CASE WHEN fee_mkt THEN usdc ELSE 0 END) notional_feemkt, min(ts) ts_min FROM {src} GROUP BY 1,2""").df()
    mk['week']=pd.Timestamp(w); mk.to_parquet(f'{SCR}/takerc/mk_{w}.parquet', index=False)
    print(w, len(dfs),'days', len(tk),'taker-cls', len(mk),'maker-cls', f'{time.time()-t:.0f}s', flush=True)
    w+=dt.timedelta(days=7)
print('ALL_CHUNKS_DONE')
pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'{SCR}/takerc/tk_*.parquet'))]).to_parquet(f'{ATLAS}/taker_week_class.parquet', index=False)
pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'{SCR}/takerc/mk_*.parquet'))]).to_parquet(f'{ATLAS}/maker_week_class.parquet', index=False)
print('done')
