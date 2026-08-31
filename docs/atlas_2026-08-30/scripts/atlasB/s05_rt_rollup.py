import duckdb, pandas as pd
pd.set_option('display.width',250); pd.set_option('display.max_columns',40)
S="/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasB"
A="/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas"
con=duckdb.connect(); con.execute("PRAGMA threads=3"); con.execute("SET enable_progress_bar=false")
con.execute(f"CREATE TABLE cm AS SELECT category AS cat, category_refined AS catr, cls, subcls FROM '{S}/catmap.parquet'")
con.execute(f"CREATE TABLE r AS SELECT r.*, coalesce(cm.cls,'other') cls FROM (SELECT *, 'binary' arch FROM '{S}/rt_daily2/*.parquet' UNION ALL SELECT *, 'multi' FROM '{S}/rt_daily2m/*.parquet') r LEFT JOIN cm USING (cat, catr)")
print(con.execute("SELECT count(*) n, sum(vol)/1e9 vol_b, sum(n_orders)/1e6 orders_m, sum(rt_close_vol)/sum(vol) rt_close_share, sum(rt_any_vol)/sum(vol) rt_any_share, sum(rt_close_vol_60s)/sum(vol) rt60_share FROM r").df().to_string())
m=con.execute("""SELECT strftime(d,'%Y-%m') ym, cls, fee_flag, sum(n_orders) n_orders, sum(vol) vol, sum(rt_close_vol) rt_close_vol, sum(rt_any_vol) rt_any_vol, sum(rt_close_n) rt_close_n, sum(rt_any_n) rt_any_n, sum(rt_close_vol_60s) rt_close_vol_60s,
  sum(rt_close_vol)/sum(vol) rt_close_share, sum(rt_any_vol)/sum(vol) rt_any_share, sum(rt_close_vol_60s)/sum(vol) rt60_share, sum(rt_close_n)/sum(n_orders) rt_close_share_n
  FROM r GROUP BY 1,2,3 ORDER BY 1,2,3""").df()
m.to_parquet(f"{A}/wash_q3b_roundtrip_monthly_class_fee.parquet", index=False)
allm=con.execute("""SELECT strftime(d,'%Y-%m') ym, cls, sum(vol) vol, sum(rt_close_vol)/sum(vol)*100 rt_close_pct, sum(rt_any_vol)/sum(vol)*100 rt_any_pct, sum(rt_close_vol_60s)/sum(vol)*100 rt60_pct FROM r GROUP BY 1,2""").df()
print("Round-trip (closing-leg) volume share %, all fills, class x month"); print(allm.pivot(index='ym',columns='cls',values='rt_close_pct').round(2).to_string())
print("Round-trip (either-leg) volume share %"); print(allm.pivot(index='ym',columns='cls',values='rt_any_pct').round(2).to_string())
print("closing leg, fee-paying fills only %"); print(m[m.fee_flag].pivot(index='ym',columns='cls',values='rt_close_share').mul(100).round(2).to_string())
print("closing leg, non-fee fills only %"); print(m[~m.fee_flag].pivot(index='ym',columns='cls',values='rt_close_share').mul(100).round(2).to_string())
print("platform monthly"); print(con.execute("SELECT strftime(d,'%Y-%m') ym, sum(vol)/1e6 vol_m, sum(rt_close_vol)/sum(vol)*100 rt_close_pct, sum(rt_any_vol)/sum(vol)*100 rt_any_pct, sum(rt_close_vol_60s)/sum(vol)*100 rt60_pct, sum(rt_close_n)/sum(n_orders)*100 rt_close_orders_pct FROM r GROUP BY 1 ORDER BY 1").df().round(3).to_string())
print("platform monthly by fee_flag"); print(con.execute("SELECT strftime(d,'%Y-%m') ym, fee_flag, sum(vol)/1e6 vol_m, sum(rt_close_vol)/sum(vol)*100 rt_close_pct, sum(rt_any_vol)/sum(vol)*100 rt_any_pct FROM r WHERE d>='2026-01-01' GROUP BY 1,2 ORDER BY 1,2").df().round(3).to_string())
w=con.execute("""SELECT date_trunc('week', d)::DATE wk, cat, catr, cls, sum(n_orders) n_orders, sum(vol) vol, sum(rt_close_vol) rt_close_vol, sum(rt_any_vol) rt_any_vol, sum(rt_close_vol_60s) rt_close_vol_60s,
  sum(CASE WHEN fee_flag THEN vol ELSE 0 END) fee_vol, count(DISTINCT d) ndays FROM r GROUP BY 1,2,3,4""").df()
w.to_parquet(f"{S}/panel_weekly_tag_rt.parquet", index=False); print(w.shape)
