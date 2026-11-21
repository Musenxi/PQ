import pandas as pd, numpy as np
from scipy.stats import norm
SP='/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/'
t=pd.read_pickle(SP+'rows.pkl'); ss=pd.read_pickle(SP+'win.pkl')
t=t.dropna(subset=['win'])
t['fee7']=0.07*t.price*(1-t.price)
t['ret']=(t.win-t.price-t.fee7)/t.price
t['sig']=t.start.map(ss.sig_imp); t['tvol']=t.start.map(ss.tvol)
t['d']=t.start.map(ss.d)
t['fair_side']=t.fair
t['z_side']=norm.ppf(t.fair_side.clip(0.001,0.999))
te=np.maximum(t.tau-40,np.where(t.tau<60,t.tau**3/(3*3600),1))
t['te']=np.where(t.tau>=60,t.tau-40,t.tau**3/(3*3600))
t['dist']=t.open*(np.exp(t.z_side*t.sig*np.sqrt(t.te))-1)  # $ toward traded side (s_est-open, signed)
MED=np.median(sorted(t.start.unique()))
t['half']=np.where(t.start<MED,1,2)
rng=np.random.default_rng(0)
def boot(df,col='ret',B=2000):
    """df must have one obs per window (or will be averaged per window first? no: cluster bootstrap)."""
    g=df.groupby('slug')[col].agg(['sum','size'])
    S=g['sum'].values; N=g['size'].values; n=len(g)
    if n<5: return (np.nan,np.nan,np.nan,n,len(df))
    idx=rng.integers(0,n,(B,n))
    m=S[idx].sum(1)/N[idx].sum(1)
    return (S.sum()/N.sum(), np.percentile(m,2.5), np.percentile(m,97.5), n, len(df))
def fmt(r): return f"{r[0]*100:+6.1f}% [{r[1]*100:+6.1f},{r[2]*100:+6.1f}] nW={r[3]} n={r[4]}"
def report(df,label,col='ret'):
    a=boot(df,col); h1=boot(df[df.half==1],col); h2=boot(df[df.half==2],col)
    print(f"{label:38s} ALL {fmt(a)} | H1 {h1[0]*100:+6.1f}% n{h1[3]} | H2 {fmt(h2)}")
    return a,h1,h2
