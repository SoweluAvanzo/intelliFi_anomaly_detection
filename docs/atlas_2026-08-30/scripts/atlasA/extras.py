import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',500)
mf=pd.read_parquet(f'{ATLAS}/market_fee_start.parquet')
fcm=mf[mf.fee_share_life>=0.5]
print('fee-charging markets', len(fcm), 'zero-fee fills inside them', 1-fcm.n_fee_fills.sum()/fcm.n_fills.sum())
print(fcm.groupby('cls').apply(lambda g: pd.Series(dict(n_mkts=len(g), zero_fee_fill_share=1-g.n_fee_fills.sum()/g.n_fills.sum(), notional=g.notional.sum()))).round(4).to_string())
print('markets tbf>0 but <50% fee fills by class:\n', mf[(mf.taker_base_fee>0)&(mf.fee_share_life<0.5)].groupby('cls').agg(n=('condition_id','count'),notional=('notional','sum'),fee_share=('fee_share_life','mean')).round(3).to_string())
# class-week panel summary for fee period
kw=pd.read_parquet(f'{ATLAS}/class_week.parquet'); kw['week']=pd.to_datetime(kw.week); kw=kw[kw.n_days==7]
kw['fee_share']=kw.n_fee_fills/kw.n_fills; kw['spread']=kw.sp_w_sum/kw.sp_w
t=kw.pivot(index='week',columns='cls',values='fee_share').round(2); print('\nfee share of fills by class-week:\n', t.to_string())
tot=kw.groupby('week').agg(notional=('notional','sum'),fee_val=('fee_val','sum'),n_fills=('n_fills','sum'),n_orders=('n_orders','sum'),n_takers=('n_takers','sum'),fee_fills=('n_fee_fills','sum'))
tot['fee_share']=tot.fee_fills/tot.n_fills; tot['fee_pct']=100*tot.fee_val/tot.notional; print('\nplatform weekly totals:\n', tot.round(3).to_string()); tot.to_csv(f'{ATLAS}/platform_week_totals.csv')
# panel description
p=pd.read_parquet(f'{ATLAS}/q2_panel_category_week.parquet')
tr=p[p.g.notna()].groupby('category').agg(g=('g','first'),cls=('cls_mode','first'),notional=('notional','sum')).sort_values(['g','notional'],ascending=[True,False])
print('\nTREATED categories (cohort = first sustained >=50% week):\n', tr.to_string())
nv=p[p.never].groupby('category').agg(cls=('cls_mode','first'),notional=('notional','sum'),max_fee=('max_fee_share','first')).sort_values('notional',ascending=False)
print('\nNEVER-TREATED categories (max fee share <5%, active in April):\n', nv.head(60).to_string()); print('n never', len(nv))
tr.to_csv(f'{ATLAS}/q2_treated_cohorts.csv'); nv.to_csv(f'{ATLAS}/q2_never_treated.csv')
# class-level pre/post table for treated classes using class_week (descriptive)
cls_start={'crypto_updown':'2026-01-05','crypto_other':'2026-03-16','sports':'2026-04-06','esports_tennis':'2026-03-30','weather':'2026-03-30','finance':'2026-04-06','culture':'2026-04-06'}
rows=[]
for c,g0 in cls_start.items():
    g=pd.Timestamp(g0); x=kw[kw.cls==c]
    pre=x[(x.week<g)&(x.week>=g-pd.Timedelta(weeks=8))]; post=x[(x.week>=g)]
    ctrl=kw[kw.cls.isin(['geopolitics_world','politics_us','finance_macro'])].groupby('week').agg(hhi=('hhi','mean'),top5=('top5','mean'),spread=('spread','mean'),ord_med=('ord_med','mean'),notional=('notional','sum'))
    cpre=ctrl[(ctrl.index<g)&(ctrl.index>=g-pd.Timedelta(weeks=8))]; cpost=ctrl[ctrl.index>=g]
    rows.append(dict(cls=c,fee_start=g0,n_pre=len(pre),n_post=len(post),
        hhi_pre=pre.hhi.mean(),hhi_post=post.hhi.mean(),hhi_ctrl_change=cpost.hhi.mean()-cpre.hhi.mean(),
        top5_pre=pre.top5.mean(),top5_post=post.top5.mean(),top5_ctrl_change=cpost.top5.mean()-cpre.top5.mean(),
        spread_pre=pre.spread.mean(),spread_post=post.spread.mean(),spread_ctrl_change=cpost.spread.mean()-cpre.spread.mean(),
        ordmed_pre=pre.ord_med.mean(),ordmed_post=post.ord_med.mean(),ordmed_ctrl_change_pct=100*(cpost.ord_med.mean()/cpre.ord_med.mean()-1),
        notional_pre_wk=pre.notional.mean(),notional_post_wk=post.notional.mean(),notional_ctrl_change_pct=100*(cpost.notional.mean()/cpre.notional.mean()-1),
        n_makers_pre=pre.n_makers.mean(),n_makers_post=post.n_makers.mean(),n_takers_pre=pre.n_takers.mean(),n_takers_post=post.n_takers.mean()))
ct=pd.DataFrame(rows); ct.to_csv(f'{ATLAS}/q2_class_prepost_descriptive.csv',index=False); print('\nclass pre/post (8 pre-weeks vs all post weeks; control = geopolitics/politics/macro classes):\n', ct.round(4).to_string())
