import pandas as pd, numpy as np
SP='/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/'
tp=pd.read_pickle(SP+'tape.pkl')
tp['win']=(tp.side==tp.winner).astype(float)
tp['fee']=np.where(tp.tsec<1795305540,.07,.05)*tp.price*(1-tp.price)
tp['ret']=(tp.win-tp.price-tp.fee)/tp.price
MED=np.median(tp.start.unique())
rng=np.random.default_rng(0)
def boot(r,B=4000):
    r=np.asarray(r); 
    if len(r)<5: return (np.nan,np.nan)
    m=r[rng.integers(0,len(r),(B,len(r)))].mean(1); return np.percentile(m,[2.5,97.5])
def summ(d,name=''):
    # d: one row per window with ret,start
    a=d[d.start<MED].ret; b=d[d.start>=MED].ret; lo,hi=boot(d.ret)
    return dict(rule=name,n=len(d),mean=d.ret.mean(),lo=lo,hi=hi,n1=len(a),h1=a.mean(),n2=len(b),h2=b.mean(),
                t=d.ret.mean()/(d.ret.std()/np.sqrt(len(d))) if len(d)>2 else np.nan)
