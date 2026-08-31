import duckdb, numpy as np, pandas as pd
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
AT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas'
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
def q(s): r=con.execute(s).fetchall(); print(r); return r
S=2.2; BIN=10000
env=pd.read_parquet(f'{SC}/blockmap_env.parquet').sort_values('bin').reset_index(drop=True)
both=env.cu.notna()&env.cl995.notna()
gap=env.cu-env.cl995
ok=both&(gap>-3600)&(gap<7200)
env['c']=np.where(ok,(env.cu+env.cl995)/2,np.nan)
print('bins usable', ok.sum(), 'of', len(env))
# spike removal: residual vs rolling median
full=pd.DataFrame({'bin':np.arange(env.bin.min(), env.bin.max()+1)}).merge(env[['bin','c']],on='bin',how='left')
for it in range(3):
    med=full.c.rolling(31,center=True,min_periods=3).median()
    bad=(full.c-med).abs()>1800
    print('iter',it,'spikes removed',int(bad.sum()))
    full.loc[bad,'c']=np.nan
full['c_i']=full.c.interpolate(limit_direction='both')
full['c_s']=full.c_i.rolling(5,center=True,min_periods=1).median()
full['blk']=full.bin*BIN+BIN//2
full['t']=S*full.blk+full.c_s
viol=(full.t.diff()<0).sum(); print('monotonic violations', viol)
full['t']=np.maximum.accumulate(full.t.values)
full[['bin','blk','t','c_s']].to_parquet(f'{SC}/blockmap.parquet')
bm=full
print(bm.iloc[::500][['bin','blk','t']].assign(dt=lambda d: pd.to_datetime(d.t,unit='s')).to_string())
spb=bm.t.diff()/bm.blk.diff(); print('spb quantiles', np.nanquantile(spb,[0.01,0.1,0.5,0.9,0.99]))
con.execute(f"CREATE TABLE bm AS SELECT blk, t FROM '{SC}/blockmap.parquet' ORDER BY blk")
con.execute(f"CREATE TABLE m AS SELECT * FROM '{AT}/struct_markets.parquet'")
con.execute(f"CREATE TABLE res AS SELECT condition_id, max(res_block) res_block FROM '{SC}/ctf_res.parquet' GROUP BY 1")
con.execute(f"CREATE TABLE prep AS SELECT condition_id, min(prep_block) prep_block FROM '{SC}/ctf_prep.parquet' GROUP BY 1")
con.execute("""CREATE TABLE rv AS SELECT m.condition_id, m.resolved_at, m.last_ts, m.close_at, r.res_block,
   b1.t + (b2.t-b1.t)*(r.res_block-b1.blk)/(b2.blk-b1.blk) AS t_hat FROM m JOIN res r USING (condition_id)
   ASOF JOIN bm b1 ON r.res_block >= b1.blk ASOF JOIN bm b2 ON r.res_block < b2.blk""")
print('res-block time minus Gamma resolved_at (s): n, q[1,5,25,50,75,95,99]')
q("SELECT count(*), quantile_cont(t_hat - resolved_at, [0.01,0.05,0.25,0.5,0.75,0.95,0.99]) FROM rv WHERE resolved_at IS NOT NULL")
q("SELECT strftime(to_timestamp(resolved_at),'%Y') yr, count(*), round(quantile_cont(t_hat - resolved_at, 0.5)), round(quantile_cont(abs(t_hat - resolved_at), 0.9)) FROM rv WHERE resolved_at IS NOT NULL GROUP BY 1 ORDER BY 1")
print('res-block time minus last fill (s):')
q("SELECT count(*), quantile_cont(t_hat - last_ts, [0.001,0.01,0.05,0.25,0.5,0.75]) FROM rv")
con.execute("""CREATE TABLE pv AS SELECT m.condition_id, m.opens_at, m.first_ts, p.prep_block, b1.t + (b2.t-b1.t)*(p.prep_block-b1.blk)/(b2.blk-b1.blk) AS t_hat FROM m JOIN prep p USING (condition_id)
   ASOF JOIN bm b1 ON p.prep_block >= b1.blk ASOF JOIN bm b2 ON p.prep_block < b2.blk""")
print('prep-block time minus first fill (s) (should be <=0):'); q("SELECT count(*), quantile_cont(t_hat - first_ts, [0.5,0.9,0.95,0.99,0.999]) FROM pv")
print('prep-block time minus opens_at (s):'); q("SELECT count(*), quantile_cont(t_hat - opens_at, [0.05,0.25,0.5,0.75,0.95]) FROM pv")
months=pd.date_range('2022-11-01','2026-06-01',freq='MS')
mb=[(mth.strftime('%Y-%m'), int(round(np.interp(mth.timestamp(), bm.t.values, bm.blk.values))), mth.timestamp()) for mth in months]
mbdf=pd.DataFrame(mb, columns=['ym','start_block','start_epoch']); mbdf.to_parquet(f'{SC}/month_blocks.parquet'); print(mbdf.to_string())
con.execute(f"COPY (SELECT condition_id, res_block, t_hat AS res_t_hat, resolved_at, last_ts FROM rv) TO '{AT}/struct_ctf_resolution_time.parquet' (FORMAT PARQUET)")
