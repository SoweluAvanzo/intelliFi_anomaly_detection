import duckdb, pandas as pd, numpy as np
SC='/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasC'
AT='/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas'
con=duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4"); con.execute(f"PRAGMA temp_directory='{SC}/duck_tmp'"); con.execute("SET enable_progress_bar=false")
def q(s): r=con.execute(s).fetchall(); print(r); return r
pd.set_option('display.width',250); pd.set_option('display.max_columns',40)
for ev in ['splits','merges','redemptions']:
    con.execute(f"CREATE TABLE {ev} AS SELECT ym, condition_id, who, collateral_token coll, sum(n) n, sum(usd) usd FROM read_parquet('{SC}/ctf_month/{ev}_*.parquet') GROUP BY 1,2,3,4")
    q(f"SELECT '{ev}', count(*), sum(n), sum(usd), min(ym), max(ym) FROM {ev}")
con.execute(f"CREATE TABLE m AS SELECT condition_id, src, cls, usd mkt_usd FROM '{AT}/struct_markets.parquet'")
con.execute(f"CREATE TABLE cm AS SELECT ym, sum(usd) fill_usd, sum(sh) fill_sh, sum(n_fills) n_fills FROM '{AT}/struct_condmonth.parquet' GROUP BY 1")
con.execute(f"CREATE TABLE cmc AS SELECT c.ym, coalesce(m.cls,'?') cls, sum(c.usd) fill_usd, sum(c.sh) fill_sh FROM '{AT}/struct_condmonth.parquet' c LEFT JOIN m USING (condition_id) GROUP BY 1,2")
# coverage: CTF amounts on conditions present in the tape vs not
for ev in ['splits','merges','redemptions']:
    q(f"SELECT '{ev}', (m.condition_id IS NOT NULL) in_tape, count(*), sum(usd) FROM {ev} LEFT JOIN m USING (condition_id) GROUP BY 1,2")
q("SELECT who, sum(usd), sum(n) FROM splits GROUP BY 1 ORDER BY 2 DESC")
q("SELECT who, sum(usd), sum(n) FROM merges GROUP BY 1 ORDER BY 2 DESC")
q("SELECT who, min(ym), max(ym) FROM splits GROUP BY 1")
# ---- monthly table ----
mon=con.execute("""SELECT ym, coalesce(sp.split_usd,0) split_usd, coalesce(sp.split_exch,0) split_exch, coalesce(sp.split_nr,0) split_nradapter, coalesce(sp.split_ada,0) split_ada, coalesce(sp.split_other,0) split_other,
  coalesce(mg.merge_usd,0) merge_usd, coalesce(mg.merge_exch,0) merge_exch, coalesce(mg.merge_nr,0) merge_nradapter, coalesce(rd.redeem_usd,0) redeem_usd, cm.fill_usd, cm.fill_sh, cm.n_fills
  FROM cm LEFT JOIN (SELECT ym, sum(usd) split_usd, sum(usd) FILTER (WHERE who='exch') split_exch, sum(usd) FILTER (WHERE who='nradapter') split_nr, sum(usd) FILTER (WHERE who IN ('ada1','ada2')) split_ada, sum(usd) FILTER (WHERE who='other') split_other FROM splits GROUP BY 1) sp USING (ym)
  LEFT JOIN (SELECT ym, sum(usd) merge_usd, sum(usd) FILTER (WHERE who='exch') merge_exch, sum(usd) FILTER (WHERE who='nradapter') merge_nr FROM merges GROUP BY 1) mg USING (ym)
  LEFT JOIN (SELECT ym, sum(usd) redeem_usd FROM redemptions GROUP BY 1) rd USING (ym)
  WHERE ym BETWEEN '2023-01' AND '2026-04' ORDER BY ym""").df()
