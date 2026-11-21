"""Tick table: per (slug,tick) spot state; sigma backout + imputation; vol proxies."""
import pandas as pd, numpy as np
from scipy.stats import norm
SP='/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/'
t=pd.read_pickle(SP+'rows.pkl')
exec(open('/home/user/PQ/backtests/ensemble_research/load.py').read().split('t,s,W=')[0])
s=pd.read_json(D+'farm-5m-old/settlements.jsonl.gz',lines=True)
ss=s.dropna(subset=['winner']).drop_duplicates('slug').copy()
ss['start']=ss.slug.str.split('-').str[-1].astype(int)
ss=ss.sort_values('start').set_index('start')
ss['d']=ss.close-ss.open
# trailing vol proxy: rms of prior windows' d within last 30 min (pre-entry info: prior windows fully settled? close of prev window known at its end = this start)
st=ss.index.values; d=ss.d.values
tv=[]
for i,x in enumerate(st):
    m=(st<x)&(st>=x-1800)
    tv.append(np.sqrt(np.mean(d[m]**2)) if m.sum()>=3 else np.nan)
ss['tvol']=tv
# sigma backout
k=t.groupby(['slug','tick']).agg(mo=('move_open','first'),fu=('fair_up','first'),tau=('tau','first'),op=('open','first'),start=('start','first'))
b=k.dropna(subset=['mo','fu']); b=b[(b.fu>0.02)&(b.fu<0.98)&(b.tau>60)]
b=b.assign(z=norm.ppf(b.fu)); b=b[np.abs(b.z)>0.15]
b['sig']=np.log(1+b.mo/b.op)/(b.z*np.sqrt(b.tau-40))
sig=b.groupby('start').sig.median()
ss['sig']=sig
ss['sig_imp']=ss.sig.copy()
# impute from nearest known within 15 min
ks=sig.index.values; kv=sig.values
for x in ss.index[ss.sig.isna()]:
    dd=np.abs(ks-x); j=dd.argmin()
    if dd[j]<=900: ss.loc[x,'sig_imp']=kv[j]
a=ss.sig.dropna(); print('n sig',len(a),'imputed cover',ss.sig_imp.notna().mean())
lag=pd.Series(a.values[1:],index=a.index[1:]); prev=pd.Series(a.values[:-1],index=a.index[1:])
ok=(a.index[1:]-a.index[:-1])<=600
print('sigma corr adjacent', np.corrcoef(np.log(lag[ok]),np.log(prev[ok]))[0,1])
print('corr log sig vs log tvol', ss[['sig','tvol']].dropna().pipe(lambda q: np.corrcoef(np.log(q.sig),np.log(q.tvol))[0,1]))
print('corr |d| vs sig*open*sqrt300', ss.dropna(subset=['sig']).pipe(lambda q: np.corrcoef(np.abs(q.d),q.sig*q.open*np.sqrt(300))[0,1]))
ss.to_pickle(SP+'win.pkl')
