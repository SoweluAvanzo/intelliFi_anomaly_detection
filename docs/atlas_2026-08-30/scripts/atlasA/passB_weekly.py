import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
from feeclass import map_market
import pandas as pd, datetime as dt, time, os
con=connect('13GB')
# market -> class table from market_day
md=pd.read_parquet(f'{ATLAS}/market_day.parquet', columns=['condition_id','category','category_refined','market_slug'])
md=md.drop_duplicates('condition_id')
md['cls']=[map_market(a,b,c) for a,b,c in zip(md.category, md.category_refined, md.market_slug)]
md[['condition_id','category','category_refined','market_slug','cls']].to_parquet(f'{ATLAS}/market_class.parquet', index=False)
con.register('mkt_cls', md[['condition_id','cls']])
con.execute("CREATE TABLE mcls AS SELECT * FROM mkt_cls")
os.makedirs(f'{SCR}/weekly', exist_ok=True)
w0=dt.date(2025,9,29); wend=dt.date(2026,4,27)
t=time.time(); BUDGET=float(sys.argv[1]) if len(sys.argv)>1 else 1e9
w=w0
while w<=wend:
    outp=f'{SCR}/weekly/mw_{w}.parquet'
    if os.path.exists(outp): w+=dt.timedelta(days=7); continue
    if time.time()-t>BUDGET: print('BUDGET_STOP', flush=True); sys.exit(0)
    dfs=day_files(w, w+dt.timedelta(days=6))
    files=[f for _,fs in dfs for f in fs]
    if not files: w+=dt.timedelta(days=7); continue
    con.execute("DROP TABLE IF EXISTS wk")
    con.execute(f"""CREATE TABLE wk AS
      SELECT condition_id cid, category cat, hash(asset_id) aid, block_timestamp ts, price, hash(maker) mk, hash(taker) tk,
        (taker_direction='BUY') is_buy, usdc_amount usdc, {FEE_VAL} fee_val, (fee_usdc>0) is_fee, (taker_base_fee>0) fee_mkt,
        least(price,1-price)*usdc_amount/price fee_base
      FROM ({union_sql(files)}) WHERE price>0 AND price<1 AND usdc_amount>0""")
    con.execute("CREATE OR REPLACE TABLE wk2 AS SELECT w.cid, w.cat, w.aid, w.ts, w.price, w.mk, w.tk, w.is_buy, w.usdc, w.fee_val, w.is_fee, w.fee_mkt, w.fee_base, coalesce(m.cls,'meta_other') cls FROM wk w LEFT JOIN mcls m ON m.condition_id=w.cid")
    con.execute("DROP TABLE wk")
    # orders
    con.execute("CREATE OR REPLACE TABLE ords AS SELECT cid, cat, cls, tk, ts, aid, is_buy, sum(usdc) sz, count(*) nf, max(is_fee) is_fee FROM wk2 GROUP BY ALL")
    # minute spread pairs
    con.execute("""CREATE OR REPLACE TABLE mins AS
      SELECT cid, cat, cls, aid, ts//60 mn,
        sum(CASE WHEN is_buy THEN usdc END) vb, sum(CASE WHEN NOT is_buy THEN usdc END) vs,
        sum(CASE WHEN is_buy THEN usdc END)/sum(CASE WHEN is_buy THEN usdc/price END) pb,
        sum(CASE WHEN NOT is_buy THEN usdc END)/sum(CASE WHEN NOT is_buy THEN usdc/price END) ps
      FROM wk2 GROUP BY ALL""")
    # maker volumes
    con.execute("CREATE OR REPLACE TABLE mkv AS SELECT cid, cat, cls, mk, sum(usdc) v FROM wk2 GROUP BY ALL")
    def agg(level):
        key={'m':'cid','c':'cat','k':'cls'}[level]
        base=con.execute(f"""
          SELECT {key} AS key, count(*) n_fills, sum(usdc) notional, sum(CASE WHEN is_fee THEN 1 ELSE 0 END) n_fee_fills,
            sum(CASE WHEN is_fee THEN usdc ELSE 0 END) notional_fee, sum(fee_val) fee_val, sum(fee_base) fee_base,
            sum(CASE WHEN is_fee THEN fee_base ELSE 0 END) fee_base_fee,
            sum(CASE WHEN fee_mkt THEN usdc ELSE 0 END) notional_feemkt,
            sum(CASE WHEN is_buy THEN usdc ELSE 0 END) notional_buy,
            count(DISTINCT tk) n_takers, count(DISTINCT mk) n_makers, count(DISTINCT cid) n_markets,
            sum(usdc*price) px_w, avg(price) px_mean, median(usdc) fill_med, avg(usdc) fill_mean
          FROM wk2 GROUP BY 1""").df()
        o=con.execute(f"""SELECT {key} AS key, count(*) n_orders, avg(sz) ord_mean, median(sz) ord_med, quantile_cont(sz,0.9) ord_p90,
            avg(nf) fills_per_order, sum(CASE WHEN sz>=1000 THEN 1 ELSE 0 END) n_orders_1k FROM ords GROUP BY 1""").df()
        s=con.execute(f"""SELECT {key} AS key, count(*) n_minpairs, sum((pb-ps)*least(vb,vs)) sp_w_sum, sum(least(vb,vs)) sp_w,
            sum(pb-ps) sp_sum, sum((pb-ps)/((pb+ps)/2)*least(vb,vs)) rsp_w_sum,
            sum(CASE WHEN pb>ps THEN 1 ELSE 0 END) n_pos FROM mins WHERE vb>0 AND vs>0 GROUP BY 1""").df()
        h=con.execute(f"""WITH r AS (SELECT {key} AS key, v, sum(v) OVER (PARTITION BY {key}) tot, row_number() OVER (PARTITION BY {key} ORDER BY v DESC) rk FROM mkv)
            SELECT key, sum((v/tot)*(v/tot)) hhi, sum(CASE WHEN rk<=5 THEN v/tot ELSE 0 END) top5, sum(CASE WHEN rk<=1 THEN v/tot ELSE 0 END) top1, count(*) n_makers2 FROM r GROUP BY 1""").df()
        df=base.merge(o,on='key',how='left').merge(s,on='key',how='left').merge(h,on='key',how='left')
        df.insert(0,'week',pd.Timestamp(w)); df['n_days']=len(dfs)
        return df
    mw=agg('m'); mw=mw.rename(columns={'key':'condition_id'})
    cw=agg('c'); cw=cw.rename(columns={'key':'category'})
    kw=agg('k'); kw=kw.rename(columns={'key':'cls'})
    cw.to_parquet(f'{SCR}/weekly/cw_{w}.parquet', index=False); kw.to_parquet(f'{SCR}/weekly/kw_{w}.parquet', index=False); mw.to_parquet(outp, index=False)
    print(w, len(dfs), 'days', int(mw.n_fills.sum()), 'fills', len(mw), 'mkts', f'{time.time()-t:.0f}s', flush=True)
    w+=dt.timedelta(days=7)
print('ALL_WEEKS_DONE')
for tag,name in [('mw','market_week'),('cw','category_week'),('kw','class_week')]:
    fs=sorted(glob.glob(f'{SCR}/weekly/{tag}_*.parquet'))
    pd.concat([pd.read_parquet(f) for f in fs]).to_parquet(f'{ATLAS}/{name}.parquet', index=False)
print('done')
