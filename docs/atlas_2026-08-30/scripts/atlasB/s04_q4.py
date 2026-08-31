import duckdb, pandas as pd, numpy as np, sys
sys.path.insert(0,'.')
from catmap import map_class
pd.set_option('display.width',250); pd.set_option('display.max_columns',40)
A="/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas"
con=duckdb.connect(); con.execute("PRAGMA threads=4"); con.execute("SET TimeZone='UTC'"); con.execute("SET enable_progress_bar=false")
con.execute("CREATE TABLE cc AS SELECT * FROM 'multi_cond_all.parquet'")
cm=con.execute("SELECT DISTINCT category, category_refined FROM cc").df()
cm['cls']=cm.apply(lambda r: map_class(r.category, r.category_refined)[0],axis=1)
con.execute("CREATE TABLE cm AS SELECT * FROM cm")
con.execute("""CREATE TABLE cand AS
  SELECT c.neg_risk_market_id fam, c.condition_id, c.first_ts, c.last_ts, c.vol, cm.cls,
         max(c.last_ts) OVER (PARTITION BY c.neg_risk_market_id) fam_last,
         min(c.first_ts) OVER (PARTITION BY c.neg_risk_market_id) fam_first,
         count(*) OVER (PARTITION BY c.neg_risk_market_id) n_cand_total
  FROM cc c LEFT JOIN cm USING (category, category_refined)""")
con.execute("""CREATE TABLE h AS SELECT neg_risk_market_id fam, condition_id, hr, last_px, n_fills, vol, fee_vol FROM 'multi_hourly/*.parquet'""")
# family-hours: any candidate traded, hour fully before family's last trade hour
con.execute("""CREATE TABLE fh AS SELECT fam, hr FROM h JOIN (SELECT fam, max(fam_last) fam_last FROM cand GROUP BY 1) f USING (fam)
  WHERE hr + 3600 <= (fam_last//3600)*3600 GROUP BY 1,2""")
# grid of alive candidates per family-hour
con.execute("""CREATE TABLE grid AS SELECT fh.fam, fh.hr, cand.condition_id FROM fh JOIN cand USING (fam)
  WHERE cand.first_ts < fh.hr + 3600 AND cand.last_ts >= fh.hr""")
# asof: last price at or before this hour for each candidate
con.execute("""CREATE TABLE g2 AS
  SELECT g.fam, g.hr, g.condition_id, h.hr AS px_hr, h.last_px AS px_cf,
         t.last_px AS px_traded, t.vol AS vol_hr, t.fee_vol AS fee_vol_hr, t.n_fills AS n_fills_hr
  FROM grid g
  ASOF LEFT JOIN h ON h.condition_id = g.condition_id AND h.hr <= g.hr
  LEFT JOIN h t ON t.condition_id = g.condition_id AND t.hr = g.hr""")
con.execute("""CREATE TABLE fs AS
  SELECT fam, hr, count(*) n_alive, count(px_traded) n_traded,
    count(px_traded)*1.0/count(*) coverage,
    sum(px_traded) S_traded,
    CASE WHEN bool_and(px_hr IS NOT NULL AND hr - px_hr <= 86400) THEN sum(px_cf) END S_cf,
    sum(least(px_cf, 1-px_cf)) sum_minp_cf,
    sum(coalesce(vol_hr,0)) vol_hr, sum(coalesce(fee_vol_hr,0)) fee_vol_hr, sum(coalesce(n_fills_hr,0)) n_fills_hr,
    max(px_cf) max_px
  FROM g2 GROUP BY 1,2""")
con.execute("""CREATE TABLE fs2 AS SELECT fs.*, c.cls, c.n_cand_total, strftime(to_timestamp(hr),'%Y-%m') ym,
   CASE WHEN fee_vol_hr > 0.5*vol_hr THEN 'fee' ELSE 'nofee' END fee_status,
   S_cf - 1 dev, abs(S_cf-1) adev, 0.10*sum_minp_cf fee_band
   FROM fs JOIN (SELECT fam, any_value(cls) cls, max(n_cand_total) n_cand_total FROM cand GROUP BY 1) c USING (fam)""")
