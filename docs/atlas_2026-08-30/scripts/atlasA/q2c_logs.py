import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
from econ import *
import pandas as pd, numpy as np
pd.set_option('display.width',250)
m=pd.read_parquet(f'{ATLAS}/q2_panel_category_week.parquet'); m['week']=pd.to_datetime(m.week)
m['log_hhi']=np.log(m.hhi); m['log_top5']=np.log(m.top5); m['log_spread']=np.log(m.spread.where(m.spread>0)); m['log_rspread']=np.log(m.rspread.where(m.rspread>0))
tr=m[m.g.notna()]; pre=tr[tr.week<tr.g]; post=tr[tr.week>=tr.g]; nv=m[m.never]
base=pd.DataFrame({'treated_pre_mean':pre[['notional','n_orders','n_takers','n_makers','hhi','top5','spread','rspread','ord_mean','ord_med','fee_share']].mean(),
                   'treated_pre_median':pre[['notional','n_orders','n_takers','n_makers','hhi','top5','spread','rspread','ord_mean','ord_med','fee_share']].median(),
                   'treated_post_mean':post[['notional','n_orders','n_takers','n_makers','hhi','top5','spread','rspread','ord_mean','ord_med','fee_share']].mean(),
                   'never_mean':nv[['notional','n_orders','n_takers','n_makers','hhi','top5','spread','rspread','ord_mean','ord_med','fee_share']].mean()})
print('baseline means (category-week panel):\n', base.round(5).to_string()); base.to_csv(f'{ATLAS}/q2_panel_baselines.csv')
print('share of category-weeks with spread proxy >0 (positive round-trip cost):', (m.spread>0).mean(), ' n_pos/n_minpairs mean:', (m.n_pos/m.n_minpairs).mean())
relc=m.rel.clip(-8,8); trm=m.g.notna()
evcols=[]
for k in range(-8,9):
    if k==-1: continue
    m[f'ev_{k}']=((relc==k)&trm).astype(float); evcols.append(f'ev_{k}')
rows=[]; es=[]
for y in ['log_hhi','log_top5','log_spread','log_rspread']:
    r,V,n,G=twfe(m,y,['D']); cs,summ=cs_att(m,y,B=300)
    r2,V2,n2,G2=twfe(m,y,evcols); pre_idx=[i for i,c in enumerate(evcols) if int(c.split('_')[1])<=-2]; W,p=wald(r2.coef.values[pre_idx],V2[np.ix_(pre_idx,pre_idx)])
    rows.append(dict(outcome=y,twfe_beta=r.coef[0],twfe_se=r.se[0],cs_att_post=summ['att_post'],cs_se_post=summ['se_post'],cs_att_pre=summ['att_pre'],cs_se_pre=summ['se_pre'],pretrend_p=p,n=n,G=G))
    r2['outcome']=y; r2['k']=[int(c.split('_')[1]) for c in r2.term]; cs['outcome']=y; es.append(r2[['outcome','k','coef','se']].merge(cs[['k','att','se','n_treated_units']],on='k',how='outer',suffixes=('_twfe','_cs')))
t=pd.DataFrame(rows); t.to_csv(f'{ATLAS}/q2_log_outcomes.csv',index=False); print('\nlog outcomes:\n', t.round(4).to_string())
e=pd.concat(es); e.to_csv(f'{ATLAS}/q2_log_outcomes_eventtime.csv',index=False)
for y in ['log_hhi','log_top5','log_spread']:
    print(f'\n== {y}'); print(e[e.outcome==y].sort_values('k').round(4).to_string(index=False))
