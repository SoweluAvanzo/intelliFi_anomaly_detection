import duckdb, pandas as pd, glob, os, time, datetime as dt
pd.set_option('display.width',250); pd.set_option('display.max_columns',40)
S="/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasB"
A="/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas"
con=duckdb.connect(); con.execute("PRAGMA threads=6"); con.execute("SET enable_progress_bar=false")
con.execute(f"SET temp_directory='{S}/duck_tmp'"); con.execute("SET memory_limit='14GB'")
con.execute(f"CREATE TABLE cm AS SELECT cat, arg_max(cls, vol) cls FROM (SELECT c.category cat, c.cls, sum(t.vol) vol FROM '{S}/catmap.parquet' c JOIN (SELECT category, category_refined, sum(vol) vol FROM '{S}/daily_agg_all_classed.parquet' GROUP BY 1,2) t USING (category, category_refined) GROUP BY 1,2) GROUP BY 1")
days=sorted(os.path.basename(f)[:-8] for f in glob.glob(f"{S}/pairs_daily2/*.parquet"))
def files(ds): return "["+",".join(f"'{S}/pairs_daily2/{d}.parquet','{S}/pairs_daily2m/{d}.parquet'" for d in ds)+"]"
def run(label, ds, out_rows, wal_rows):
    t=time.time()
    con.execute("DROP TABLE IF EXISTS p"); con.execute(f"CREATE TABLE p AS SELECT a, b, cat, fee_flag, sum(n) n, sum(vol) vol FROM read_parquet({files(ds)}) WHERE a<>b GROUP BY ALL")
    con.execute("CREATE OR REPLACE TABLE wc AS SELECT w, c, sum(n) n, sum(vol) vol FROM (SELECT a w, b c, n, vol FROM p UNION ALL SELECT b w, a c, n, vol FROM p) GROUP BY 1,2")
    con.execute("CREATE OR REPLACE TABLE ws AS SELECT w, sum(n) N, sum(vol) V, sum(n*n)/(sum(n)*sum(n)) hhi, arg_max(c, n) top_c, max(n)*1.0/sum(n) top_share, count(*) n_cp FROM wc GROUP BY 1")
    con.execute("CREATE OR REPLACE TABLE flag AS SELECT w, top_c c, N, V, hhi FROM ws WHERE N>=100 AND hhi>=0.5")
    con.execute("CREATE OR REPLACE TABLE fp AS SELECT least(w,c) a, greatest(w,c) b, count(*) k FROM flag GROUP BY 1,2")
    r=con.execute(f"""SELECT '{label}' period, cat, coalesce(cm.cls,'other') cls, fee_flag, sum(p.vol) vol, sum(p.n) n,
        sum(CASE WHEN fp.a IS NOT NULL THEN p.vol ELSE 0 END) pair_vol, sum(CASE WHEN fp.k=2 THEN p.vol ELSE 0 END) recip_vol,
        sum(CASE WHEN fp.a IS NOT NULL THEN p.n ELSE 0 END) pair_n, sum(CASE WHEN fp.k=2 THEN p.n ELSE 0 END) recip_n
        FROM p LEFT JOIN fp USING (a,b) LEFT JOIN cm USING (cat) GROUP BY ALL""").df()
    out_rows.append(r)
    wal=con.execute(f"""SELECT '{label}' period, (SELECT count(*) FROM ws) n_wallets, (SELECT count(*) FROM ws WHERE N>=100) n_wallets_ge100, (SELECT count(*) FROM flag) n_flagged,
        (SELECT count(*) FROM fp) n_flagged_pairs, (SELECT count(*) FROM fp WHERE k=2) n_recip_pairs,
        (SELECT median(hhi) FROM ws WHERE N>=100) med_hhi_ge100, (SELECT quantile_cont(hhi,0.9) FROM ws WHERE N>=100) p90_hhi_ge100,
        (SELECT sum(V) FROM flag) flagged_wallet_vol, (SELECT sum(vol) FROM p) total_vol""").df()
    wal_rows.append(wal)
    print(label, len(ds), "days", round(time.time()-t,1), "s", flush=True)
out=[]; wal=[]
months=sorted(set(d[:7] for d in days))
for m in months: run(m, [d for d in days if d.startswith(m)], out, wal)
M=pd.concat(out); W=pd.concat(wal)
M.to_parquet(f"{S}/pairs_monthly_tag.parquet", index=False); W.to_parquet(f"{A}/wash_q3c_pair_hhi_wallet_stats_monthly.parquet", index=False)
mm=M.groupby(['period','cls','fee_flag'],as_index=False)[['vol','n','pair_vol','recip_vol','pair_n','recip_n']].sum()
mm['pair_share']=mm.pair_vol/mm.vol; mm['recip_share']=mm.recip_vol/mm.vol
mm.to_parquet(f"{A}/wash_q3c_pair_hhi_monthly_class_fee.parquet", index=False)
print(W.to_string())
allc=M.groupby(['period','cls'],as_index=False)[['vol','pair_vol','recip_vol']].sum()
print("Concentrated-pair volume share % (any-side flag), class x month"); print(allc.assign(s=allc.pair_vol/allc.vol*100).pivot(index='period',columns='cls',values='s').round(2).to_string())
print("Reciprocal-pair volume share %"); print(allc.assign(s=allc.recip_vol/allc.vol*100).pivot(index='period',columns='cls',values='s').round(3).to_string())
print("fee-paying fills only, any-side %"); print(mm[mm.fee_flag].pivot(index='period',columns='cls',values='pair_share').mul(100).round(2).to_string())
print("non-fee fills only, any-side %"); print(mm[~mm.fee_flag].pivot(index='period',columns='cls',values='pair_share').mul(100).round(2).to_string())
pm=M.groupby(['period'],as_index=False)[['vol','pair_vol','recip_vol']].sum(); print("platform"); print(pm.assign(pair_pct=pm.pair_vol/pm.vol*100, recip_pct=pm.recip_vol/pm.vol*100).round(3).to_string())
pf=M.groupby(['period','fee_flag'],as_index=False)[['vol','pair_vol','recip_vol']].sum(); print(pf.assign(pair_pct=pf.pair_vol/pf.vol*100, recip_pct=pf.recip_vol/pf.vol*100).round(3).to_string())
# weekly
out=[]; wal=[]
wk_of=lambda d: (dt.date.fromisoformat(d.replace('_','-')) - dt.timedelta(days=dt.date.fromisoformat(d.replace('_','-')).weekday())).isoformat()
weeks=sorted(set(wk_of(d) for d in days))
for w in weeks: run(w, [d for d in days if wk_of(d)==w], out, wal)
Wk=pd.concat(out); Wk.rename(columns={'period':'wk'}).to_parquet(f"{S}/panel_weekly_tag_pairs.parquet", index=False)
pd.concat(wal).to_parquet(f"{S}/pairs_weekly_wallet_stats.parquet", index=False)
print("weekly done")