mon['mint_to_fill']=mon.split_usd/mon.fill_usd; mon['exch_mint_to_fill']=(mon.split_exch+mon.split_nradapter)/mon.fill_usd; mon['merge_to_fill']=mon.merge_usd/mon.fill_usd; mon['redeem_to_fill']=mon.redeem_usd/mon.fill_usd
mon['net_open_interest_flow']=mon.split_usd-mon.merge_usd-mon.redeem_usd
mon.to_parquet(f'{AT}/struct_q5_ctf_monthly.parquet'); mon.to_csv(f'{SC}/q5_ctf_monthly.csv',index=False)
print(mon[['ym','split_usd','split_exch','split_nradapter','split_ada','split_other','merge_usd','redeem_usd','fill_usd','mint_to_fill','exch_mint_to_fill','merge_to_fill','redeem_to_fill']].to_string())
tot=mon[['split_usd','split_exch','split_nradapter','split_ada','split_other','merge_usd','merge_exch','merge_nradapter','redeem_usd','fill_usd','fill_sh']].sum(); print('TOTAL 2023-01..2026-04'); print(tot.to_string()); print('mint/fill', tot.split_usd/tot.fill_usd, 'exch+nr mint/fill', (tot.split_exch+tot.split_nradapter)/tot.fill_usd, 'merge/fill', tot.merge_usd/tot.fill_usd, 'redeem/fill', tot.redeem_usd/tot.fill_usd)
yr=mon.assign(yr=mon.ym.str[:4]).groupby('yr')[['split_usd','split_exch','split_nradapter','split_ada','split_other','merge_usd','redeem_usd','fill_usd']].sum(); yr['mint_to_fill']=yr.split_usd/yr.fill_usd; yr['exch_mint_to_fill']=(yr.split_exch+yr.split_nradapter)/yr.fill_usd; yr['merge_to_fill']=yr.merge_usd/yr.fill_usd; yr['redeem_to_fill']=yr.redeem_usd/yr.fill_usd; print(yr.to_string()); yr.to_csv(f'{SC}/q5_ctf_yearly.csv')
# ---- by class (2023-01..2026-04) ----
byc=con.execute("""SELECT coalesce(m.cls,'not in tape') cls, sum(s.usd) split_usd, sum(s.usd) FILTER (WHERE who='exch') split_exch, sum(s.usd) FILTER (WHERE who='nradapter') split_nr, sum(s.usd) FILTER (WHERE who IN ('ada1','ada2')) split_ada, sum(s.usd) FILTER (WHERE who='other') split_other
  FROM splits s LEFT JOIN m USING (condition_id) WHERE ym BETWEEN '2023-01' AND '2026-04' GROUP BY 1""").df()
mgc=con.execute("""SELECT coalesce(m.cls,'not in tape') cls, sum(s.usd) merge_usd FROM merges s LEFT JOIN m USING (condition_id) WHERE ym BETWEEN '2023-01' AND '2026-04' GROUP BY 1""").df()
rdc=con.execute("""SELECT coalesce(m.cls,'not in tape') cls, sum(s.usd) redeem_usd FROM redemptions s LEFT JOIN m USING (condition_id) WHERE ym BETWEEN '2023-01' AND '2026-04' GROUP BY 1""").df()
fc=con.execute("SELECT cls, sum(fill_usd) fill_usd, sum(fill_sh) fill_sh FROM cmc WHERE ym BETWEEN '2023-01' AND '2026-04' GROUP BY 1").df()
byc=byc.merge(mgc,on='cls',how='outer').merge(rdc,on='cls',how='outer').merge(fc,on='cls',how='outer')
byc['mint_to_fill']=byc.split_usd/byc.fill_usd; byc['exch_mint_to_fill']=(byc.split_exch.fillna(0)+byc.split_nr.fillna(0))/byc.fill_usd; byc['merge_to_fill']=byc.merge_usd/byc.fill_usd; byc['redeem_to_fill']=byc.redeem_usd/byc.fill_usd
byc=byc.sort_values('fill_usd',ascending=False); print(byc.to_string()); byc.to_parquet(f'{AT}/struct_q5_ctf_by_class.parquet'); byc.to_csv(f'{SC}/q5_ctf_by_class.csv',index=False)
# by class x year
bcy=con.execute("""SELECT substr(s.ym,1,4) yr, coalesce(m.cls,'not in tape') cls, sum(s.usd) split_usd FROM splits s LEFT JOIN m USING (condition_id) WHERE ym BETWEEN '2023-01' AND '2026-04' GROUP BY 1,2""").df()
fcy=con.execute("SELECT substr(ym,1,4) yr, cls, sum(fill_usd) fill_usd FROM cmc WHERE ym BETWEEN '2023-01' AND '2026-04' GROUP BY 1,2").df()
bcy=bcy.merge(fcy,on=['yr','cls'],how='outer'); bcy['mint_to_fill']=bcy.split_usd/bcy.fill_usd
print(bcy.pivot(index='cls',columns='yr',values='mint_to_fill').to_string()); bcy.to_csv(f'{SC}/q5_ctf_by_class_year.csv',index=False)
# ---- reconciliation: exchange-driven splits vs fills-based cross-group shares, per condition (all-time) ----
con.execute(f"CREATE TABLE fx AS SELECT * FROM '{SC}/fills_cond_x.parquet'")
con.execute("""CREATE TABLE rec AS SELECT fx.condition_id, fx.src, fx.cls, fx.sh, fx.sh_x, fx.sh_x_sell, fx.sh_x_buy, fx.sh_x_min, fx.sh_x_max, fx.sh_x_samedir,
   coalesce(sp.exch,0) split_exch, coalesce(sp.nr,0) split_nr, coalesce(sp.ada,0) split_ada, coalesce(sp.oth,0) split_other, coalesce(mg.exch,0) merge_exch, coalesce(mg.nr,0) merge_nr
   FROM fx LEFT JOIN (SELECT condition_id, sum(usd) FILTER (WHERE who='exch') exch, sum(usd) FILTER (WHERE who='nradapter') nr, sum(usd) FILTER (WHERE who IN ('ada1','ada2')) ada, sum(usd) FILTER (WHERE who='other') oth FROM splits GROUP BY 1) sp USING (condition_id)
   LEFT JOIN (SELECT condition_id, sum(usd) FILTER (WHERE who='exch') exch, sum(usd) FILTER (WHERE who='nradapter') nr FROM merges GROUP BY 1) mg USING (condition_id)""")
