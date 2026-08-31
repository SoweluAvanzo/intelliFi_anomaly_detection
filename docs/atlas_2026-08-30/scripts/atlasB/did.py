"""Two-way FE DiD / stacked event study with cluster-robust SEs (numpy only)."""
import numpy as np, pandas as pd, itertools

def demean(df, cols, fe_cols, w, tol=1e-10, maxit=500):
    X=df[cols].to_numpy(float).copy(); wv=df[w].to_numpy(float)
    codes=[pd.factorize(df[c])[0] for c in fe_cols]
    sws=[np.bincount(cd, weights=wv) for cd in codes]
    for it in range(maxit):
        X_old=X.copy()
        for cd,sw in zip(codes,sws):
            for j in range(X.shape[1]):
                m=np.bincount(cd, weights=wv*X[:,j])/sw
                X[:,j]-=m[cd]
        if np.max(np.abs(X-X_old))<tol: break
    return X

def cluster_ols(y, X, w, cluster, n_fe=0):
    sw=np.sqrt(w); Xw=X*sw[:,None]; yw=y*sw
    XtX=Xw.T@Xw; XtXi=np.linalg.pinv(XtX); beta=XtXi@(Xw.T@yw)
    u=yw-Xw@beta
    cd=pd.factorize(cluster)[0]; G=cd.max()+1
    Sg=pd.DataFrame(Xw*u[:,None]).groupby(cd).sum().to_numpy()
    meat=Sg.T@Sg
    N,K=X.shape; K2=K+n_fe
    adj=G/(G-1)*(N-1)/max(N-K2,1)
    V=adj*XtXi@meat@XtXi
    return beta, np.sqrt(np.diag(V)), G, u, cd

def wild_cluster_p(y, X, w, cluster, j, B=999, seed=0, n_fe=0):
    """Wild cluster bootstrap (Rademacher) p-value for H0: beta_j=0, null imposed. Full enumeration if G<=12."""
    sw=np.sqrt(w); Xw=X*sw[:,None]; yw=y*sw
    cd=pd.factorize(cluster)[0]; G=cd.max()+1
    # restricted fit (drop column j)
    keep=[k for k in range(X.shape[1]) if k!=j]
    Xr=Xw[:,keep]; br=np.linalg.pinv(Xr.T@Xr)@(Xr.T@yw); ur=yw-Xr@br; fit=Xr@br
    beta,se,_,_,_=cluster_ols(y,X,w,cluster,n_fe); t0=beta[j]/se[j]
    rng=np.random.default_rng(seed)
    if G<=12: draws=np.array(list(itertools.product([-1,1],repeat=G)))
    else: draws=rng.choice([-1,1],size=(B,G))
    ts=[]
    XtXi=np.linalg.pinv(Xw.T@Xw)
    for e in draws:
        ystar=fit+ur*e[cd]
        b=XtXi@(Xw.T@ystar); u=ystar-Xw@b
        Sg=pd.DataFrame(Xw*u[:,None]).groupby(cd).sum().to_numpy()
        N,K=X.shape; adj=G/(G-1)*(N-1)/max(N-K-n_fe,1)
        V=adj*XtXi@(Sg.T@Sg)@XtXi
        ts.append(b[j]/np.sqrt(V[j,j]))
    ts=np.array(ts)
    return float(np.mean(np.abs(ts)>=abs(t0))), float(t0), len(draws)

def assign_treatment(panel, unit_cols, thr_on=0.5, thr_never=0.05):
    """panel: unit-week rows with fee_share. Returns unit table with g (first treated week) or NaT for never-treated; ambiguous dropped."""
    p=panel.sort_values('wk')
    rows=[]
    for key,g in p.groupby(unit_cols, sort=False):
        fs=g.set_index('wk')['fee_share']
        mx=fs.max()
        on=fs[fs>=thr_on]
        if len(on)>0:
            # first week >=thr where next observed week also >= thr (or it is the last observed week)
            wks=list(fs.index); gdate=None
            for wk in on.index:
                i=wks.index(wk)
                if i==len(wks)-1 or fs.iloc[i+1]>=thr_on: gdate=wk; break
            rows.append(dict(zip(unit_cols,key if isinstance(key,tuple) else (key,)))|dict(g=gdate, status='treated' if gdate is not None else 'ambiguous', max_fee_share=mx))
        elif mx<thr_never:
            rows.append(dict(zip(unit_cols,key if isinstance(key,tuple) else (key,)))|dict(g=pd.NaT, status='never', max_fee_share=mx))
        else:
            rows.append(dict(zip(unit_cols,key if isinstance(key,tuple) else (key,)))|dict(g=pd.NaT, status='ambiguous', max_fee_share=mx))
    return pd.DataFrame(rows)

def static_did(df, y, w, unit, time, D, cluster):
    """TWFE: y ~ unit FE + time FE + D. Returns beta, se(cluster), G, N."""
    X=demean(df,[y,D],[unit,time],w)
    b,se,G,_,_=cluster_ols(X[:,0],X[:,1:],df[w].to_numpy(float),df[cluster].to_numpy(),n_fe=df[unit].nunique()+df[time].nunique())
    return dict(beta=float(b[0]),se=float(se[0]),G=int(G),N=len(df))

def stacked_event(df, y, w, unit, time, gcol, cluster, K=8, static=False):
    """Stacked (cohort-by-cohort) design: treated units of cohort g in event window [-K,K] + never-treated (g NaT) in the same calendar weeks.
    FE: (stack,unit), (stack,time). Event dummies k in [-K..K]\{-1} (endpoints binned) for treated units only."""
    weeks=np.sort(df[time].unique())
    never=df[df[gcol].isna()]
    parts=[]
    for g in np.sort(df[gcol].dropna().unique()):
        g=pd.Timestamp(g); gi=np.searchsorted(weeks,np.datetime64(g))
        win=weeks[max(gi-K,0):gi+K+1]
        tr=df[(df[gcol]==g)&(df[time].isin(win))].copy(); tr['k']=((tr[time]-g).dt.days//7).clip(-K,K)
        ct=never[never[time].isin(win)].copy(); ct['k']=np.nan
        if len(tr)==0: continue
        s=pd.concat([tr,ct]); s['stack']=str(g.date()); parts.append(s)
    S=pd.concat(parts, ignore_index=True)
    S['su']=S['stack']+'|'+S[unit].astype(str); S['st']=S['stack']+'|'+S[time].astype(str)
    if static:
        S['post']=((S['k']>=0)&S['k'].notna()).astype(float)
        X=demean(S,[y,'post'],['su','st'],w)
        b,se,G,_,_=cluster_ols(X[:,0],X[:,1:],S[w].to_numpy(float),S[cluster].to_numpy(),n_fe=S['su'].nunique()+S['st'].nunique())
        return dict(beta=float(b[0]),se=float(se[0]),G=int(G),N=len(S),n_treated_units=int(S.loc[S.k.notna(),unit].nunique()),n_control_units=int(S.loc[S.k.isna(),unit].nunique()),cohorts=int(S['stack'].nunique())), S
    ks=[k for k in range(-K,K+1) if k!=-1]
    for k in ks: S[f'k{k}']=((S['k']==k)).astype(float)
    X=demean(S,[y]+[f'k{k}' for k in ks],['su','st'],w)
    b,se,G,_,_=cluster_ols(X[:,0],X[:,1:],S[w].to_numpy(float),S[cluster].to_numpy(),n_fe=S['su'].nunique()+S['st'].nunique())
    out=pd.DataFrame(dict(k=ks,beta=b,se=se)); out['n_treated_obs']=[int((S['k']==k).sum()) for k in ks]
    return out, S
