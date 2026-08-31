import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
from feeclass import map_market, CLASSES
import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',500)
md=pd.read_parquet(f'{ATLAS}/market_day.parquet')
md['d']=pd.to_datetime(md.d)
mc=pd.read_parquet(f'{ATLAS}/market_class.parquet')[['condition_id','cls']]
md=md.merge(mc,on='condition_id',how='left')
md['fee_share']=md.n_fee_fills/md.n_fills
# ---- per-market fee start
g=md.sort_values('d').groupby('condition_id')
mk=g.agg(category=('category','first'),cls=('cls','first'),src=('src','first'),neg_risk=('neg_risk','first'),
         first_day=('d','min'),last_day=('d','max'),n_days=('d','count'),n_fills=('n_fills','sum'),notional=('notional','sum'),
         n_fee_fills=('n_fee_fills','sum'),fee_val=('fee_val','sum'),taker_base_fee=('taker_base_fee','max'),
         opens_at=('opens_at','min'),close_at=('close_at','min'),resolved_at=('resolved_at','min'),slug=('market_slug','first')).reset_index()
fs=md[md.fee_share>=0.5].groupby('condition_id').d.min().rename('fee_start_day')
mk=mk.merge(fs,on='condition_id',how='left')
mk['fee_share_life']=mk.n_fee_fills/mk.n_fills
# any fee day before/after: does fee status switch within life?
first_fee_any=md[md.n_fee_fills>0].groupby('condition_id').d.min().rename('first_fee_day')
last_nofee=md[md.fee_share<0.5].groupby('condition_id').d.max().rename('last_nofee_day')
mk=mk.merge(first_fee_any,on='condition_id',how='left').merge(last_nofee,on='condition_id',how='left')
mk['switch_within_life']=(mk.fee_start_day.notna()) & (mk.fee_start_day>mk.first_day)
mk['fee_from_birth']=(mk.fee_start_day.notna()) & (mk.fee_start_day==mk.first_day)
mk['nofee_after_start']=(mk.fee_start_day.notna()) & (mk.last_nofee_day>mk.fee_start_day)
mk.to_parquet(f'{ATLAS}/market_fee_start.parquet', index=False)
print('markets', len(mk), 'with fee start', mk.fee_start_day.notna().sum())
print('fee_from_birth', mk.fee_from_birth.sum(), 'switch_within_life', mk.switch_within_life.sum(), 'nofee day after start', mk.nofee_after_start.sum())
sw=mk[mk.switch_within_life]
print('switchers by class:\n', sw.groupby('cls').agg(n=('condition_id','count'),notional=('notional','sum'),med_days_before=('n_days','median')).to_string())
print('switchers: distribution of fee_start_day (top 15):\n', sw.fee_start_day.value_counts().head(15).to_string())
# taker_base_fee vs fee fills: markets with taker_base_fee>0 but 0 fee fills
print('markets tbf>0:', (mk.taker_base_fee>0).sum(), ' of which fee_share_life<0.5:', ((mk.taker_base_fee>0)&(mk.fee_share_life<0.5)).sum(),
      ' markets tbf=0 with any fee:', ((mk.taker_base_fee==0)&(mk.n_fee_fills>0)).sum())
# fee-share within fee markets (why not 100%?)
fm=md[md.taker_base_fee>0]
print('within fee-markets fee share of fills overall', fm.n_fee_fills.sum()/fm.n_fills.sum(), ' by month:')
print(fm.groupby(fm.d.dt.to_period('M')).apply(lambda x: x.n_fee_fills.sum()/x.n_fills.sum()).round(3).to_string())
# ---- class x day series
md['ym']=md.d.dt.to_period('M').astype(str)
cd=md.groupby(['cls','d']).agg(n_fills=('n_fills','sum'),n_fee_fills=('n_fee_fills','sum'),notional=('notional','sum'),notional_fee=('notional_fee','sum'),fee_val=('fee_val','sum'),n_markets=('condition_id','nunique'),
   n_mkts_fee=('taker_base_fee',lambda s:(s>0).sum())).reset_index()
