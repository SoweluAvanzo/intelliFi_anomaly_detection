import duckdb, polars as pl, numpy as np, time, glob
SCR="/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad"
t=time.time()
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SCR}/duck_tmp'")
panel = pl.read_parquet(f"{SCR}/dubach_repo/data/panel.parquet")
ids = [s.lower() for s in panel["market_id"].to_list()]
files = sorted(f for f in glob.glob("data/external/polymarket_v1/daily_aligned/2026_0[23]_*.parquet") if "2026_02_28"<=f.split("/")[-1][:10]<="2026_03_27")
print("days", len(files), flush=True)
con.execute("CREATE TABLE ids AS SELECT * FROM (VALUES " + ",".join(f"('{i}')" for i in ids) + ") t(cid)")
con.execute(f"""CREATE TABLE f AS
  SELECT row_number() OVER () AS rid, lower(condition_id) AS cid, lower(maker) AS maker, lower(taker) AS taker, block_timestamp AS ts, usdc_amount
  FROM read_parquet({files}) WHERE lower(condition_id) IN (SELECT cid FROM ids)""")
n=con.execute("SELECT count(*), count(DISTINCT cid) FROM f").fetchall(); print("rows, markets", n, round(time.time()-t), flush=True)
con.execute("CREATE INDEX i1 ON f(cid)")
for W in (256, 270, 300):
    con.execute(f"""CREATE OR REPLACE TABLE flagged AS
      SELECT DISTINCT rid FROM (
        SELECT a.rid FROM f a JOIN f b ON a.cid=b.cid AND a.maker=b.taker AND a.taker=b.maker AND a.maker<>a.taker AND abs(a.ts-b.ts)<={W} AND a.rid<>b.rid
      )""")
    res = con.execute("""
      SELECT f.cid, count(*)::DOUBLE AS n_rows, sum(CASE WHEN maker=taker THEN 1 ELSE 0 END)::DOUBLE AS n_direct,
             sum(CASE WHEN fl.rid IS NOT NULL THEN 1 ELSE 0 END)::DOUBLE AS n_flipped,
             (sum(CASE WHEN fl.rid IS NOT NULL THEN usdc_amount ELSE 0 END)/sum(usdc_amount))::DOUBLE AS flipped_usdc_share
      FROM f LEFT JOIN flagged fl USING(rid) GROUP BY f.cid""").pl()
    res = res.with_columns(((pl.col("n_direct")+pl.col("n_flipped"))/pl.col("n_rows")).alias("wash_share"))
    s = res["wash_share"].to_numpy()
    print(f"W={W}s: markets {len(res)} | direct total {res['n_direct'].sum()} | wash_share count-based: median {np.median(s)*100:.2f}% p90 {np.quantile(s,.9)*100:.2f}% p99 {np.quantile(s,.99)*100:.2f}% max {s.max()*100:.2f}% | pooled {(res['n_direct'].sum()+res['n_flipped'].sum())/res['n_rows'].sum()*100:.2f}% | usdc-share median {np.median(res['flipped_usdc_share'].to_numpy())*100:.2f}%", flush=True)
    res.write_parquet(f"{SCR}/sf7_replica_W{W}.parquet")
# compare with Dubach's shipped table
d = pl.read_parquet(f"{SCR}/dubach_repo/artifacts/sf7_wash.parquet").with_columns(pl.col("market_id").str.to_lowercase().alias("cid"))
ours = pl.read_parquet(f"{SCR}/sf7_replica_W270.parquet")
j = d.join(ours, on="cid", how="left")
print("Dubach shipped: median %.2f%% p90 %.2f%% p99 %.2f%% max %.2f%%" % tuple(np.quantile(d['wash_share'].to_numpy(), q)*100 for q in (.5,.9,.99,1.0)))
jj = j.drop_nulls(subset=["wash_share_right"])
print("markets matched", len(jj), "spearman", pl.DataFrame({"a":jj["wash_share"],"b":jj["wash_share_right"]}).select(pl.corr("a","b",method="spearman")).item())
print("his n_trades sum", d["n_trades"].sum(), "our rows sum", ours["n_rows"].sum())
print("elapsed", round(time.time()-t))
