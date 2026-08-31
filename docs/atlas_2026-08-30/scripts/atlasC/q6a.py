import duckdb, pandas as pd, numpy as np
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
AT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas'
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
def q(s): r=con.execute(s).fetchall(); print(r); return r
pd.set_option('display.width',250)
OFFS=['d14','d7','d3','d1','h6','h1','h0']
con.execute(f"CREATE TABLE m AS SELECT * FROM '{AT}/struct_markets.parquet'")
print('markets by status / resolved_at availability / src:')
q("SELECT src, status, count(*) n, count(resolved_at) n_with_resolved_at FROM m GROUP BY 1,2 ORDER BY 1,2")
q("SELECT count(*) FILTER (WHERE status='resolved') n_resolved, count(*) FILTER (WHERE status='resolved' AND resolved_at IS NULL) excluded_null_resolved_at, count(*) FILTER (WHERE status='resolved' AND resolved_at IS NOT NULL) usable FROM m")
con.execute(f"CREATE TABLE w0 AS SELECT * FROM '{AT}/struct_winner_offsets_archive.parquet'")
q("SELECT count(*), count(distinct condition_id) FROM w0")
# conditions with two 'winner' assets (label ambiguity) -> drop
con.execute("CREATE TABLE dup AS SELECT condition_id FROM w0 GROUP BY 1 HAVING count(*)>1")
q("SELECT count(*) AS n_multi_winner_conditions FROM dup")
con.execute("""CREATE TABLE w AS SELECT w0.*, m.cls, m.src, m.close_at, m.status, m.usd AS mkt_usd, (w0.resolved_at < m.close_at) AS early, m.category
  FROM w0 JOIN m USING (condition_id) WHERE w0.condition_id NOT IN (SELECT condition_id FROM dup) AND m.status='resolved'""")
q("SELECT count(*), count(*) FILTER (WHERE early), count(*) FILTER (WHERE close_at IS NULL) FROM w")
q("SELECT count(*) AS resolved_with_ts_but_no_traded_winner FROM m WHERE status='resolved' AND resolved_at IS NOT NULL AND condition_id NOT IN (SELECT condition_id FROM w0)")
def stats(group_cols, where='1=1', name=''):
    rows=[]
    for k in OFFS:
        g=', '.join(group_cols) if group_cols else "'all'"
        df=con.execute(f"""SELECT {g} AS grp, '{k}' AS horizon, count(*) n_markets, count(p_{k}) n_with_fill,
            quantile_cont(abs(1-p_{k}),0.5) med, avg(abs(1-p_{k})) mean, quantile_cont(abs(1-p_{k}),0.9) p90,
            avg(CASE WHEN abs(1-p_{k})>0.5 THEN 1 ELSE 0 END) frac_wrong_side, avg(CASE WHEN abs(1-p_{k})<=0.05 THEN 1 ELSE 0 END) frac_within_5c
            FROM w WHERE {where} GROUP BY 1 ORDER BY 1""").df()
        rows.append(df)
    out=pd.concat(rows); out['horizon']=pd.Categorical(out.horizon, OFFS, ordered=True); out=out.sort_values(['grp','horizon'])
    print('\n==', name); print(out.to_string(index=False)); return out
