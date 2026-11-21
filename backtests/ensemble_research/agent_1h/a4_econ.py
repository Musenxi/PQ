"""Economics under 1h fee 0.01: per-$ return by ask band x entry timing, all observed 1h asks
(farm1h FAIR/LATE/BAND + swing entries + probe orders/signals), deduped per (window, side, minute). Clustered by window."""
from obs import *
_,_,W1=load_1h()
pw=rd('live-probe-1h/settlements.jsonl.gz').groupby('slug').winner.first(); W1=pd.concat([W1,pw[~pw.index.isin(W1.index)]])
a=obs1h(); a=a[a.src!='swingbid'].copy(); a['w']=a.slug.map(W1); a=a.dropna(subset=['w'])
a['win']=(a.side==a.w).astype(float); a['min']=(a.off//60).astype(int)
a=a.sort_values('tsec').drop_duplicates(['slug','side','min'])
a['r01']=ret(a.win,a.price,a.tsec,r=0.01); a['r07']=ret(a.win,a.price,a.tsec,r=0.07); a['r00']=ret(a.win,a.price,a.tsec,r=0.0)
print('obs',len(a),'windows',a.slug.nunique())
bands=[(0,.3),(.3,.45),(.45,.55),(.55,.6),(.6,.75),(.75,.9),(.9,1.0)]
tb=[(0,5),(5,20),(20,45),(45,61)]
print('\nband: per-$ ret @fee.01 [clustered 95%CI] wr px | breakeven wr = px*(1+.01*(1-px))')
for lo,hi in bands:
    y=a[(a.price>=lo)&(a.price<hi)]
    if len(y)<3: continue
    print(f' [{lo:.2f},{hi:.2f})',fmt(cboot(y,'r01')),' wr=%.3f px=%.3f be=%.3f'%(y.win.mean(),y.price.mean(),(y.price*(1+.01*(1-y.price))).mean()))
print('\ntiming (minute buckets), all bands / band .55-.75:')
for lo,hi in tb:
    y=a[(a['min']>=lo)&(a['min']<hi)]; z=y[(y.price>=.55)&(y.price<=.75)]
    print(f' min[{lo},{hi})',fmt(cboot(y,'r01')),'| .55-.75:',fmt(cboot(z,'r01')) if len(z)>2 else '-')
# fee drag table
print('\nfee drag per $ at p (0.07 vs 0.01):',' '.join(f'p={p}:{.07*(1-p):.3f}/{.01*(1-p):.4f}' for p in [.3,.5,.65,.8,.9]))
# FAIR first-entry per window in 0.5-0.75 under both fees
d=pd.read_pickle('/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/dec1h.pkl')
f=d[(d.family=='FAIR')&(d.price>=.5)&(d.price<=.75)].sort_values('tsec').drop_duplicates('slug').copy()
f['r01']=ret(f.win,f.price,f.tsec,r=.01); f['r07']=ret(f.win,f.price,f.tsec,r=.07)
print('\nFAIR first/window 0.5-0.75: fee.07',fmt(cboot(f,'r07')),' fee.01',fmt(cboot(f,'r01')))
# sensitivity: exclude README outage range 2026-11-20 16:20 -> 11-21 05:51 UTC
OUT0,OUT1=1795198800-3600*0+1200-3600*3+3600*3, 0
