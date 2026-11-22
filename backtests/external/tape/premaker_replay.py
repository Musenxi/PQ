import gzip, json, os, sys, numpy as np, pandas as pd
R='/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/ext_tape'
kind=sys.argv[1]; T={'5m':300,'15m':900,'1h':3600}[kind]
mdir,tdir=f'{R}/{kind}/meta',f'{R}/{kind}/trades'
rows_out=[]; pre_cov=[]
for fn in sorted(os.listdir(tdir)):
    if not fn.endswith('.json.gz'): continue
    s=int(fn.split('.')[0]); m=json.load(open(f'{mdir}/{s}.json'))
    try: op=[float(x) for x in json.loads(m['outcomePrices'])]
    except Exception: continue
    if sorted(op)!=[0.,1.]: continue
    up=op[0]==1.
    rr=json.load(gzip.open(f'{tdir}/{fn}','rt'))
    ts=np.array([r[0] for r in rr]); 
    pre_cov.append((ts<s).sum())
    rows_out.append((s,up,rr))
print(kind,'windows',len(rows_out),'windows with any pre-open fill',np.mean(np.array(pre_cov)>0).round(3), 'median pre fills',np.median(pre_cov))
def sim(b, lo, hi, strict=True):
    res=[]
    for s,up,rr in rows_out:
        fu=fd=False
        for t,oi,side,p,size,w in rr:
            dt=t-s
            if dt<lo or dt>hi: continue
            # implied Up price of this taker trade and whether it trades through my Up bid / Down bid
            upx = p if oi==0 else 1-p
            # taker SELL Up (side 0, oi 0) or taker BUY Down (side 1, oi 1) push Up price down -> hits Up bids
            hits_up = (oi==0 and side==0) or (oi==1 and side==1)
            hits_dn = (oi==1 and side==0) or (oi==0 and side==1)
            if hits_up and (upx<b if strict else upx<=b): fu=True
            if hits_dn and ((1-upx)<b if strict else (1-upx)<=b): fd=True
        pnl=0.
        if fu and fd: pnl=1-2*b
        elif fu: pnl=(1 if up else 0)-b
        elif fd: pnl=(0 if up else 1)-b
        res.append((s,fu,fd,pnl))
    return pd.DataFrame(res,columns=['s','fu','fd','pnl'])
for lo,hi in [(-300,-75),(-300,-120),(-75,-1)]:
  for b in [.45,.46,.47,.48,.49]:
    for strict in [True,False]:
        d=sim(b,lo,hi,strict); f=d[d.fu|d.fd]; n=len(f)
        if n==0: continue
        med=d.s.median()
        def st(x): 
            return '%+.4f(se %.4f,n%d)'%(x.pnl.mean(),x.pnl.std()/np.sqrt(max(len(x),1)),len(x))
        print(f'[{lo},{hi}] b={b} strict={strict} fillwin={n/len(d):.3f} both={(f.fu&f.fd).mean():.2f} per-fill-share pnl {st(f)} H1 {st(f[f.s<=med])} H2 {st(f[f.s>med])}')
