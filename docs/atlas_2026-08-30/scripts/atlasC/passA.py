import duckdb, os, sys, time, glob
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
BASE='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/external/polymarket_v1'
d=sys.argv[1]  # daily_aligned | daily_aligned_multi
out=f'{SC}/passA/{d}'; os.makedirs(out, exist_ok=True)
con=duckdb.connect()
con.execute(f"SET enable_progress_bar=false; PRAGMA threads=8; SET memory_limit='5GB'; SET temp_directory='{SC}/duckтmp_{d}';")
months=sys.argv[2].split(',') if len(sys.argv)>2 else None
files=sorted(glob.glob(f'{BASE}/{d}/*.parquet'))
def key(f):
    b=os.path.basename(f); ym=b[:7].replace('_','-'); dd=int(b[8:10])
    return ym+('a' if dd<=15 else 'b')
files=[f for f in files if (months is None or key(f) in months) and not os.path.exists(f'{out}/cond_'+key(f)+'.parquet')]
print('files to do', len(files), flush=True)
extra=", neg_risk_market_id" if d=='daily_aligned_multi' else ", NULL::VARCHAR AS neg_risk_market_id"
OFFS={'d14':1209600,'d7':604800,'d3':259200,'d1':86400,'h6':21600,'h1':3600,'h0':0}
acc={}
def flush(ym):
    for name in ['cond','asset','mkr','tkr','catmkr','cattkr','grp','win','condmon']:
        con.execute(f"COPY (SELECT * FROM acc_{name}) TO '{out}/{name}_{ym}.parquet' (FORMAT PARQUET)")
        con.execute(f"DELETE FROM acc_{name}")