cd['fee_share']=cd.n_fee_fills/cd.n_fills; cd['fee_share_notional']=cd.notional_fee/cd.notional
cd.to_parquet(f'{ATLAS}/class_day.parquet', index=False)
# first day class fee share >=0.5 (7-day rolling to smooth), and first day >0.1
rows=[]
for c,x in cd.sort_values('d').groupby('cls'):
    x=x.set_index('d'); r=(x.n_fee_fills.rolling('7D').sum()/x.n_fills.rolling('7D').sum())
    d50=r[r>=0.5].index.min(); d10=r[r>=0.1].index.min(); d01=x[x.n_fee_fills>0].index.min()
    apr=x[x.index>='2026-04-01']; aprs=apr.n_fee_fills.sum()/apr.n_fills.sum()
    rows.append(dict(cls=c,first_any_fee=d01,first_10pct=d10,first_50pct=d50,april_fee_share=round(aprs,3),april_fee_share_notional=round(apr.notional_fee.sum()/apr.notional.sum(),3),
                     notional_total=x.notional.sum(),n_fills=x.n_fills.sum(),fee_val=x.fee_val.sum(),n_markets=x.n_markets.sum()))
ct=pd.DataFrame(rows).sort_values('notional_total',ascending=False); ct.to_csv(f'{ATLAS}/q1_class_timing.csv',index=False)
print(ct.to_string())
# category-tag level timing (weekly), from market_day
md['week']=md.d-pd.to_timedelta(md.d.dt.weekday,unit='D')
cw=md.groupby(['category','week']).agg(n_fills=('n_fills','sum'),n_fee_fills=('n_fee_fills','sum'),notional=('notional','sum'),n_markets=('condition_id','nunique')).reset_index()
cw['fee_share']=cw.n_fee_fills/cw.n_fills
rows=[]
for c,x in cw.sort_values('week').groupby('category'):
    x=x.set_index('week'); apr=x[x.index>='2026-03-30']
    d50=x[x.fee_share>=0.5].index.min()
    # first week of a sustained (>=2 consecutive weeks) >=50%
    idx=list(x.index); sust=pd.NaT
    for i,w in enumerate(idx[:-1]):
        if x.fee_share.iloc[i]>=0.5 and x.fee_share.iloc[i+1]>=0.5: sust=w; break
    rows.append(dict(category=c,n_weeks=len(x),notional=x.notional.sum(),n_fills=x.n_fills.sum(),n_markets=x.n_markets.sum(),
        first_week_50=d50,first_sustained_50=sust,april_fee_share=(apr.n_fee_fills.sum()/apr.n_fills.sum()) if apr.n_fills.sum()>0 else np.nan,
        max_fee_share=x.fee_share.max(),last_week=x.index.max(), first_week=x.index.min()))
catt=pd.DataFrame(rows)
mcat=pd.read_parquet(f'{ATLAS}/market_class.parquet')
catt=catt.merge(mcat.groupby('category').cls.agg(lambda s:s.mode().iloc[0]).rename('cls_mode'),on='category',how='left')
catt['treated']=(catt.april_fee_share>=0.5)
catt['never_treated']=(catt.max_fee_share<0.05)&(catt.last_week>=pd.Timestamp('2026-04-06'))
catt.to_parquet(f'{ATLAS}/q1_category_timing.parquet',index=False); catt.sort_values('notional',ascending=False).to_csv(f'{ATLAS}/q1_category_timing.csv',index=False)
big=catt[catt.notional>=5e6].sort_values('notional',ascending=False)
print(big[['category','cls_mode','notional','n_markets','first_week_50','first_sustained_50','april_fee_share','max_fee_share','treated','never_treated']].to_string())
print('treated cats', catt.treated.sum(), 'never', catt.never_treated.sum(), 'ambiguous', (~catt.treated & ~catt.never_treated).sum())
print(catt.groupby('cls_mode').agg(n=('category','count'),treated=('treated','sum'),never=('never_treated','sum'),notional=('notional','sum')).to_string())
