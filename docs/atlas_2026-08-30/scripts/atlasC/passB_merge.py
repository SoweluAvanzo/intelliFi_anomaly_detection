import duckdb, time
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
AT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas'
con=duckdb.connect()
con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
P=f"{SC}/passA"
def src(name):
    return f"(SELECT *, 'binary' src FROM read_parquet('{P}/daily_aligned/{name}_*.parquet') UNION ALL SELECT *, 'negrisk' src FROM read_parquet('{P}/daily_aligned_multi/{name}_*.parquet'))"
t=time.time()
# markets
con.execute(f"""COPY (SELECT cid AS condition_id, any_value(src) src, any_value(neg_risk) neg_risk, any_value(category) category, any_value(category_refined) category_refined,
  any_value(slug) slug, any_value(nrm_id) nrm_id, min(opens_at) opens_at, min(close_at) close_at, min(resolved_at) resolved_at, any_value(status) status, any_value(wlabel) wlabel,
  min(first_ts) first_ts, max(last_ts) last_ts, sum(n) n_fills, sum(usd) usd, sum(sh) sh, sum(fee) fee, max(n_out) n_out, sum(n_null_res) n_null_res,
  count(distinct src) n_src FROM {src('cond')} GROUP BY 1) TO '{AT}/struct_markets.parquet' (FORMAT PARQUET)""")
print('markets', time.time()-t, flush=True)
con.execute(f"""COPY (SELECT asset_id, cid condition_id, seq outcome_seq, any_value(olabel) outcome_label, max(is_winner) is_winner, sum(n) n_fills, sum(usd) usd, sum(sh) sh,
  min(first_ts) first_ts, max(last_ts) last_ts FROM {src('asset')} GROUP BY 1,2,3) TO '{AT}/struct_assets.parquet' (FORMAT PARQUET)""")
print('assets', time.time()-t, flush=True)
con.execute(f"""COPY (SELECT ym, maker, sum(n) n_fills, sum(usd) usd, sum(sh) sh FROM {src('mkr')} GROUP BY 1,2) TO '{AT}/struct_maker_month.parquet' (FORMAT PARQUET)""")
con.execute(f"""COPY (SELECT ym, taker, sum(n) n_fills, sum(usd) usd, sum(sh) sh FROM {src('tkr')} GROUP BY 1,2) TO '{AT}/struct_taker_month.parquet' (FORMAT PARQUET)""")
con.execute(f"""COPY (SELECT ym, category, maker, sum(n) n_fills, sum(usd) usd FROM {src('catmkr')} GROUP BY 1,2,3) TO '{SC}/catmkr_2026.parquet' (FORMAT PARQUET)""")
con.execute(f"""COPY (SELECT ym, category, taker, sum(n) n_fills, sum(usd) usd FROM {src('cattkr')} GROUP BY 1,2,3) TO '{SC}/cattkr_2026.parquet' (FORMAT PARQUET)""")
print('mkr/tkr', time.time()-t, flush=True)
con.execute(f"""COPY (SELECT ym, cid condition_id, sum(n) n_fills, sum(usd) usd, sum(sh) sh, sum(fee) fee, max(n_mkr) n_mkr, max(n_tkr) n_tkr FROM {src('condmon')} GROUP BY 1,2) TO '{AT}/struct_condmonth.parquet' (FORMAT PARQUET)""")
con.execute(f"""COPY (SELECT ym, cid condition_id, sum(n_grp) n_grp, sum(n_rows) n_rows, sum(sh) sh, sum(usd) usd, sum(n_grp_x) n_grp_x, sum(n_rows_x) n_rows_x, sum(n_rows_x_min) n_rows_x_min, sum(n_rows_x_max) n_rows_x_max,
  sum(sh_x_min) sh_x_min, sum(sh_x_max) sh_x_max, sum(sh_x_sell) sh_x_sell, sum(sh_x_buy) sh_x_buy, sum(usd_x_sell) usd_x_sell, sum(usd_x_buy) usd_x_buy, sum(sh_x) sh_x, sum(usd_x) usd_x,
  sum(n_grp_x_samedir) n_grp_x_samedir, sum(n_rows_x_samedir) n_rows_x_samedir, sum(sh_x_samedir) sh_x_samedir, sum(n_grp_mixed) n_grp_mixed, sum(n_rows_mixed) n_rows_mixed, sum(sh_mixed) sh_mixed,
  sum(n_grp_samet_bothdir) n_grp_samet_bothdir, sum(n_rows_samet_bothdir) n_rows_samet_bothdir FROM {src('grp')} GROUP BY 1,2) TO '{AT}/struct_mintgroups_condmonth.parquet' (FORMAT PARQUET)""")
print('grp', time.time()-t, flush=True)
# winner offsets: across months pick, per asset & offset, the record with the max ts
OFFS=['d14','d7','d3','d1','h6','h1','h0']
sel=", ".join([f"max_by(p_{k}, ts_{k}) p_{k}, max(ts_{k}) ts_{k}" for k in OFFS])
con.execute(f"""COPY (SELECT asset_id, cid condition_id, any_value(resolved_at) resolved_at, sum(n) n_fills, {sel} FROM {src('win')} GROUP BY 1,2) TO '{AT}/struct_winner_offsets_archive.parquet' (FORMAT PARQUET)""")
print('win', time.time()-t, flush=True)