print(con.execute("SELECT count(*) fam_hours, count(DISTINCT fam) fams, sum(CASE WHEN coverage>=0.8 THEN 1 ELSE 0 END) fh_cov80, sum(CASE WHEN coverage>=0.8 AND n_alive>=3 THEN 1 ELSE 0 END) fh_cov80_n3, sum(CASE WHEN coverage>=0.8 AND n_alive>=3 AND S_cf IS NOT NULL THEN 1 ELSE 0 END) fh_ok FROM fs2").df().to_string())
con.execute("CREATE TABLE ok AS SELECT * FROM fs2 WHERE coverage>=0.8 AND n_alive>=3 AND S_cf IS NOT NULL")
con.execute(f"COPY ok TO '{A}/negrisk_family_hour_sums.parquet' (FORMAT PARQUET)")
def q(sql): return con.execute(sql).df()
summ=q("""SELECT ym, fee_status, count(*) fam_hours, count(DISTINCT fam) fams, avg(dev) mean_dev, stddev(dev) sd_dev, median(dev) med_dev,
  quantile_cont(adev,0.5) p50_adev, quantile_cont(adev,0.75) p75_adev, quantile_cont(adev,0.9) p90_adev, quantile_cont(adev,0.95) p95_adev,
  avg(CASE WHEN adev>0.01 THEN 1.0 ELSE 0 END) sh_gt1c, avg(CASE WHEN adev>0.05 THEN 1.0 ELSE 0 END) sh_gt5c, avg(CASE WHEN adev>0.10 THEN 1.0 ELSE 0 END) sh_gt10c,
  avg(fee_band) mean_fee_band, avg(S_traded-1) mean_dev_traded, avg(n_alive) mean_n_alive, sum(vol_hr)/1e6 vol_m
  FROM ok GROUP BY 1,2 ORDER BY 1,2""")
print(summ.round(4).to_string())
summ.to_parquet(f"{A}/negrisk_q4_summary_month_fee.parquet", index=False)
# cluster-robust SE of mean dev by family: family-level means, weighted by hours
fam=q("SELECT ym, fee_status, fam, count(*) nh, sum(dev) sdev FROM ok GROUP BY 1,2,3")
rows=[]
for (ym,fs),g in fam.groupby(['ym','fee_status']):
    N=g.nh.sum(); mean=g.sdev.sum()/N; G=len(g)
    u=g.sdev-mean*g.nh
    se=np.sqrt((u**2).sum())/N*np.sqrt(G/(G-1)) if G>1 else np.nan
    rows.append(dict(ym=ym,fee_status=fs,mean_dev=mean,se_cluster_fam=se,n_fam=G,n_hours=N))
cl=pd.DataFrame(rows); print(cl.round(5).to_string()); cl.to_parquet(f"{A}/negrisk_q4_meandev_clusterSE.parquet",index=False)
print("by class x month (fam-hours, mean dev, p50 adev, p90 adev, fee share of hours)")
bc=q("""SELECT cls, ym, count(*) fh, count(DISTINCT fam) fams, avg(dev) mean_dev, quantile_cont(adev,0.5) p50, quantile_cont(adev,0.9) p90, avg(CASE WHEN fee_status='fee' THEN 1.0 ELSE 0 END) fee_hr_share, avg(fee_band) fee_band FROM ok GROUP BY 1,2 ORDER BY 1,2""")
print(bc.round(4).to_string()); bc.to_parquet(f"{A}/negrisk_q4_by_class_month.parquet",index=False)
print("by family size bucket x fee_status (Mar-Apr 2026)")
print(q("""SELECT CASE WHEN n_alive<=3 THEN '3' WHEN n_alive<=6 THEN '4-6' WHEN n_alive<=12 THEN '7-12' ELSE '13+' END nb, fee_status, count(*) fh, count(DISTINCT fam) fams, avg(dev) mean_dev, quantile_cont(adev,0.5) p50, quantile_cont(adev,0.9) p90, avg(fee_band) fee_band FROM ok WHERE ym>='2026-03' GROUP BY 1,2 ORDER BY 1,2""").round(4).to_string())
print("same families before/after fee: families with both fee and nofee hours in 2026")
print(q("""WITH f AS (SELECT fam FROM ok WHERE ym>='2026-01' GROUP BY 1 HAVING count(DISTINCT fee_status)=2)
  SELECT fee_status, count(*) fh, count(DISTINCT fam) fams, avg(dev) mean_dev, quantile_cont(adev,0.5) p50, quantile_cont(adev,0.9) p90, avg(fee_band) fee_band FROM ok WHERE fam IN (SELECT fam FROM f) AND ym>='2026-01' GROUP BY 1""").round(4).to_string())
print("robustness: S_traded (no carry-forward), coverage=1 only")
print(q("""SELECT ym, fee_status, count(*) fh, avg(S_traded-1) mean_dev, quantile_cont(abs(S_traded-1),0.5) p50, quantile_cont(abs(S_traded-1),0.9) p90 FROM ok WHERE coverage=1 GROUP BY 1,2 ORDER BY 1,2""").round(4).to_string())
