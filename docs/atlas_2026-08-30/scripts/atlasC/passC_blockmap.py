import duckdb, time, numpy as np, pandas as pd
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
AT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas'
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
def q(s): r=con.execute(s).fetchall(); print(r); return r
S=2.2  # nominal seconds per block for intercept space
BIN=10000
con.execute(f"CREATE TABLE m AS SELECT * FROM '{AT}/struct_markets.parquet'")
con.execute(f"CREATE TABLE prep AS SELECT * FROM '{SC}/ctf_prep.parquet'")
con.execute(f"CREATE TABLE res AS SELECT * FROM '{SC}/ctf_res.parquet'")
q("SELECT count(*), count(*) FILTER (WHERE p.condition_id IS NOT NULL), count(*) FILTER (WHERE r.condition_id IS NOT NULL) FROM m LEFT JOIN prep p USING (condition_id) LEFT JOIN res r USING (condition_id)")
# duplicates in prep/res per condition?
q("SELECT count(*), count(distinct condition_id) FROM prep"); q("SELECT count(*), count(distinct condition_id) FROM res")
con.execute(f"""CREATE TABLE up AS SELECT p.prep_block blk, m.first_ts t, m.first_ts - {S}*p.prep_block c FROM m JOIN (SELECT condition_id, min(prep_block) prep_block FROM prep GROUP BY 1) p USING (condition_id)""")
con.execute(f"""CREATE TABLE lo AS SELECT r.res_block blk, m.last_ts t, m.last_ts - {S}*r.res_block c FROM m JOIN (SELECT condition_id, max(res_block) res_block FROM res GROUP BY 1) r USING (condition_id)""")
con.execute(f"""CREATE TABLE env AS SELECT coalesce(u.bin,l.bin) bin, u.n nu, u.cu, l.n nl, l.cl, l.cl995 FROM
  (SELECT blk//{BIN} bin, count(*) n, min(c) cu FROM up GROUP BY 1) u FULL OUTER JOIN
  (SELECT blk//{BIN} bin, count(*) n, max(c) cl, quantile_cont(c,0.995) cl995 FROM lo GROUP BY 1) l USING (bin) ORDER BY 1""")
df=con.execute("SELECT * FROM env ORDER BY bin").df()
print(df.describe())
print('bins with both', ((df.cu.notna())&(df.cl.notna())).sum(), 'violations cl>cu', ((df.cl>df.cu)).sum(), 'cl995>cu', (df.cl995>df.cu).sum())
d=df[(df.cu.notna())&(df.cl.notna())]
print('gap cu-cl (s) quantiles', np.nanquantile((d.cu-d.cl).values,[0.05,0.25,0.5,0.75,0.95]))
print('gap cu-cl995 (s) quantiles', np.nanquantile((d.cu-d.cl995).values,[0.05,0.25,0.5,0.75,0.95]))
df.to_parquet(f'{SC}/blockmap_env.parquet')