cur=None; t0=time.time()
for i,f in enumerate(files):
    ym=os.path.basename(f)[:7].replace('_','-'); k=key(f)
    if k!=cur:
        if cur is not None: flush(cur)
        cur=k
    con.execute(f"""CREATE OR REPLACE TABLE dd AS SELECT asset_id, block_timestamp ts, price, maker, taker, taker_direction dir, usdc_amount usd, fee_usdc fee,
        usdc_amount/price AS sh, condition_id cid, outcome_seq seq, neg_risk, category, category_refined, outcome_label olabel, winning_outcome_label wlabel,
        resolution_status status, epoch(opens_at) opens_at, epoch(close_at) close_at, epoch(resolved_at) resolved_at, market_slug slug, '{ym}' ym {extra}
        FROM '{f}'""")
    if i==0:
        con.execute("CREATE TABLE acc_cond AS SELECT cid, any_value(neg_risk) neg_risk, any_value(category) category, any_value(category_refined) category_refined, any_value(slug) slug, any_value(neg_risk_market_id) nrm_id, min(opens_at) opens_at, min(close_at) close_at, min(resolved_at) resolved_at, any_value(status) status, any_value(wlabel) wlabel, min(ts) first_ts, max(ts) last_ts, count(*) n, sum(usd) usd, sum(sh) sh, sum(fee) fee, count(distinct seq) n_out, count(*) FILTER (WHERE resolved_at IS NULL) n_null_res FROM dd WHERE 1=0 GROUP BY 1")
        con.execute("CREATE TABLE acc_asset AS SELECT asset_id, cid, seq, any_value(olabel) olabel, max(olabel = wlabel) is_winner, count(*) n, sum(usd) usd, sum(sh) sh, min(ts) first_ts, max(ts) last_ts FROM dd WHERE 1=0 GROUP BY 1,2,3")
        con.execute("CREATE TABLE acc_mkr AS SELECT ym, maker, count(*) n, sum(usd) usd, sum(sh) sh FROM dd WHERE 1=0 GROUP BY 1,2")
        con.execute("CREATE TABLE acc_tkr AS SELECT ym, taker, count(*) n, sum(usd) usd, sum(sh) sh FROM dd WHERE 1=0 GROUP BY 1,2")
        con.execute("CREATE TABLE acc_catmkr AS SELECT ym, category, maker, count(*) n, sum(usd) usd FROM dd WHERE 1=0 GROUP BY 1,2,3")
        con.execute("CREATE TABLE acc_cattkr AS SELECT ym, category, taker, count(*) n, sum(usd) usd FROM dd WHERE 1=0 GROUP BY 1,2,3")
        con.execute("CREATE TABLE acc_condmon AS SELECT ym, cid, count(*) n, sum(usd) usd, sum(sh) sh, sum(fee) fee, count(distinct maker) n_mkr, count(distinct taker) n_tkr FROM dd WHERE 1=0 GROUP BY 1,2")
        con.execute("""CREATE TABLE acc_grp AS WITH g AS (SELECT ym, cid, taker, ts, count(*) n, count(distinct seq) ko, count(distinct dir) kd, count(distinct (seq,dir)) kc,
              count(*) FILTER (WHERE seq=1) n1, count(*) FILTER (WHERE seq=2) n2, sum(sh) FILTER (WHERE seq=1) sh1, sum(sh) FILTER (WHERE seq=2) sh2,
              sum(usd) FILTER (WHERE seq=1) usd1, sum(usd) FILTER (WHERE seq=2) usd2, sum(sh) FILTER (WHERE dir='BUY') shb, sum(sh) FILTER (WHERE dir='SELL') shs,
              sum(usd) FILTER (WHERE dir='BUY') usdb, sum(usd) FILTER (WHERE dir='SELL') usds, sum(sh) sh, sum(usd) usd FROM dd WHERE 1=0 GROUP BY 1,2,3,4)
            SELECT ym, cid, count(*) n_grp, sum(n) n_rows, sum(sh) sh, sum(usd) usd,
              count(*) FILTER (WHERE ko=2 AND kc=2 AND kd=2) n_grp_x, sum(n) FILTER (WHERE ko=2 AND kc=2 AND kd=2) n_rows_x,
              sum(least(n1,n2)) FILTER (WHERE ko=2 AND kc=2 AND kd=2) n_rows_x_min, sum(greatest(n1,n2)) FILTER (WHERE ko=2 AND kc=2 AND kd=2) n_rows_x_max,
              sum(least(sh1,sh2)) FILTER (WHERE ko=2 AND kc=2 AND kd=2) sh_x_min, sum(greatest(sh1,sh2)) FILTER (WHERE ko=2 AND kc=2 AND kd=2) sh_x_max,
              sum(shs) FILTER (WHERE ko=2 AND kc=2 AND kd=2) sh_x_sell, sum(shb) FILTER (WHERE ko=2 AND kc=2 AND kd=2) sh_x_buy,
              sum(usds) FILTER (WHERE ko=2 AND kc=2 AND kd=2) usd_x_sell, sum(usdb) FILTER (WHERE ko=2 AND kc=2 AND kd=2) usd_x_buy,
              sum(sh) FILTER (WHERE ko=2 AND kc=2 AND kd=2) sh_x, sum(usd) FILTER (WHERE ko=2 AND kc=2 AND kd=2) usd_x,
              count(*) FILTER (WHERE ko=2 AND kd=1) n_grp_x_samedir, sum(n) FILTER (WHERE ko=2 AND kd=1) n_rows_x_samedir, sum(sh) FILTER (WHERE ko=2 AND kd=1) sh_x_samedir,
              count(*) FILTER (WHERE kc>=3) n_grp_mixed, sum(n) FILTER (WHERE kc>=3) n_rows_mixed, sum(sh) FILTER (WHERE kc>=3) sh_mixed,
              count(*) FILTER (WHERE ko=1 AND kd=2) n_grp_samet_bothdir, sum(n) FILTER (WHERE ko=1 AND kd=2) n_rows_samet_bothdir
            FROM g GROUP BY 1,2""")
        wsel=", ".join([f"max_by(price, ts) FILTER (WHERE ts <= resolved_at - {o}) p_{k}, max(ts) FILTER (WHERE ts <= resolved_at - {o}) ts_{k}" for k,o in OFFS.items()])
        con.execute(f"CREATE TABLE acc_win AS SELECT asset_id, cid, any_value(resolved_at) resolved_at, count(*) n, {wsel} FROM dd WHERE 1=0 GROUP BY 1,2")
    con.execute("INSERT INTO acc_cond SELECT cid, any_value(neg_risk), any_value(category), any_value(category_refined), any_value(slug), any_value(neg_risk_market_id), min(opens_at), min(close_at), min(resolved_at), any_value(status), any_value(wlabel), min(ts), max(ts), count(*), sum(usd), sum(sh), sum(fee), count(distinct seq), count(*) FILTER (WHERE resolved_at IS NULL) FROM dd GROUP BY 1")
    con.execute("INSERT INTO acc_asset SELECT asset_id, cid, seq, any_value(olabel), max(olabel = wlabel), count(*), sum(usd), sum(sh), min(ts), max(ts) FROM dd GROUP BY 1,2,3")
    con.execute("INSERT INTO acc_mkr SELECT ym, maker, count(*), sum(usd), sum(sh) FROM dd GROUP BY 1,2")
    con.execute("INSERT INTO acc_tkr SELECT ym, taker, count(*), sum(usd), sum(sh) FROM dd GROUP BY 1,2")
    if ym>='2026-01':
        con.execute("INSERT INTO acc_catmkr SELECT ym, category, maker, count(*), sum(usd) FROM dd GROUP BY 1,2,3")
        con.execute("INSERT INTO acc_cattkr SELECT ym, category, taker, count(*), sum(usd) FROM dd GROUP BY 1,2,3")
    con.execute("INSERT INTO acc_condmon SELECT ym, cid, count(*), sum(usd), sum(sh), sum(fee), count(distinct maker), count(distinct taker) FROM dd GROUP BY 1,2")
    con.execute("""INSERT INTO acc_grp WITH g AS (SELECT ym, cid, taker, ts, count(*) n, count(distinct seq) ko, count(distinct dir) kd, count(distinct (seq,dir)) kc,
              count(*) FILTER (WHERE seq=1) n1, count(*) FILTER (WHERE seq=2) n2, sum(sh) FILTER (WHERE seq=1) sh1, sum(sh) FILTER (WHERE seq=2) sh2,
              sum(usd) FILTER (WHERE seq=1) usd1, sum(usd) FILTER (WHERE seq=2) usd2, sum(sh) FILTER (WHERE dir='BUY') shb, sum(sh) FILTER (WHERE dir='SELL') shs,
              sum(usd) FILTER (WHERE dir='BUY') usdb, sum(usd) FILTER (WHERE dir='SELL') usds, sum(sh) sh, sum(usd) usd FROM dd GROUP BY 1,2,3,4)
            SELECT ym, cid, count(*), sum(n), sum(sh), sum(usd),
              count(*) FILTER (WHERE ko=2 AND kc=2 AND kd=2), sum(n) FILTER (WHERE ko=2 AND kc=2 AND kd=2),
              sum(least(n1,n2)) FILTER (WHERE ko=2 AND kc=2 AND kd=2), sum(greatest(n1,n2)) FILTER (WHERE ko=2 AND kc=2 AND kd=2),
              sum(least(sh1,sh2)) FILTER (WHERE ko=2 AND kc=2 AND kd=2), sum(greatest(sh1,sh2)) FILTER (WHERE ko=2 AND kc=2 AND kd=2),
              sum(shs) FILTER (WHERE ko=2 AND kc=2 AND kd=2), sum(shb) FILTER (WHERE ko=2 AND kc=2 AND kd=2),
              sum(usds) FILTER (WHERE ko=2 AND kc=2 AND kd=2), sum(usdb) FILTER (WHERE ko=2 AND kc=2 AND kd=2),
              sum(sh) FILTER (WHERE ko=2 AND kc=2 AND kd=2), sum(usd) FILTER (WHERE ko=2 AND kc=2 AND kd=2),
              count(*) FILTER (WHERE ko=2 AND kd=1), sum(n) FILTER (WHERE ko=2 AND kd=1), sum(sh) FILTER (WHERE ko=2 AND kd=1),
              count(*) FILTER (WHERE kc>=3), sum(n) FILTER (WHERE kc>=3), sum(sh) FILTER (WHERE kc>=3),
              count(*) FILTER (WHERE ko=1 AND kd=2), sum(n) FILTER (WHERE ko=1 AND kd=2)
            FROM g GROUP BY 1,2""")
    con.execute(f"INSERT INTO acc_win SELECT asset_id, cid, any_value(resolved_at), count(*), {wsel} FROM dd WHERE resolved_at IS NOT NULL AND status='resolved' AND olabel = wlabel GROUP BY 1,2")
    if i%50==0: print(i, f, round(time.time()-t0), flush=True)
flush(cur)
print('done', time.time()-t0)
