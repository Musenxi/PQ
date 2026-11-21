from common import *
def obs1h():
    L=[]
    t=rd('farm-1h/trades.jsonl.gz'); t=t[t.leg==1]; t['src']='farm1h'
    L.append(t[['ts','slug','side','price','src']])
    w=rd('farm-1h-swing/trades.jsonl.gz'); w['src']='swing'; L.append(w[['ts','slug','side','price','src']])
    for f in ['orders','signals']:
        o=rd(f'live-probe-1h/{f}.jsonl.gz'); o['price']=o.ask; o['src']='probe'; L.append(o[['ts','slug','side','price','src']])
    x=pd.concat(L); x['tsec']=tsec(x.ts).round(1); x['start']=start(x.slug)
    x=x.drop_duplicates(['slug','side','price','tsec']); x['off']=x.tsec-x.start
    return x
def obs5m():
    L=[]
    for d in ['farm-5m-old','farm-5m-band-farm2']:
        t=rd(f'{d}/trades.jsonl.gz'); t=t[t.leg==1] if 'leg' in t else t
        L.append(t[['ts','slug','side','price']])
    x=pd.concat(L); x['tsec']=tsec(x.ts).round(1); x['start']=start(x.slug)
    x=x.drop_duplicates(['slug','side','price','tsec']); x['off']=x.tsec-x.start
    return x
def winners5():
    W=[]
    for d in ['farm-5m-old','farm-5m-band-farm2']:
        W.append(winners(rd(f'{d}/settlements.jsonl.gz')))
    W=pd.concat(W); return W[~W.index.duplicated()]
