import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',500)
con=connect()   # PRAGMA memory_limit 4GB, threads 4
TW=f"{ATLAS}/taker_week_class.parquet"; MW=f"{ATLAS}/maker_week_class.parquet"; FS=f"{ATLAS}/wallet_first_seen.parquet"
fs_n=con.execute(f"SELECT count(*), min(first_any) FROM read_parquet('{FS}')").fetchall()[0]
print('wallets with first-seen', fs_n)
# ---- per-taker aggregates over the fee window (2026-01-05 .. 2026-04-26, full weeks)
W0,W1=pd.Timestamp('2026-01-05'),pd.Timestamp('2026-04-20')
agg_cols=['n_fills','notional','notional_fee','notional_feemkt','fee_val','fee_base','fee_base_fee','fee_base_feemkt','notional_buy','px_w']
sums=", ".join(f"sum({c}) {c}" for c in agg_cols)
tk=con.execute(f"""SELECT t.taker, {sums}, any_value(f.first_any) first_any, any_value(f.first_taker) first_taker
    FROM read_parquet('{TW}') t LEFT JOIN read_parquet('{FS}') f ON f.addr=t.taker
    WHERE t.week>=TIMESTAMP '2026-01-05' AND t.week<=TIMESTAMP '2026-04-20' GROUP BY 1""").df().set_index('taker')
tk['first_any_d']=pd.to_datetime(tk.first_any,unit='s')
tk['fee_pct']=100*tk.fee_val/tk.notional
tk['fee_pct_feemkt']=100*tk.fee_val/tk.notional_feemkt.replace(0,np.nan)
tk['share_feemkt']=tk.notional_feemkt/tk.notional
tk['exempt_share']=1-tk.notional_fee/tk.notional_feemkt.replace(0,np.nan)    # share of fee-market notional filled with fee==0
tk['mech_rate_feemkt']=100*0.10*tk.fee_base_feemkt/tk.notional_feemkt.replace(0,np.nan)  # what the 1000bps schedule implies given price mix
tk['avg_px']=tk.px_w/tk.notional
print('takers in window', len(tk), 'total notional', tk.notional.sum()/1e9, 'B; fee_val', tk.fee_val.sum()/1e6, 'M; overall fee % of notional', 100*tk.fee_val.sum()/tk.notional.sum())
# deciles by taker total notional (equal count)
tk['decile']=pd.qcut(tk.notional.rank(method='first'),10,labels=range(1,11))
def wavg(g):
    n=g.notional.sum(); nf=g.notional_feemkt.sum()
    return pd.Series(dict(n_takers=len(g), notional_total=n, notional_share=np.nan, fee_total=g.fee_val.sum(),
        fee_pct_vw=100*g.fee_val.sum()/n, fee_pct_median_taker=g.fee_pct.median(), fee_pct_mean_taker=g.fee_pct.mean(),
        share_notional_in_feemkts=nf/n, fee_pct_within_feemkts=100*g.fee_val.sum()/nf if nf>0 else np.nan,
        mech_rate_within_feemkts=100*0.10*g.fee_base_feemkt.sum()/nf if nf>0 else np.nan,
        exempt_share_feemkt_notional=1-g.notional_fee.sum()/nf if nf>0 else np.nan,
        min_notional=g.notional.min(), max_notional=g.notional.max(), avg_px=g.px_w.sum()/n))
