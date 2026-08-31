import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
import pandas as pd, time, os
con=connect('13GB')
md=pd.read_parquet(f'{ATLAS}/market_class.parquet', columns=['condition_id','cls'])
con.register('mkt_cls', md); con.execute("CREATE TABLE mcls AS SELECT * FROM mkt_cls")
os.makedirs(f'{SCR}/takerm', exist_ok=True)
t=time.time(); BUDGET=float(sys.argv[1]) if len(sys.argv)>1 else 1e9
for ym in ['2025_10','2025_11','2025_12','2026_01','2026_02','2026_03','2026_04']:
    outp=f'{SCR}/takerm/tm_{ym}.parquet'
    if os.path.exists(outp): continue
    if time.time()-t>BUDGET: print('BUDGET_STOP', flush=True); sys.exit(0)
    files=glob.glob(f'{EXT}/daily_aligned/{ym}_*.parquet')+glob.glob(f'{EXT}/daily_aligned_multi/{ym}_*.parquet')
    con.execute("DROP TABLE IF EXISTS wk")
    con.execute(f"""CREATE TABLE wk AS
      SELECT taker tk, coalesce(m.cls,'meta_other') cls, hash(asset_id) aid, block_timestamp ts, price, (taker_direction='BUY') is_buy,
        usdc_amount usdc, {FEE_VAL} fee_val, (fee_usdc>0) is_fee, (taker_base_fee>0) fee_mkt, least(price,1-price)*usdc_amount/price fee_base, w.condition_id cid, hash(maker) mk
      FROM ({union_sql(files)}) w LEFT JOIN mcls m USING (condition_id) WHERE price>0 AND price<1 AND usdc_amount>0""")
    con.execute("CREATE OR REPLACE TABLE ords AS SELECT tk, cls, ts, aid, is_buy, sum(usdc) sz FROM wk GROUP BY ALL")
    df=con.execute(f"""
      SELECT '{ym}' ym, tk taker, cls, count(*) n_fills, sum(usdc) notional, sum(CASE WHEN is_fee THEN usdc ELSE 0 END) notional_fee,
        sum(CASE WHEN fee_mkt THEN usdc ELSE 0 END) notional_feemkt, sum(fee_val) fee_val, sum(fee_base) fee_base,
        sum(CASE WHEN is_fee THEN fee_base ELSE 0 END) fee_base_fee, sum(CASE WHEN fee_mkt THEN fee_base ELSE 0 END) fee_base_feemkt,
        sum(CASE WHEN is_buy THEN usdc ELSE 0 END) notional_buy, count(DISTINCT cid) n_markets, count(DISTINCT mk) n_counterparties,
        min(ts) ts_min, max(ts) ts_max, sum(usdc*price) px_w
      FROM wk GROUP BY 1,2,3""").df()
    o=con.execute("SELECT tk taker, cls, count(*) n_orders, avg(sz) ord_mean, median(sz) ord_med FROM ords GROUP BY 1,2").df()
    df=df.merge(o,on=['taker','cls'],how='left')
    # maker-side monthly aggregates (for provider composition)
    mk=con.execute(f"""SELECT '{ym}' ym, mk maker_h, cls, count(*) n_fills, sum(usdc) notional, sum(CASE WHEN is_fee THEN usdc ELSE 0 END) notional_fee,
        sum(CASE WHEN fee_mkt THEN usdc ELSE 0 END) notional_feemkt, count(DISTINCT cid) n_markets FROM wk GROUP BY 1,2,3""").df()
    df.to_parquet(outp, index=False); mk.to_parquet(f'{SCR}/takerm/mk_{ym}.parquet', index=False)
    print(ym, len(df), len(mk), f'{time.time()-t:.0f}s', flush=True)
pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'{SCR}/takerm/tm_*.parquet'))]).to_parquet(f'{ATLAS}/taker_month_class.parquet', index=False)
pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'{SCR}/takerm/mk_*.parquet'))]).to_parquet(f'{ATLAS}/maker_month_class.parquet', index=False)
print('done')