a=stats([], name='ALL (non-NULL resolved_at, status=resolved)')
b=stats(['cls'], name='by class')
c=stats(["CASE WHEN early THEN 'early' ELSE 'at/after close_at' END"], name='early vs at/after close_at')
d=stats(["CASE WHEN early THEN 'early' ELSE 'at/after' END || ' | ' || cls"], name='early x class')
e=stats(["CASE WHEN mkt_usd>=1e5 THEN '>=100k' WHEN mkt_usd>=1e4 THEN '10k-100k' ELSE '<10k' END"], name='by market notional')
pd.concat([a.assign(cut='all'),b.assign(cut='class'),c.assign(cut='early'),d.assign(cut='early_x_class'),e.assign(cut='notional')]).to_parquet(f'{AT}/struct_q6a_platform.parquet')
pd.concat([a.assign(cut='all'),b.assign(cut='class'),c.assign(cut='early'),d.assign(cut='early_x_class'),e.assign(cut='notional')]).to_csv(f'{SC}/q6a_platform.csv',index=False)
# resolved_at year distribution of the usable sample
q("SELECT strftime(to_timestamp(resolved_at),'%Y-%m') ym, count(*) FROM w GROUP BY 1 ORDER BY 1")
# ---- corpus check ----
ids=[l.strip() for l in open('/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/snapshots/20260829/corpus_condition_ids.txt') if l.strip()]
con.execute("CREATE TABLE ids AS SELECT unnest(?) AS condition_id", [ids])
con.execute(f"CREATE TABLE cf AS SELECT * FROM '{SC}/corpus_fills.parquet'")
con.execute(f"CREATE TABLE snap AS SELECT condition_id, epoch(closed_time) closed_time, epoch(end_date) end_date, epoch(uma_end_date) uma_end_date FROM '/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/snapshots/20260829/markets/markets.parquet'")
con.execute(f"CREATE TABLE ctfres AS SELECT condition_id, res_t_hat FROM '{AT}/struct_ctf_resolution_time.parquet'")
con.execute("""CREATE TABLE cm AS SELECT i.condition_id, any_value(cf.resolved_at) resolved_at, any_value(cf.close_at) close_at, any_value(s.closed_time) closed_time, any_value(r.res_t_hat) res_t_hat,
   count(cf.ts) n_fills, max(cf.ts) last_ts, any_value(cf.winning_outcome_label) wlabel FROM ids i LEFT JOIN cf USING (condition_id) LEFT JOIN snap s USING (condition_id) LEFT JOIN ctfres r USING (condition_id) GROUP BY 1""")
q("SELECT count(*), count(*) FILTER (WHERE n_fills>0) in_archive, count(resolved_at) with_archive_resolved_at, count(closed_time) with_snapshot_closed_time, count(res_t_hat) with_ctf_res_time FROM cm")
q("SELECT quantile_cont(closed_time - res_t_hat,[0.1,0.5,0.9]) snapshot_closed_minus_ctf, quantile_cont(closed_time - last_ts,[0.1,0.5,0.9]) closed_minus_lastfill, quantile_cont(res_t_hat - last_ts,[0.1,0.5,0.9]) ctf_minus_lastfill FROM cm WHERE n_fills>0")
OFFSEC={'d14':1209600,'d7':604800,'d3':259200,'d1':86400,'h6':21600,'h1':3600,'h0':0}
res=[]
for anchor in ['resolved_at','closed_time','res_t_hat']:
    for k,o in OFFSEC.items():
        df=con.execute(f"""WITH wf AS (SELECT cf.condition_id, cf.ts, cf.price, cm.{anchor} anc FROM cf JOIN cm USING (condition_id) WHERE cf.outcome_label = cf.winning_outcome_label AND cm.{anchor} IS NOT NULL),
          l AS (SELECT condition_id, max_by(price, ts) p FROM wf WHERE ts <= anc - {o} GROUP BY 1)
          SELECT '{anchor}' anchor, '{k}' horizon, (SELECT count(*) FROM cm WHERE {anchor} IS NOT NULL AND n_fills>0) n_markets, count(*) n_with_fill, quantile_cont(abs(1-p),0.5) med, avg(abs(1-p)) mean, quantile_cont(abs(1-p),0.9) p90 FROM l""").df()
        res.append(df)
corp=pd.concat(res); print('\n== corpus (97 of 100 in archive)'); print(corp.to_string(index=False)); corp.to_csv(f'{SC}/q6a_corpus.csv',index=False); corp.to_parquet(f'{AT}/struct_q6a_corpus.parquet')
