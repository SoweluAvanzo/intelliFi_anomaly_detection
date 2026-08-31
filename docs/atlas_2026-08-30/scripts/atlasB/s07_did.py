import sys, numpy as np, pandas as pd, duckdb
sys.path.insert(0,'/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasB')
import did
pd.set_option('display.width',250); pd.set_option('display.max_columns',40)
S="/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasB"
A="/home/sowelo/Scrivania/IntelliFi_anomaly_detection/data/parquet/atlas"
panel_file, ycol, ncol, minn, tag = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
p=pd.read_parquet(panel_file)
p['wk']=pd.to_datetime(p['wk'])
unit_cols=[c for c in ['cat','catr'] if c in p.columns]
p['unit']=p[unit_cols].astype(str).agg('|'.join,axis=1)
p=p[(p.vol>0)].copy(); p['fee_share']=p.fee_vol/p.vol; p['y']=p[ycol]/p.vol
p=p[p.wk<=pd.Timestamp('2026-04-20')]  # drop partial last week (Apr 27-28)
tr=did.assign_treatment(p[['unit','wk','fee_share']].assign(fee_share=p.fee_share), ['unit'])
p=p.merge(tr,on='unit'); p['g']=pd.to_datetime(p['g'])
cls_of=p.groupby('unit').cls.first()
def prep(df):
    d=df[(df[ncol]>=minn)&(df.status.isin(['treated','never']))].copy()
    nw=d.groupby('unit').wk.nunique(); d=d[d.unit.isin(nw[nw>=8].index)].copy()
    d['D']=((d.status=='treated')&(d.wk>=d.g)).astype(float)
    return d
d=prep(p)
print(f"== {tag}: outcome={ycol}/vol, min {ncol}>={minn}; units treated={d[d.status=='treated'].unit.nunique()} never={d[d.status=='never'].unit.nunique()} ambiguous-dropped={p[p.status=='ambiguous'].unit.nunique()}; obs={len(d)}; weeks {d.wk.min().date()}..{d.wk.max().date()}")
print("treated cohorts (first fee week -> n tags):", d[d.status=='treated'].groupby('unit').g.first().dt.date.value_counts().sort_index().to_dict())
print("treated tags by class:", cls_of[d[d.status=='treated'].unit.unique()].value_counts().to_dict()); print("never-treated by class:", cls_of[d[d.status=='never'].unit.unique()].value_counts().to_dict())
print("pre-period level (vol-weighted y, weeks before Jan 5 2026): treated=%.4f never=%.4f" % tuple(np.average(x.y, weights=x.vol) for x in [d[(d.status=='treated')&(d.wk<'2026-01-05')], d[(d.status=='never')&(d.wk<'2026-01-05')]]))
rows=[]
for wname,w in [('vol-weighted','vol'),('unweighted','one')]:
    d['one']=1.0
    r=did.static_did(d,'y',w,'unit','wk','D','unit'); r2=did.static_did(d,'y',w,'unit','wk','D','cls')
    X=did.demean(d,['y','D'],['unit','wk'],w)
    pw,t0,nd=did.wild_cluster_p(X[:,0],X[:,1:],d[w].to_numpy(float),d['cls'].to_numpy(),0,n_fe=d.unit.nunique()+d.wk.nunique())
    rows.append(dict(spec='TWFE static',weights=wname,beta=r['beta'],se_tag=r['se'],G_tag=r['G'],se_cls=r2['se'],G_cls=r2['G'],p_wild_cls=pw,N=r['N']))
    rs,Sst=did.stacked_event(d,'y',w,'unit','wk','g','unit',K=8,static=True)
    rs2,_=did.stacked_event(d,'y',w,'unit','wk','g','cls',K=8,static=True)
    Sst['one']=1.0; X=did.demean(Sst,['y','post'],['su','st'],w)
    pw2,_,_=did.wild_cluster_p(X[:,0],X[:,1:],Sst[w].to_numpy(float),Sst['cls'].to_numpy(),0,n_fe=Sst.su.nunique()+Sst.st.nunique())
    rows.append(dict(spec='stacked static (-8..+8)',weights=wname,beta=rs['beta'],se_tag=rs['se'],G_tag=rs['G'],se_cls=rs2['se'],G_cls=rs2['G'],p_wild_cls=pw2,N=rs['N']))
res=pd.DataFrame(rows); print(res.round(5).to_string()); res.to_parquet(f"{A}/wash_did_{tag}_static.parquet",index=False)
ev,_=did.stacked_event(d,'y','vol','unit','wk','g','unit',K=8); ev2,_=did.stacked_event(d,'y','vol','unit','wk','g','cls',K=8)
ev['se_cls']=ev2['se']; ev.loc[len(ev)]=dict(k=-1,beta=0.0,se=0.0,n_treated_obs=int((_['k']==-1).sum()),se_cls=0.0); ev=ev.sort_values('k')
ev['t_tag']=ev.beta/ev.se.replace(0,np.nan)
print("Event-time (stacked, vol-weighted; ref k=-1; k in weeks relative to tag's first fee week; endpoints binned)"); print(ev.round(5).to_string(index=False)); ev.to_parquet(f"{A}/wash_did_{tag}_eventtime.parquet",index=False)
# per-class heterogeneity: static stacked by treated class
het=[]
for c in sorted(d[d.status=='treated'].cls.unique()):
    dd=d[(d.status=='never')|(d.cls==c)]
    if dd[dd.status=='treated'].unit.nunique()<2: continue
    r,_=did.stacked_event(dd,'y','vol','unit','wk','g','unit',K=8,static=True); het.append(dict(treated_class=c,beta=r['beta'],se_tag=r['se'],n_treated_tags=r['n_treated_units']))
het=pd.DataFrame(het); print("heterogeneity by treated class (stacked static, never-treated controls, cluster tag):"); print(het.round(5).to_string(index=False)); het.to_parquet(f"{A}/wash_did_{tag}_byclass.parquet",index=False)
d[['unit','cls','wk','vol',ncol,'fee_share','y','status','g','D']].to_parquet(f"{S}/did_sample_{tag}.parquet",index=False)
