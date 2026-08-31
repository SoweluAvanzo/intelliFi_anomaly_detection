import duckdb, pandas as pd, numpy as np
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
AT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas'
con=duckdb.connect(); con.execute("PRAGMA memory_limit='3GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
bm=pd.read_parquet(f'{SC}/blockmap.parquet').sort_values('bin').reset_index(drop=True)
g=con.execute(f"SELECT res_block//10000 bin, median(resolved_at)+214 t, count(*) n FROM '{AT}/struct_ctf_resolution_time.parquet' WHERE resolved_at IS NOT NULL GROUP BY 1 HAVING count(*)>=50 ORDER BY 1").df()
SPLICE=8500
tail=pd.DataFrame({'bin':np.arange(SPLICE, bm.bin.max()+1)}).merge(g[['bin','t']],on='bin',how='left')
tail['blk']=tail.bin*10000+5000
# anchors at bin centre: Gamma medians are for events spread within the bin -> centre is fine; interpolate gaps; extrapolate beyond last anchor at 1.9 s/block
tail['t']=tail.t.interpolate()
last=tail.t.last_valid_index()
if last is not None and last < len(tail)-1:
    tail.loc[last+1:,'t']=tail.loc[last,'t']+1.9*(tail.loc[last+1:,'blk']-tail.loc[last,'blk'])
first=tail.t.first_valid_index()
print('splice continuity at bin',SPLICE,': old map t=',bm.loc[bm.bin==SPLICE,'t'].values, 'gamma-based t=',tail.loc[first,'t'] if first is not None else None)
bm2=pd.concat([bm[bm.bin<SPLICE][['bin','blk','t']], tail[['bin','blk','t']]]).reset_index(drop=True)
bm2['t']=np.maximum.accumulate(bm2.t.values)
bm2.to_parquet(f'{SC}/blockmap.parquet')
print(bm2.tail(5).assign(dt=lambda d: pd.to_datetime(d.t,unit='s')).to_string())
# validate again
con.execute(f"CREATE TABLE bm AS SELECT blk, t FROM '{SC}/blockmap.parquet' ORDER BY blk")
con.execute(f"CREATE TABLE r AS SELECT condition_id, res_block, resolved_at FROM '{AT}/struct_ctf_resolution_time.parquet'")
con.execute("""CREATE TABLE rv AS SELECT r.*, b1.t + (b2.t-b1.t)*(r.res_block-b1.blk)/(b2.blk-b1.blk) AS t_hat FROM r ASOF JOIN bm b1 ON r.res_block >= b1.blk ASOF JOIN bm b2 ON r.res_block < b2.blk""")
print(con.execute("SELECT strftime(to_timestamp(resolved_at),'%Y-%m') ym, count(*) n, round(quantile_cont(t_hat-resolved_at,0.5)) med, round(quantile_cont(t_hat-resolved_at,0.1)) p10, round(quantile_cont(t_hat-resolved_at,0.9)) p90 FROM rv WHERE resolved_at IS NOT NULL GROUP BY 1 ORDER BY 1").df().to_string())
print(con.execute("SELECT count(*), quantile_cont(t_hat - resolved_at, [0.01,0.05,0.25,0.5,0.75,0.95,0.99]) FROM rv WHERE resolved_at IS NOT NULL").fetchall())
con.execute(f"COPY (SELECT condition_id, res_block, t_hat AS res_t_hat, resolved_at FROM rv) TO '{AT}/struct_ctf_resolution_time.parquet' (FORMAT PARQUET)")
# month boundaries; 2026-05 boundary = tape end (2026-04-29 00:00 UTC) so that CTF 'April 2026' matches the fill tape's coverage
months=pd.date_range('2022-11-01','2026-06-01',freq='MS')
rows=[]
for mth in months:
    e=mth.timestamp()
    if mth.strftime('%Y-%m')=='2026-05': e=1777420800.0
    rows.append((mth.strftime('%Y-%m'), int(round(np.interp(e, bm2.t.values, bm2.blk.values))), e))
mbdf=pd.DataFrame(rows, columns=['ym','start_block','start_epoch']); mbdf.to_parquet(f'{SC}/month_blocks.parquet'); print(mbdf.tail(6).to_string())
