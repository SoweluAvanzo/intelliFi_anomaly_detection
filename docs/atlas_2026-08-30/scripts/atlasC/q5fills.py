import duckdb, pandas as pd
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
AT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas'
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
con.execute(f"CREATE TABLE g AS SELECT g.*, m.cls, m.src FROM '{AT}/struct_mintgroups_condmonth.parquet' g LEFT JOIN '{AT}/struct_markets.parquet' m USING (condition_id)")
cols="""sum(n_rows) n_rows, sum(usd) usd, sum(sh) sh, sum(n_grp) n_grp, sum(n_grp_x) n_grp_x, sum(n_rows_x) n_rows_x, sum(n_rows_x_min) n_rows_x_min, sum(n_rows_x_max) n_rows_x_max,
 sum(sh_x) sh_x, sum(sh_x_min) sh_x_min, sum(sh_x_max) sh_x_max, sum(sh_x_sell) sh_x_sell, sum(sh_x_buy) sh_x_buy, sum(usd_x) usd_x, sum(usd_x_sell) usd_x_sell, sum(usd_x_buy) usd_x_buy,
 sum(n_rows_x_samedir) n_rows_x_samedir, sum(sh_x_samedir) sh_x_samedir, sum(n_rows_mixed) n_rows_mixed, sum(sh_mixed) sh_mixed, sum(n_grp_samet_bothdir) n_grp_samet_bothdir"""
mon=con.execute(f"SELECT ym, {cols} FROM g WHERE ym BETWEEN '2023-01' AND '2026-04' GROUP BY 1 ORDER BY 1").df()
mon.to_parquet(f'{AT}/struct_q5_fills_monthly.parquet'); mon.to_csv(f'{SC}/q5_fills_monthly.csv',index=False)
byc=con.execute(f"SELECT cls, {cols} FROM g WHERE ym BETWEEN '2023-01' AND '2026-04' GROUP BY 1 ORDER BY usd DESC").df()
byc.to_parquet(f'{AT}/struct_q5_fills_by_class.parquet'); byc.to_csv(f'{SC}/q5_fills_by_class.csv',index=False)
bys=con.execute(f"SELECT src, {cols} FROM g WHERE ym BETWEEN '2023-01' AND '2026-04' GROUP BY 1").df(); bys.to_csv(f'{SC}/q5_fills_by_src.csv',index=False)
tot=con.execute(f"SELECT {cols} FROM g WHERE ym BETWEEN '2023-01' AND '2026-04'").df(); tot.to_csv(f'{SC}/q5_fills_total.csv',index=False)
pd.set_option('display.width',250)
for d in [mon,byc,bys,tot]:
    d['x_row_share']=d.n_rows_x/d.n_rows; d['x_row_share_min']=d.n_rows_x_min/d.n_rows; d['x_row_share_max']=d.n_rows_x_max/d.n_rows
    d['x_sh_share']=d.sh_x/d.sh; d['x_sh_min_share']=d.sh_x_min/d.sh; d['x_sh_max_share']=d.sh_x_max/d.sh; d['x_sell_sh_share']=d.sh_x_sell/d.sh; d['x_buy_sh_share']=d.sh_x_buy/d.sh
    d['samedir_row_share']=d.n_rows_x_samedir/d.n_rows; d['mixed_row_share']=d.n_rows_mixed/d.n_rows
    print(d[[c for c in d.columns if c in ('ym','cls','src')]+['n_rows','usd','x_row_share','x_row_share_min','x_row_share_max','x_sh_share','x_sell_sh_share','x_buy_sh_share','samedir_row_share','mixed_row_share']].to_string())
# per-condition all-time for reconciliation
con.execute(f"COPY (SELECT condition_id, any_value(src) src, any_value(cls) cls, sum(n_rows) n_rows, sum(sh) sh, sum(usd) usd, sum(n_rows_x) n_rows_x, sum(sh_x) sh_x, sum(sh_x_sell) sh_x_sell, sum(sh_x_buy) sh_x_buy, sum(sh_x_min) sh_x_min, sum(sh_x_max) sh_x_max, sum(sh_x_samedir) sh_x_samedir, sum(sh_mixed) sh_mixed FROM g GROUP BY 1) TO '{SC}/fills_cond_x.parquet' (FORMAT PARQUET)")
