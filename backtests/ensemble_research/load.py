import pandas as pd, numpy as np, json
D='/home/user/PQ/data/2026-11-22/'
def rd(p): return pd.read_json(D+p, lines=True)
def prep(t,s):
    t['ts']=pd.to_datetime(t['ts'],utc=True,format='ISO8601')
    t['tsec']=(t.ts-pd.Timestamp('1970-01-01',tz='UTC')).dt.total_seconds()
    t['start']=t.slug.str.split('-').str[-1].astype(int)
    t['off']=t.tsec-t.start
    s['start']=s.slug.str.split('-').str[-1].astype(int)
    w=s.dropna(subset=['winner']).groupby('slug').winner.agg(lambda x:x.mode()[0])
    t['winner']=t.slug.map(w)
    t['win']=(t.side==t.winner).astype(float); t.loc[t.winner.isna(),'win']=np.nan
    t['ppnl']=np.where(t.win==1, t.shares-t.cost, -t.cost)-t.fees  # per-trade hold-to-settle pnl
    return t,s,w
t,s,W=prep(rd('farm-5m-old/trades.jsonl.gz'),rd('farm-5m-old/settlements.jsonl.gz'))
def fee_ps(tsec, p, h1=False):
    r = np.where(tsec<1795219140, .07, (.01 if h1 else .05))
    return r*p*(1-p)
x=t[(t.leg==1)].dropna(subset=['win']).copy()
x['feeps']=fee_ps(x.tsec.values,x.price.values)
x['edge']=x.win-x.price-x.feeps   # per-share edge
x['ret']=x.edge/x.price            # per-$ return
first=x.sort_values('tsec').drop_duplicates(['family','slug'])
