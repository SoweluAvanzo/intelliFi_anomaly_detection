import duckdb, glob
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
AT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas'
con=duckdb.connect(); con.execute("PRAGMA memory_limit='3GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
def q(s): r=con.execute(s).fetchall(); print(r); return r
fs=glob.glob('/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/fills/**/*.parquet', recursive=True)
EXCH="('0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e','0xc5d563a36ae78145c45a50134d48a1215220f80a')"
con.execute(f"""CREATE TABLE f AS SELECT exchange, block_number, epoch(ts_utc) ts, tx_hash, evt_index, lower(maker) maker, lower(taker) taker, maker_asset_id, taker_asset_id, token_id, outcome_index, maker_side, usdc, shares, price, (lower(taker) IN {EXCH}) is_taker_order, condition_id FROM read_parquet({fs})""")
q("SELECT condition_id, count(*), count(*) FILTER (WHERE is_taker_order) n_taker, count(*) FILTER (WHERE NOT is_taker_order) n_maker FROM f GROUP BY 1")
# taker order per tx: token & side
con.execute("""CREATE TABLE t AS SELECT tx_hash, condition_id, any_value(token_id) taker_token, any_value(maker_side) taker_side_raw, any_value(maker) taker_addr, count(*) n FROM f WHERE is_taker_order GROUP BY 1,2""")
q("SELECT n, count(*) FROM t GROUP BY 1 ORDER BY 1 LIMIT 5")
con.execute("""CREATE TABLE mf AS SELECT f.*, t.taker_token, (f.token_id <> t.taker_token) is_complement FROM f JOIN t USING (tx_hash, condition_id) WHERE NOT f.is_taker_order""")
print('on-chain maker fills: complement-leg share by count and shares, per condition')
q("SELECT condition_id, count(*) n, sum(is_complement::int) n_comp, sum(is_complement::int)/count(*) comp_row_share, sum(shares) FILTER (WHERE is_complement)/sum(shares) comp_share_share, sum(shares) sh, sum(shares) FILTER (WHERE is_complement) sh_comp FROM mf GROUP BY 1")
print('same-second rule applied to on-chain maker fills (taker, ts, condition, both tokens):')
q("""WITH g AS (SELECT taker, ts, condition_id, count(distinct token_id) ko, count(*) n, sum(shares) sh, sum(shares) FILTER (WHERE maker_side='SELL') sh_makersell, sum(shares) FILTER (WHERE maker_side='BUY') sh_makerbuy FROM mf GROUP BY 1,2,3)
 SELECT count(*) n_grp, sum(n) FILTER (WHERE ko=2)/sum(n) cross_row_share, sum(sh) FILTER (WHERE ko=2)/sum(sh) cross_sh_share FROM g""")
print('exchange splits (CTF) for these conditions vs complement-leg shares:')
con.execute(f"CREATE TABLE sp AS SELECT condition_id, sum(usd) FILTER (WHERE who='exch') split_exch, sum(usd) FILTER (WHERE who='nradapter') split_nr FROM '{SC}/ctf_splits_cond.parquet' GROUP BY 1")
con.execute(f"CREATE TABLE mg AS SELECT condition_id, sum(usd) FILTER (WHERE who='exch') merge_exch, sum(usd) FILTER (WHERE who='nradapter') merge_nr FROM '{SC}/ctf_merges_cond.parquet' GROUP BY 1")
q("""SELECT m.condition_id, sp.split_exch, sp.split_nr, mg.merge_exch, mg.merge_nr, sum(shares) FILTER (WHERE is_complement AND maker_side='BUY') comp_makerbuy_sh, sum(shares) FILTER (WHERE is_complement AND maker_side='SELL') comp_makersell_sh
   FROM mf m LEFT JOIN sp USING (condition_id) LEFT JOIN mg USING (condition_id) GROUP BY 1,2,3,4,5""")
# how do complement legs look in the archive? compare per-condition row counts: archive rows vs on-chain maker fills
con.execute(f"CREATE TABLE a AS SELECT condition_id, n_rows, sh, sh_x, sh_x_sell, sh_x_buy, sh_x_samedir, sh_mixed FROM '{SC}/fills_cond_x.parquet' WHERE condition_id IN (SELECT DISTINCT condition_id FROM f)")
q("SELECT a.*, x.n_maker, x.sh_chain, x.sh_comp FROM a JOIN (SELECT condition_id, count(*) n_maker, sum(shares) sh_chain, sum(shares) FILTER (WHERE is_complement) sh_comp FROM mf GROUP BY 1) x USING (condition_id)")
# per-tx: does the archive re-express complement legs at the taker's token? check with a direct join on (taker, ts, maker) for one condition
cid=con.execute("SELECT condition_id FROM f GROUP BY 1 ORDER BY count(*) LIMIT 1").fetchall()[0][0]
con.execute(f"CREATE TABLE mk AS SELECT * FROM '{AT}/struct_markets.parquet' WHERE condition_id='{cid}'")
q("SELECT condition_id, src, slug, first_ts, last_ts, n_fills FROM mk")
import os
first_ts,last_ts=con.execute("SELECT first_ts,last_ts FROM mk").fetchall()[0]
import datetime
days=[]
d=datetime.date.fromtimestamp(first_ts)
while d<=datetime.date.fromtimestamp(last_ts):
    days.append(d); d=d+datetime.timedelta(days=1)
BASE='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/external/polymarket_v1'
src=con.execute("SELECT src FROM mk").fetchall()[0][0]
dd='daily_aligned' if src=='binary' else 'daily_aligned_multi'
files=[f'{BASE}/{dd}/{x.strftime("%Y_%m_%d")}.parquet' for x in days if os.path.exists(f'{BASE}/{dd}/{x.strftime("%Y_%m_%d")}.parquet')]
con.execute(f"CREATE TABLE ar AS SELECT asset_id, block_timestamp ts, price, lower(maker) maker, lower(taker) taker, taker_direction, usdc_amount, usdc_amount/price sh, outcome_seq FROM read_parquet({files}) WHERE condition_id='{cid}'")
q("SELECT count(*) FROM ar"); q(f"SELECT count(*) FROM mf WHERE condition_id='{cid}'")
# join archive rows to on-chain maker fills on (maker, taker, ts, shares≈)
q(f"""SELECT m.is_complement, m.maker_side, a.taker_direction, (a.asset_id = m.token_id) same_token, count(*) FROM mf m JOIN ar a ON a.maker=m.maker AND a.taker=m.taker AND a.ts=m.ts AND abs(a.sh-m.shares)<0.01 WHERE m.condition_id='{cid}' GROUP BY 1,2,3,4 ORDER BY 5 DESC""")
q(f"""SELECT m.is_complement, count(*) n_chain, count(a.ts) n_matched FROM mf m LEFT JOIN ar a ON a.maker=m.maker AND a.taker=m.taker AND a.ts=m.ts AND abs(a.sh-m.shares)<0.01 WHERE m.condition_id='{cid}' GROUP BY 1""")
