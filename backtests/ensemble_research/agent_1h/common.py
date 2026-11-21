import pandas as pd, numpy as np
D='/home/user/PQ/data/2026-11-22/'
FEECUT=1795305540
S2CUT=1795255200; S3CUT=1795262400
def rd(p): return pd.read_json(D+p, lines=True, convert_dates=False)
def tsec(col): return (pd.to_datetime(col,utc=True,format='ISO8601')-pd.Timestamp('1970-01-01',tz='UTC')).dt.total_seconds()
def start(slug): return slug.str.split('-').str[-1].astype(int)
def seg(st): return np.where(st<S2CUT,'S1',np.where(st<S3CUT,'S2','S3'))
def rate(ts,h1=True): return np.where(np.asarray(ts)<FEECUT,.07,(.01 if h1 else .05))
def winners(s):
    s=s.dropna(subset=['winner']); return s.groupby('slug').winner.agg(lambda x:x.mode()[0])
def load_1h():
    t=rd('farm-1h/trades.jsonl.gz'); s=rd('farm-1h/settlements.jsonl.gz')
    t['tsec']=tsec(t.ts); t['start']=start(t.slug); t['off']=t.tsec-t.start
    W=winners(s); t['winner']=t.slug.map(W)
    t=t[t.leg==1].dropna(subset=['winner']).copy()
    t['win']=(t.side==t.winner).astype(float)
    return t,s,W
def ret(win,p,ts,h1=True,r=None):
    rr=rate(ts,h1) if r is None else r
    return (win-p-rr*p*(1-p))/p
def cboot(df,val,cl='slug',B=4000,seed=0):
    """window-clustered bootstrap of ratio sum(val*w)/sum(w) ; here mean per-$ (each row = $1 equal stake)"""
    g=df.groupby(cl)[val].agg(['sum','count'])
    s=g['sum'].values; c=g['count'].values; n=len(g)
    if n<2: return (np.nan,np.nan,np.nan,n,len(df))
    rng=np.random.default_rng(seed); idx=rng.integers(0,n,(B,n))
    bs=s[idx].sum(1)/c[idx].sum(1)
    return (s.sum()/c.sum(), *np.percentile(bs,[2.5,97.5]), n, len(df))
def fmt(r): return f"{r[0]:+.3f} [{r[1]:+.3f},{r[2]:+.3f}] nW={r[3]} n={r[4]}"
