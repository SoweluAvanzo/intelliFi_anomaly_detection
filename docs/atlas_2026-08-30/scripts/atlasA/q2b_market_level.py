import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
from econ import *
import pandas as pd, numpy as np
pd.set_option('display.width',250)
cols=['week','condition_id','n_fills','notional','n_fee_fills','n_takers','n_makers','n_orders','ord_mean','ord_med','hhi','top5','sp_w_sum','sp_w','n_minpairs','n_days']
mw=pd.read_parquet(f'{ATLAS}/market_week.parquet',columns=cols); mw['week']=pd.to_datetime(mw.week); mw=mw[mw.n_days==7]
mf=pd.read_parquet(f'{ATLAS}/market_fee_start.parquet',columns=['condition_id','category','cls','first_day','taker_base_fee','fee_share_life'])
mw=mw.merge(mf,on='condition_id',how='left')
mw['fee_mkt']=(mw.fee_share_life>=0.5).astype(float)   # fee-charging market (>=50% of lifetime fills carry a fee)
mw['age_w']=((mw.week-pd.to_datetime(mw.first_day)).dt.days//7)
mw['spread']=mw.sp_w_sum/mw.sp_w
for c in ['notional','n_takers','n_makers','n_orders','ord_mean','ord_med']: mw['log_'+c]=np.log(mw[c])
# Design B: within category x week, fee-bearing vs fee-free markets, same age band (young markets, age 0-3 weeks), weeks 2026-01-05..2026-04-20
s=mw[(mw.week>='2026-01-05')&(mw.n_fills>=50)&(mw.age_w.between(0,3))&(mw.cls!='meta_other')].copy()
s['cw']=s.category+'|'+s.week.dt.strftime('%Y%m%d')
# keep category-weeks that have both fee and non-fee markets
both=s.groupby('cw').fee_mkt.agg(['min','max']); keep=both[(both['min']==0)&(both['max']==1)].index
s=s[s.cw.isin(keep)]
print('design B sample: market-weeks',len(s),'category-weeks',s.cw.nunique(),'categories',s.category.nunique(),'fee mkts',int(s.fee_mkt.sum()))
for a in range(4): s[f'age{a}']=(s.age_w==a).astype(float)
rows=[]
for y in ['log_notional','log_n_takers','log_n_makers','log_n_orders','hhi','top5','spread','log_ord_mean','log_ord_med']:
    d=s.dropna(subset=[y]).copy()
    Z=demean_two_way(d,[y,'fee_mkt','age1','age2','age3'],'cw','cls')  # cw FE absorbs category x week; second dimension trivial
    b,V,e=ols_cluster(Z[:,0],Z[:,1:],d.category.values)
    rows.append(dict(outcome=y,beta_fee=b[0],se=np.sqrt(V[0,0]),n=len(d),G=d.category.nunique()))
rb=pd.DataFrame(rows); rb.to_csv(f'{ATLAS}/q2b_market_level_within_catweek.csv',index=False)
print(rb.round(4).to_string())
# by class
rows=[]
for c,g in s.groupby('cls'):
    if g.cw.nunique()<10: continue
    for y in ['hhi','top5','spread','log_ord_mean','log_n_takers']:
        d=g.dropna(subset=[y]).copy()
        Z=demean_two_way(d,[y,'fee_mkt','age1','age2','age3'],'cw','cls'); b,V,e=ols_cluster(Z[:,0],Z[:,1:],d.cw.values)
        rows.append(dict(cls=c,outcome=y,beta_fee=b[0],se=np.sqrt(V[0,0]),n=len(d),G=d.cw.nunique()))
rc=pd.DataFrame(rows); rc.to_csv(f'{ATLAS}/q2b_market_level_by_class.csv',index=False); print(rc.round(4).to_string())