print('\n== reconciliation totals (share units): binary markets, CTF-exchange splits vs fills cross-group SELL-side shares')
q("""SELECT src, count(*) n_cond, sum(split_exch) split_exch, sum(split_nr) split_nr, sum(split_ada) split_ada, sum(split_other) split_other, sum(merge_exch) merge_exch, sum(merge_nr) merge_nr,
   sum(sh_x_sell) sh_x_sell, sum(sh_x_buy) sh_x_buy, sum(sh_x_min) sh_x_min, sum(sh_x_max) sh_x_max, sum(sh_x_samedir) sh_x_samedir, sum(sh) sh FROM rec GROUP BY 1""")
print('per-condition ratio split_exch / sh_x_sell (binary, conditions with >=1000 cross shares):')
q("""SELECT count(*), quantile_cont(split_exch/sh_x_sell,[0.05,0.25,0.5,0.75,0.95]), avg(CASE WHEN abs(split_exch/sh_x_sell-1)<=0.05 THEN 1 ELSE 0 END) within5pct, avg(CASE WHEN abs(split_exch/sh_x_sell-1)<=0.10 THEN 1 ELSE 0 END) within10pct, corr(split_exch, sh_x_sell) r FROM rec WHERE src='binary' AND sh_x_sell>=1000""")
print('per-condition ratio split_exch / (sh_x_sell + sh_x_samedir):')
q("""SELECT count(*), quantile_cont(split_exch/(sh_x_sell+sh_x_samedir),[0.05,0.25,0.5,0.75,0.95]) FROM rec WHERE src='binary' AND sh_x_sell>=1000""")
print('per-condition ratio merge_exch / sh_x_buy (binary, >=1000):')
q("""SELECT count(*), quantile_cont(merge_exch/sh_x_buy,[0.05,0.25,0.5,0.75,0.95]), corr(merge_exch, sh_x_buy) FROM rec WHERE src='binary' AND sh_x_buy>=1000""")
print('negrisk: adapter splits / sh_x_sell:')
q("""SELECT count(*), quantile_cont(split_nr/sh_x_sell,[0.05,0.25,0.5,0.75,0.95]), corr(split_nr, sh_x_sell) FROM rec WHERE src='negrisk' AND sh_x_sell>=1000""")
q("""SELECT src, sum(split_exch)/sum(sh_x_sell) tot_ratio_exch_sell, sum(split_nr)/sum(sh_x_sell) tot_ratio_nr_sell, sum(merge_exch)/sum(sh_x_buy) tot_ratio_merge_buy, sum(merge_nr)/sum(sh_x_buy) FROM rec GROUP BY 1""")
# monthly reconciliation series (binary): exch splits vs fills sh_x_sell
mrec=con.execute(f"""SELECT g.ym, sum(g.sh_x_sell) sh_x_sell, sum(g.sh_x_buy) sh_x_buy, sum(g.sh) sh FROM '{AT}/struct_mintgroups_condmonth.parquet' g JOIN m USING (condition_id) WHERE m.src='binary' GROUP BY 1""").df()
srec=con.execute("""SELECT s.ym, sum(s.usd) split_exch FROM splits s JOIN m USING (condition_id) WHERE m.src='binary' AND s.who='exch' GROUP BY 1""").df()
mgrec=con.execute("""SELECT s.ym, sum(s.usd) merge_exch FROM merges s JOIN m USING (condition_id) WHERE m.src='binary' AND s.who='exch' GROUP BY 1""").df()
mrec=mrec.merge(srec,on='ym',how='left').merge(mgrec,on='ym',how='left').sort_values('ym'); mrec=mrec[(mrec.ym>='2023-01')&(mrec.ym<='2026-04')]
mrec['ratio_split_exch_over_sh_x_sell']=mrec.split_exch/mrec.sh_x_sell; mrec['ratio_merge_exch_over_sh_x_buy']=mrec.merge_exch/mrec.sh_x_buy; mrec['exch_mint_share_of_shares']=mrec.split_exch/mrec.sh
print(mrec.to_string()); mrec.to_csv(f'{SC}/q5_reconciliation_monthly.csv',index=False); mrec.to_parquet(f'{AT}/struct_q5_reconciliation_monthly.parquet')
con.execute(f"COPY (SELECT * FROM rec) TO '{AT}/struct_q5_reconciliation_cond.parquet' (FORMAT PARQUET)")
