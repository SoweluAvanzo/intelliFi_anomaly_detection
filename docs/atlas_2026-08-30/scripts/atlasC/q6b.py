import duckdb, pandas as pd, numpy as np
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
AT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas'
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
con.execute(f"CREATE TABLE mk AS SELECT ym, maker, n_fills, usd FROM '{AT}/struct_maker_month.parquet' WHERE ym BETWEEN '2023-01' AND '2026-04'")
con.execute(f"CREATE TABLE tk AS SELECT ym, count(*) n_takers, sum(n_fills) n_fills FROM '{AT}/struct_taker_month.parquet' WHERE ym BETWEEN '2023-01' AND '2026-04' GROUP BY 1")
con.execute("""CREATE TABLE r AS SELECT ym, maker, n_fills, usd, row_number() OVER (PARTITION BY ym ORDER BY usd DESC, maker) rk, usd/sum(usd) OVER (PARTITION BY ym) s FROM mk""")
con.execute("""CREATE TABLE top AS SELECT ym, maker FROM r WHERE rk<=10""")
mon=con.execute("""SELECT r.ym, count(*) n_makers, sum(usd) usd, sum(n_fills) n_fills, sum(s*s) hhi, sum(s) FILTER (WHERE rk<=10) top10_share,
  sum(n_fills) FILTER (WHERE rk<=10)/sum(n_fills) top10_fill_share, sum(s) FILTER (WHERE rk=1) top1_share, sum(s) FILTER (WHERE rk<=50) top50_share,
  1.0/sum(s*s) eff_n FROM r GROUP BY 1 ORDER BY 1""").df()
pers=con.execute("""SELECT a.ym, count(b.maker)/10.0 persistence FROM top a LEFT JOIN top b ON b.maker=a.maker AND b.ym = strftime(date_trunc('month', strptime(a.ym,'%Y-%m')) - INTERVAL 1 MONTH, '%Y-%m') GROUP BY 1""").df()
tk=con.execute("SELECT * FROM tk").df()
out=mon.merge(pers,on='ym',how='left').merge(tk[['ym','n_takers']],on='ym',how='left')
out.loc[out.ym=='2023-01','persistence']=np.nan
out.to_parquet(f'{AT}/struct_q6b_monthly.parquet'); out.to_csv(f'{SC}/q6b_monthly.csv',index=False)
print(out.to_string())
# by class for 2026
con.execute(f"CREATE TABLE cm AS SELECT category, cls FROM '{AT}/struct_category_classmap.parquet'")
con.execute(f"CREATE TABLE cmk AS SELECT c.ym, coalesce(cm.cls,'Other') cls, c.maker, sum(c.n_fills) n_fills, sum(c.usd) usd FROM '{SC}/catmkr_2026.parquet' c LEFT JOIN cm USING (category) GROUP BY 1,2,3")
con.execute(f"CREATE TABLE ctk AS SELECT c.ym, coalesce(cm.cls,'Other') cls, count(distinct c.taker) n_takers FROM '{SC}/cattkr_2026.parquet' c LEFT JOIN cm USING (category) GROUP BY 1,2")
con.execute("""CREATE TABLE rc AS SELECT ym, cls, maker, n_fills, usd, row_number() OVER (PARTITION BY ym, cls ORDER BY usd DESC, maker) rk, usd/sum(usd) OVER (PARTITION BY ym, cls) s FROM cmk""")
byc=con.execute("""SELECT ym, cls, count(*) n_makers, sum(usd) usd, sum(s*s) hhi, sum(s) FILTER (WHERE rk<=10) top10_share, sum(n_fills) FILTER (WHERE rk<=10)/sum(n_fills) top10_fill_share, sum(s) FILTER (WHERE rk=1) top1_share FROM rc GROUP BY 1,2 ORDER BY 2,1""").df()
persc=con.execute("""WITH t AS (SELECT ym, cls, maker FROM rc WHERE rk<=10) SELECT a.ym, a.cls, count(b.maker)/10.0 persistence FROM t a LEFT JOIN t b ON b.maker=a.maker AND b.cls=a.cls AND b.ym = strftime(date_trunc('month', strptime(a.ym,'%Y-%m')) - INTERVAL 1 MONTH, '%Y-%m') GROUP BY 1,2""").df()
byc=byc.merge(persc,on=['ym','cls'],how='left').merge(con.execute("SELECT * FROM ctk").df(),on=['ym','cls'],how='left')
byc.loc[byc.ym=='2026-01','persistence']=np.nan
byc.to_parquet(f'{AT}/struct_q6b_2026_by_class.parquet'); byc.to_csv(f'{SC}/q6b_2026_by_class.csv',index=False)
print(byc.to_string())
# 2026 aggregate by class (Jan-Apr pooled)
con.execute("""CREATE TABLE rp AS SELECT cls, maker, sum(n_fills) n_fills, sum(usd) usd FROM cmk GROUP BY 1,2""")
pool=con.execute("""WITH x AS (SELECT cls, maker, n_fills, usd, row_number() OVER (PARTITION BY cls ORDER BY usd DESC) rk, usd/sum(usd) OVER (PARTITION BY cls) s FROM rp)
 SELECT cls, count(*) n_makers, sum(usd) usd, sum(s*s) hhi, sum(s) FILTER (WHERE rk<=10) top10_share, sum(n_fills) FILTER (WHERE rk<=10)/sum(n_fills) top10_fill_share FROM x GROUP BY 1 ORDER BY 3 DESC""").df()
print(pool.to_string()); pool.to_csv(f'{SC}/q6b_2026_pooled_by_class.csv',index=False)
# cross-class overlap of top-10 makers in 2026 pooled
ov=con.execute("""WITH x AS (SELECT cls, maker, row_number() OVER (PARTITION BY cls ORDER BY usd DESC) rk FROM rp) SELECT maker, count(*) n_classes, string_agg(cls, ',' ORDER BY cls) classes FROM x WHERE rk<=10 GROUP BY 1 ORDER BY 2 DESC""").df()
print(ov.head(20).to_string()); ov.to_csv(f'{SC}/q6b_2026_top10_overlap.csv',index=False)
