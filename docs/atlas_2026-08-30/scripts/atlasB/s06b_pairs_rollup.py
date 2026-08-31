import duckdb, pandas as pd, glob, os, time, sys, datetime as dt
S="/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasB"
BUDGET=float(sys.argv[1]) if len(sys.argv)>1 else 1e9; MODE=sys.argv[2] if len(sys.argv)>2 else 'month'
os.makedirs(f"{S}/pairs_out", exist_ok=True); os.makedirs(f"{S}/duck_tmp", exist_ok=True)
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{S}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
con.execute("SET preserve_insertion_order=false")
con.execute(f"CREATE TABLE cm AS SELECT cat, arg_max(cls, vol) cls FROM (SELECT c.category cat, c.cls, sum(t.vol) vol FROM '{S}/catmap.parquet' c JOIN (SELECT category, category_refined, sum(vol) vol FROM '{S}/daily_agg_all_classed.parquet' GROUP BY 1,2) t USING (category, category_refined) GROUP BY 1,2) GROUP BY 1")
days=sorted(os.path.basename(f)[:-8] for f in glob.glob(f"{S}/pairs_daily2/*.parquet"))
def files(ds): return "["+",".join(f"'{S}/pairs_daily2/{d}.parquet','{S}/pairs_daily2m/{d}.parquet'" for d in ds)+"]"
t0=time.time()
def run(label, ds):
    if os.path.exists(f"{S}/pairs_out/{label}_wal.parquet"): return
    if time.time()-t0>BUDGET: print("budget reached", flush=True); sys.exit(0)
    t=time.time()
    con.execute(f"COPY (SELECT a, b, sum(n) n FROM read_parquet({files(ds)}) WHERE a<>b GROUP BY 1,2) TO '{S}/duck_tmp/p0_{label}.parquet' (FORMAT PARQUET)")
    con.execute(f"CREATE OR REPLACE TABLE ws AS SELECT w, sum(n) N, sum(n*n)/(sum(n)*sum(n)) hhi, arg_max(c, n) top_c, max(n)*1.0/sum(n) top_share, count(*) n_cp FROM (SELECT a w, b c, n FROM '{S}/duck_tmp/p0_{label}.parquet' UNION ALL SELECT b w, a c, n FROM '{S}/duck_tmp/p0_{label}.parquet') GROUP BY 1")
    os.remove(f"{S}/duck_tmp/p0_{label}.parquet")
    con.execute("CREATE OR REPLACE TABLE flag AS SELECT w, top_c c, N, hhi FROM ws WHERE N>=100 AND hhi>=0.5")
    con.execute("CREATE OR REPLACE TABLE fp AS SELECT least(w,c) a, greatest(w,c) b, count(*) k FROM flag GROUP BY 1,2")
    con.execute(f"""COPY (SELECT '{label}' period, cat, coalesce(cm.cls,'other') cls, fee_flag, sum(p.vol) vol, sum(p.n) n,
        sum(CASE WHEN fp.a IS NOT NULL THEN p.vol ELSE 0 END) pair_vol, sum(CASE WHEN fp.k=2 THEN p.vol ELSE 0 END) recip_vol,
        sum(CASE WHEN fp.a IS NOT NULL THEN p.n ELSE 0 END) pair_n, sum(CASE WHEN fp.k=2 THEN p.n ELSE 0 END) recip_n
        FROM read_parquet({files(ds)}) p LEFT JOIN fp USING (a,b) LEFT JOIN cm USING (cat) WHERE a<>b GROUP BY ALL) TO '{S}/pairs_out/{label}_agg.parquet' (FORMAT PARQUET)""")
    con.execute(f"""COPY (SELECT '{label}' period, (SELECT count(*) FROM ws) n_wallets, (SELECT count(*) FROM ws WHERE N>=100) n_wallets_ge100, (SELECT count(*) FROM flag) n_flagged,
        (SELECT count(*) FROM fp) n_flagged_pairs, (SELECT count(*) FROM fp WHERE k=2) n_recip_pairs,
        (SELECT median(hhi) FROM ws WHERE N>=100) med_hhi_ge100, (SELECT quantile_cont(hhi,0.9) FROM ws WHERE N>=100) p90_hhi_ge100,
        (SELECT sum(N) FROM flag) flagged_wallet_fills, (SELECT sum(N) FROM ws) total_wallet_fills) TO '{S}/pairs_out/{label}_wal.parquet' (FORMAT PARQUET)""")
    print(label, len(ds), "days", round(time.time()-t,1), "s", flush=True)
if MODE=='month':
    for m in sorted(set(d[:7] for d in days)): run(m, [d for d in days if d.startswith(m)])
else:
    wk_of=lambda d: (dt.date.fromisoformat(d.replace('_','-')) - dt.timedelta(days=dt.date.fromisoformat(d.replace('_','-')).weekday())).isoformat()
    for w in sorted(set(wk_of(d) for d in days)): run("W"+w, [d for d in days if wk_of(d)==w])
print("done", MODE, round(time.time()-t0), "s")
