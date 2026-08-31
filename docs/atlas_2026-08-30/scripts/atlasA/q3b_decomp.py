import sys; sys.path.insert(0, '/tmp/claude-1000/-home-sowelo-Scrivania-IntelliFi-anomaly-detection/1ca1568e-3e0a-4271-965d-872ec4a24b54/scratchpad/atlasA')
from common import *
import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',500)
con=connect()
fc=con.execute(f"""SELECT taker, sum(n_fills_fc) n_fills_fc, sum(notional_fc) notional_fc, sum(notional_fc_zerofee) notional_fc_zerofee, sum(fee_base_fc) fee_base_fc, sum(fee_val_fc) fee_val_fc
   FROM read_parquet('{ATLAS}/taker_week_feecharging.parquet') WHERE week>=TIMESTAMP '2026-01-05' AND week<=TIMESTAMP '2026-04-20' GROUP BY 1""").df()
tk=pd.read_parquet(f'{ATLAS}/q3_taker_window.parquet').merge(fc,on='taker',how='left').fillna({'notional_fc':0,'notional_fc_zerofee':0,'fee_base_fc':0,'fee_val_fc':0,'n_fills_fc':0})
print('check: fee_val total', tk.fee_val.sum()/1e6, 'fee_val in fee-charging mkts', tk.fee_val_fc.sum()/1e6)
def wavg(g):
    n=g.notional.sum(); nf=g.notional_fc.sum()
    return pd.Series(dict(n_takers=len(g), notional_total=n, fee_total=g.fee_val.sum(), fee_pct_of_notional=100*g.fee_val.sum()/n,
        median_taker_fee_pct=g.fee_pct.median(), share_notional_in_feecharging_mkts=nf/n,
        fee_pct_within_feecharging=100*g.fee_val_fc.sum()/nf if nf>0 else np.nan,
        schedule_rate_given_price_mix=100*0.10*g.fee_base_fc.sum()/nf if nf>0 else np.nan,
        zero_fee_share_within_feecharging=g.notional_fc_zerofee.sum()/nf if nf>0 else np.nan,
        avg_px_feecharging=np.nan))
dec=tk.groupby('decile').apply(wavg)
q99=tk.notional.quantile(0.99); q999=tk.notional.quantile(0.999)
top=pd.DataFrame({'top1pct':wavg(tk[tk.notional>=q99]),'top0.1pct':wavg(tk[tk.notional>=q999]),'ALL':wavg(tk)}).T
dec=pd.concat([dec,top]).drop(columns=['avg_px_feecharging']); dec['notional_share']=dec.notional_total/tk.notional.sum()
dec.to_csv(f'{ATLAS}/q3_incidence_by_size_decile_v2.csv'); print('\nBY SIZE DECILE (fee-charging = market with >=50% lifetime fee fills):\n', dec.round(4).to_string())
ten=tk.groupby('tenure',observed=True).apply(wavg).drop(columns=['avg_px_feecharging']); ten['notional_share']=ten.notional_total/tk.notional.sum()
ten.to_csv(f'{ATLAS}/q3_incidence_by_tenure_v2.csv'); print('\nBY TENURE:\n', ten.round(4).to_string())
ts=tk.groupby(['tenure','size3'],observed=True).apply(wavg)[['n_takers','notional_total','fee_pct_of_notional','share_notional_in_feecharging_mkts','fee_pct_within_feecharging','schedule_rate_given_price_mix','zero_fee_share_within_feecharging']]
ts.to_csv(f'{ATLAS}/q3_incidence_tenure_x_size_v2.csv'); print('\nTENURE x SIZE:\n', ts.round(4).to_string())
# taker-level zero-fee inside fee-charging markets: is it concentrated?
z=tk[tk.notional_fc>0].copy(); z['zshare']=z.notional_fc_zerofee/z.notional_fc
print('\nzero-fee notional inside fee-charging markets:', z.notional_fc_zerofee.sum()/1e6,'M =',100*z.notional_fc_zerofee.sum()/z.notional_fc.sum(),'% of fee-charging notional')
print('takers with zshare>0.9 & notional_fc>10k:', ((z.zshare>0.9)&(z.notional_fc>1e4)).sum(), '; their share of fee-charging notional:', z[(z.zshare>0.9)&(z.notional_fc>1e4)].notional_fc.sum()/z.notional_fc.sum())
zz=z.sort_values('notional_fc_zerofee',ascending=False); print('top-10/100 taker share of zero-fee notional:', zz.notional_fc_zerofee.head(10).sum()/z.notional_fc_zerofee.sum(), zz.notional_fc_zerofee.head(100).sum()/z.notional_fc_zerofee.sum())
print(z.groupby('decile').apply(lambda g: pd.Series(dict(zero_fee_share=g.notional_fc_zerofee.sum()/g.notional_fc.sum(), n_takers_fc=len(g), n_zshare_gt_0_9=int((g.zshare>0.9).sum())))).round(4).to_string())
# regression-style decomposition: log fee_pct_within_feecharging on log size (takers with notional_fc>=100)
r=z[(z.notional_fc>=100)].copy(); r['rate']=100*r.fee_val_fc/r.notional_fc; r['sched']=100*0.1*r.fee_base_fc/r.notional_fc; r['ls']=np.log10(r.notional)
b=r.groupby(pd.cut(r.ls,[0,2,3,4,5,6,9])).agg(n=('rate','size'),rate_vw=('fee_val_fc',lambda s: 0),).index
tab=r.groupby(pd.cut(r.ls,[0,2,3,4,5,6,9]),observed=True).apply(lambda g: pd.Series(dict(n=len(g),rate_vw=100*g.fee_val_fc.sum()/g.notional_fc.sum(),sched_vw=100*0.1*g.fee_base_fc.sum()/g.notional_fc.sum(),zero_share=g.notional_fc_zerofee.sum()/g.notional_fc.sum(),avg_px=g.px_w.sum()/g.notional.sum())))
print('\nwithin fee-charging markets by log10(size) bin:\n', tab.round(4).to_string()); tab.to_csv(f'{ATLAS}/q3_rate_by_logsize.csv')