dec=tk.groupby('decile').apply(wavg); dec['notional_share']=dec.notional_total/dec.notional_total.sum()
# top 1% and 0.1%
q99=tk.notional.quantile(0.99); q999=tk.notional.quantile(0.999)
top=pd.DataFrame({'top1pct':wavg(tk[tk.notional>=q99]),'top0.1pct':wavg(tk[tk.notional>=q999])}).T
top['notional_share']=top.notional_total/tk.notional.sum()
dec=pd.concat([dec,top]); dec.to_csv(f'{ATLAS}/q3_incidence_by_size_decile.csv'); print('\nfee incidence by taker size decile (window 2026-01-05..2026-04-26):\n', dec.round(4).to_string())
# tenure buckets by first-seen date
bins=[pd.Timestamp('2000-01-01'),pd.Timestamp('2024-01-01'),pd.Timestamp('2025-01-01'),pd.Timestamp('2025-07-01'),pd.Timestamp('2025-10-01'),pd.Timestamp('2026-01-05'),pd.Timestamp('2026-03-01'),pd.Timestamp('2026-03-30'),pd.Timestamp('2027-01-01')]
labels=['<2024','2024','2025H1','2025Q3','2025Q4 (pre-fee)','2026-01-05..02-28 (crypto fees live)','2026-03-01..03-29 (crypto+partial)','2026-03-30+ (schedule v2)']
tk['tenure']=pd.cut(tk.first_any_d,bins=bins,labels=labels,right=False)
ten=tk.groupby('tenure',observed=True).apply(wavg); ten['notional_share']=ten.notional_total/ten.notional_total.sum()
ten.to_csv(f'{ATLAS}/q3_incidence_by_tenure.csv'); print('\nfee incidence by taker tenure (first seen in archive, as taker or maker):\n', ten.round(4).to_string())
# tenure x size (coarse)
tk['size3']=pd.cut(tk.notional,[0,1e3,1e5,np.inf],labels=['<1k','1k-100k','>100k'])
ts=tk.groupby(['tenure','size3'],observed=True).apply(wavg)[['n_takers','notional_total','fee_pct_vw','share_notional_in_feemkts','fee_pct_within_feemkts','exempt_share_feemkt_notional']]
ts.to_csv(f'{ATLAS}/q3_incidence_tenure_x_size.csv'); print('\ntenure x size:\n', ts.round(4).to_string())
# by class (window)
cl=con.execute(f"""SELECT cls, {sums} FROM read_parquet('{TW}') WHERE week>=TIMESTAMP '2026-01-05' AND week<=TIMESTAMP '2026-04-20' GROUP BY 1""").df().set_index('cls')
cl['fee_pct']=100*cl.fee_val/cl.notional; cl['share_feemkt']=cl.notional_feemkt/cl.notional; cl['fee_pct_within_feemkt']=100*cl.fee_val/cl.notional_feemkt.replace(0,np.nan)
cl['mech_rate_feemkt']=100*0.1*cl.fee_base_feemkt/cl.notional_feemkt.replace(0,np.nan); cl['exempt_share']=1-cl.notional_fee/cl.notional_feemkt.replace(0,np.nan)
cl=cl.sort_values('notional',ascending=False); cl.to_csv(f'{ATLAS}/q3_incidence_by_class.csv'); print('\nby class:\n', cl[['notional','fee_val','fee_pct','share_feemkt','fee_pct_within_feemkt','mech_rate_feemkt','exempt_share']].round(4).to_string())
# exemption: who fills at fee=0 inside fee markets? concentration among takers
fm=tk[tk.notional_feemkt>0].copy(); fm['exempt_notional']=fm.notional_feemkt-fm.notional_fee
ex=fm.sort_values('exempt_notional',ascending=False)
print('\nexempt (zero-fee) notional inside fee markets: total', ex.exempt_notional.sum()/1e6,'M =', 100*ex.exempt_notional.sum()/fm.notional_feemkt.sum(),'% of fee-market notional')
print('share of exempt notional from top 10 / 100 takers:', ex.exempt_notional.head(10).sum()/ex.exempt_notional.sum(), ex.exempt_notional.head(100).sum()/ex.exempt_notional.sum())
print('takers with exempt_share>0.9 and feemkt notional>10k:', ((fm.exempt_share>0.9)&(fm.notional_feemkt>1e4)).sum(), ' their notional share of fee-market notional:', fm[(fm.exempt_share>0.9)&(fm.notional_feemkt>1e4)].notional_feemkt.sum()/fm.notional_feemkt.sum())
exd=fm.groupby('decile').apply(lambda g: pd.Series(dict(exempt_share=1-g.notional_fee.sum()/g.notional_feemkt.sum(), n_fully_exempt=int(((g.exempt_share>0.9)).sum()), n=len(g))))
print(exd.round(4).to_string()); exd.to_csv(f'{ATLAS}/q3_exemption_by_decile.csv')
# taker-level (window) table persisted (aggregates only, ~500k rows)
tk.reset_index().drop(columns=['first_any']).to_parquet(f'{ATLAS}/q3_taker_window.parquet',index=False)
# ---- maker composition: share of maker notional from makers first seen after 2026-01-05, by class-week
t0=pd.Timestamp('2026-01-05').timestamp(); t1=pd.Timestamp('2026-03-30').timestamp()
comp=con.execute(f"""SELECT cls, week, sum(notional) maker_notional,
      sum(CASE WHEN f.first_any>={t0} THEN notional ELSE 0 END)/sum(notional) new_maker_share,
      sum(CASE WHEN f.first_any>={t1} THEN notional ELSE 0 END)/sum(notional) new_maker_share_v2,
      count(DISTINCT maker) n_makers, count(DISTINCT CASE WHEN f.first_any>={t0} THEN maker END) n_new_makers
    FROM read_parquet('{MW}') m LEFT JOIN read_parquet('{FS}') f ON f.addr=m.maker GROUP BY 1,2 ORDER BY 1,2""").df()
comp.to_parquet(f'{ATLAS}/q3_maker_composition_class_week.parquet',index=False)
piv=comp.pivot(index='week',columns='cls',values='new_maker_share').round(3)
print('\nshare of maker notional from makers first seen on/after 2026-01-05, by class-week:\n', piv.to_string())
