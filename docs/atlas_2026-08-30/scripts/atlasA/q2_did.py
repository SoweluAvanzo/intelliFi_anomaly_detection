import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
from econ import *
import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',500)
cw=pd.read_parquet(f'{ATLAS}/category_week.parquet'); cw['week']=pd.to_datetime(cw.week)
cw=cw[cw.n_days==7]
ct=pd.read_parquet(f'{ATLAS}/q1_category_timing.parquet')
cw=cw.merge(ct[['category','cls_mode','first_sustained_50','treated','never_treated','april_fee_share','max_fee_share']],on='category',how='left')
cw['fee_share']=cw.n_fee_fills/cw.n_fills
cw['spread']=cw.sp_w_sum/cw.sp_w            # volume-weighted (min-side) mean of vwap_buy - vwap_sell within (token, minute); price units
cw['rspread']=cw.rsp_w_sum/cw.sp_w          # relative to mid
cw['spread_unw']=cw.sp_sum/cw.n_minpairs
cw['log_notional']=np.log(cw.notional); cw['log_orders']=np.log(cw.n_orders); cw['log_takers']=np.log(cw.n_takers); cw['log_makers']=np.log(cw.n_makers)
cw['log_ord_mean']=np.log(cw.ord_mean); cw['log_ord_med']=np.log(cw.ord_med); cw['log_fills']=np.log(cw.n_fills)
cw['log_markets']=np.log(cw.n_markets)
# sample: category-weeks with >=100 fills and >=20 minute-pairs; categories with >=12 weeks in sample and present in >=2 weeks pre-Jan
s=cw[(cw.n_fills>=100)].copy()
nweeks=s.groupby('category').week.nunique(); s=s[s.category.isin(nweeks[nweeks>=12].index)]
# treated categories: sustained >=50% ; never treated: max fee share <5% and active in April
s['g']=s.first_sustained_50
s['never']=s.never_treated.fillna(False)
s['D']=((s.week>=s.g)&s.g.notna()).astype(float)
s['rel']=((s.week-s.g).dt.days//7)
main=s[(s.g.notna())|(s.never)].copy()
print('panel: cat-weeks',len(main),'categories',main.category.nunique(),'treated',main[main.g.notna()].category.nunique(),'never',main[main.never].category.nunique())
print('cohorts:\n', main[main.g.notna()].groupby('category').g.first().value_counts().sort_index().to_string())
main.to_parquet(f'{ATLAS}/q2_panel_category_week.parquet',index=False)
outcomes=[('log_notional','log taker notional'),('log_orders','log n taker orders'),('log_takers','log n distinct takers'),('log_makers','log n distinct makers'),
          ('hhi','maker HHI (volume)'),('top5','top-5 maker share'),('spread','spread proxy (price units, min-vol weighted)'),('rspread','relative spread proxy'),
          ('log_ord_mean','log mean taker order size'),('log_ord_med','log median taker order size'),('fee_share','fee share of fills (first stage)')]
# --- TWFE static + event study
rows=[]; es_rows=[]; cs_rows=[]; cs_summ=[]
for k in range(-8,9):
    main[f'ev_{k}']=0.0
tr=main.g.notna()
relc=main.rel.clip(-8,8)
for k in range(-8,9):
    if k==-1: continue
    main[f'ev_{k}']=((relc==k)&tr).astype(float)
evcols=[f'ev_{k}' for k in range(-8,9) if k!=-1]
for y,lab in outcomes:
    res,V,n,G=twfe(main,y,['D'])
    rows.append(dict(outcome=y,label=lab,beta=res.coef[0],se=res.se[0],t=res.t[0],n=n,G=G))
    r,V,n,G=twfe(main,y,evcols)
    r['outcome']=y; r['k']=[int(c.split('_')[1]) for c in r.term]
    pre_idx=[i for i,c in enumerate(evcols) if int(c.split('_')[1])<=-2]
    W,p=wald(r.coef.values[pre_idx],V[np.ix_(pre_idx,pre_idx)])
    r['pretrend_wald']=W; r['pretrend_p']=p
    es_rows.append(r)
    cs,summ=cs_att(main,y,B=400)
    cs['outcome']=y; cs_rows.append(cs); summ['outcome']=y; cs_summ.append(summ)
twfe_tab=pd.DataFrame(rows); es_tab=pd.concat(es_rows); cs_tab=pd.concat(cs_rows); cs_s=pd.DataFrame(cs_summ)
twfe_tab.to_csv(f'{ATLAS}/q2_twfe_static.csv',index=False); es_tab.to_csv(f'{ATLAS}/q2_twfe_eventstudy.csv',index=False)
cs_tab.to_csv(f'{ATLAS}/q2_cs_eventtime.csv',index=False); cs_s.to_csv(f'{ATLAS}/q2_cs_summary.csv',index=False)
print('\nTWFE static (D = week >= category fee-start; category+week FE; category-clustered SE)'); print(twfe_tab.round(4).to_string())
print('\nCS-style ATT (never-treated controls, long diff from g-1; cluster bootstrap 400)'); print(cs_s.round(4).to_string())
for y,lab in outcomes:
    e=es_tab[es_tab.outcome==y]; c=cs_tab[cs_tab.outcome==y]
    m=e[['k','coef','se']].merge(c[['k','att','se','n_treated_units']],on='k',how='outer',suffixes=('_twfe','_cs')).sort_values('k')
    print(f'\n== event time: {lab}  | pre-trend Wald(k<=-2) p = {e.pretrend_p.iloc[0]:.3f}'); print(m.round(4).to_string(index=False))
# --- descriptive pre/post means by class (treated classes) vs controls
cls_tab=main.groupby(['cls_mode','D']).agg(n=('category','size'),notional=('notional','mean'),hhi=('hhi','mean'),top5=('top5','mean'),spread=('spread','mean'),ord_med=('ord_med','mean'),ord_mean=('ord_mean','mean'),fee_share=('fee_share','mean')).round(4)
print('\nclass-level means by treatment status:\n', cls_tab.to_string())
cls_tab.to_csv(f'{ATLAS}/q2_class_means.csv')
# --- robustness: continuous dose (fee share), weighted by pre-period notional
main['fee_share_dose']=main.fee_share
rows=[]
for y,lab in outcomes[:-1]:
    r,V,n,G=twfe(main,y,['fee_share_dose']); rows.append(dict(outcome=y,spec='dose=fee share, unweighted',beta=r.coef[0],se=r.se[0],n=n,G=G))
pre_w=main[main.week<'2026-01-05'].groupby('category').notional.mean().rename('w_pre')
mw=main.merge(pre_w,on='category',how='inner')
for y,lab in outcomes[:-1]:
    r,V,n,G=twfe(mw,y,['D'],weights='w_pre'); rows.append(dict(outcome=y,spec='binary D, weighted by pre-period notional',beta=r.coef[0],se=r.se[0],n=n,G=G))
# all categories incl. partially treated with dose
s2=s.copy()
for y,lab in outcomes[:-1]:
    r,V,n,G=twfe(s2,y,['fee_share']); rows.append(dict(outcome=y,spec='dose=fee share, all categories (incl. partial)',beta=r.coef[0],se=r.se[0],n=n,G=G))
rob=pd.DataFrame(rows); rob.to_csv(f'{ATLAS}/q2_robustness.csv',index=False); print('\nrobustness:\n',rob.round(4).to_string())
