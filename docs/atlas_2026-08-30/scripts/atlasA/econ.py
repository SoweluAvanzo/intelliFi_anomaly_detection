"""Minimal TWFE / event-study / CS-style DiD with category-clustered SEs (numpy only)."""
import numpy as np, pandas as pd
def demean_two_way(df, cols, unit, time, tol=1e-9, maxit=200):
    X=df[cols].astype(float).values.copy()
    u=df[unit].values; t=df[time].values
    for _ in range(maxit):
        old=X.copy()
        X-= pd.DataFrame(X).groupby(u).transform('mean').values
        X-= pd.DataFrame(X).groupby(t).transform('mean').values
        if np.abs(X-old).max()<tol: break
    return X
def ols_cluster(y, X, cl):
    """OLS with cluster-robust VCE (Liang-Zeger with G/(G-1) * (N-1)/(N-K))"""
    n,k=X.shape
    XtX_inv=np.linalg.pinv(X.T@X); b=XtX_inv@X.T@y; e=y-X@b
    groups=pd.factorize(cl)[0]; G=groups.max()+1
    meat=np.zeros((k,k))
    for g in range(G):
        m=groups==g; s=X[m].T@e[m]; meat+=np.outer(s,s)
    V=XtX_inv@meat@XtX_inv*(G/(G-1))*((n-1)/max(n-k,1))
    return b, V, e
def twfe(df, y, xcols, unit='category', time='week', weights=None):
    d=df.dropna(subset=[y]+xcols).copy()
    Z=demean_two_way(d,[y]+xcols,unit,time)
    yy=Z[:,0]; X=Z[:,1:]
    if weights is not None:
        w=np.sqrt(d[weights].values); yy=yy*w; X=X*w[:,None]
    b,V,e=ols_cluster(yy,X,d[unit].values)
    se=np.sqrt(np.diag(V))
    return pd.DataFrame(dict(term=xcols,coef=b,se=se,t=b/se)), V, len(d), d[unit].nunique()
def wald(b,V):
    from scipy import stats
    W=float(b@np.linalg.pinv(V)@b); k=len(b)
    return W, 1-stats.chi2.cdf(W,k)
def cs_att(df, y, unit='category', time='week', gcol='g', never='never', kmin=-8, kmax=8, B=500, seed=0, weights=None):
    """Callaway-Sant'Anna style ATT(g,k) with never-treated controls; long-difference from g-1.
       returns event-time aggregates (weighted by cohort size) with cluster-bootstrap SEs."""
    d=df[[unit,time,y,gcol,never]].dropna(subset=[y]).copy()
    weeks=sorted(d[time].unique()); widx={w:i for i,w in enumerate(weeks)}
    d['ti']=d[time].map(widx)
    piv=d.pivot(index=unit,columns='ti',values=y)
    meta=d.groupby(unit).agg(g=(gcol,'first'),never=(never,'first'))
    meta['gi']=meta.g.map(lambda x: widx.get(x,np.nan))
    units=piv.index.values; Y=piv.values
    nev=meta.never.values.astype(bool); gi=meta.gi.values
    cohorts=sorted(set(gi[~np.isnan(gi)]))
    def estimate(sel_units):
        # sel_units: boolean mask/weights over units (bootstrap resample counts)
        cnt=sel_units
        out={}
        for k in range(kmin,kmax+1):
            num=0.0; den=0.0
            for g in cohorts:
                g=int(g); tpre=g-1; tk=g+k
                if tpre<0 or tk<0 or tk>=Y.shape[1]: continue
                tr=(gi==g)&(cnt>0); ct=nev&(cnt>0)
                dtr=Y[tr,tk]-Y[tr,tpre]; wtr=cnt[tr]; ok=~np.isnan(dtr)
                dct=Y[ct,tk]-Y[ct,tpre]; wct=cnt[ct]; okc=~np.isnan(dct)
                if ok.sum()==0 or okc.sum()==0: continue
                att=np.average(dtr[ok],weights=wtr[ok])-np.average(dct[okc],weights=wct[okc])
                n=wtr[ok].sum(); num+=att*n; den+=n
            out[k]=num/den if den>0 else np.nan
        return out
    ones=np.ones(len(units))
    point=estimate(ones)
    rng=np.random.default_rng(seed); boots=[]
    for b in range(B):
        idx=rng.integers(0,len(units),len(units)); cnt=np.bincount(idx,minlength=len(units)).astype(float)
        boots.append(estimate(cnt))
    bt=pd.DataFrame(boots)
    res=pd.DataFrame({'k':list(point.keys()),'att':list(point.values())})
    res['se']=[bt[k].std(ddof=1) for k in res.k]
    # n treated units contributing at each k
    ntr=[]
    for k in res.k:
        c=0
        for g in cohorts:
            g=int(g); tk=g+k
            if g-1<0 or tk<0 or tk>=Y.shape[1]: continue
            tr=(gi==g); c+=int((~np.isnan(Y[tr,tk]-Y[tr,g-1])).sum())
        ntr.append(c)
    res['n_treated_units']=ntr
    post=res[(res.k>=0)]; pre=res[(res.k<=-2)]
    def agg_stat(bdf, ks):
        return bdf[ks].mean(axis=1)
    post_ks=[k for k in post.k if not np.isnan(point[k])]; pre_ks=[k for k in pre.k if not np.isnan(point[k])]
    summ=dict(att_post=np.nanmean([point[k] for k in post_ks]), se_post=agg_stat(bt,post_ks).std(ddof=1),
              att_pre=np.nanmean([point[k] for k in pre_ks]), se_pre=agg_stat(bt,pre_ks).std(ddof=1))
    return res, summ
