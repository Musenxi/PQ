from common import *
t,s,W=load_1h()
o=rd('live-probe-1h/orders.jsonl.gz'); st=rd('live-probe-1h/settlements.jsonl.gz')
o['tsec']=tsec(o.ts); o['start']=start(o.slug)
pw=st.groupby('slug').winner.first()
Wall=pd.concat([W,pw[~pw.index.isin(W.index)]])
# probe fills (first fill per window = the cap-respecting one; S1 incident window had 4)
f=o[o.filled==1].sort_values('tsec')
f['px']=f.filled_cost/f.filled_shares
f['winner']=f.slug.map(Wall); f=f.dropna(subset=['winner']).copy(); f['win']=(f.side==f.winner).astype(float)
f['seg']=seg(f.start)
f['r']=ret(f.win,f.px,f.tsec)
f['inb']=(f.px>=0.6)&(f.px<=0.75)
print('probe fills',len(f),'windows',f.slug.nunique())
for sg,g in f.groupby('seg'): print(sg,'fills',len(g),'wr %.3f px %.3f'%(g.win.mean(),g.px.mean()),fmt(cboot(g,'r')))
b=f[f.inb]; print('probe in-band 0.6-0.75 fills',len(b),'wr %.3f px %.3f'%(b.win.mean(),b.px.mean()),fmt(cboot(b,'r')))
b1=b.drop_duplicates('slug'); print(' first-per-window',len(b1),'wr %.3f px %.3f'%(b1.win.mean(),b1.px.mean()),fmt(cboot(b1,'r')))
print(' offset (s) median of in-band probe fills: %.0f'%b.offset_s.median())
# twin: farm fair-05 first entry same window
F5=t[t.account=='fair-05'].sort_values('tsec').drop_duplicates('slug').set_index('slug')
FA=t[t.family=='FAIR']
pf=f.drop_duplicates('slug').set_index('slug')
rows=[]
for sl,r in pf.iterrows():
    q=F5.loc[sl] if sl in F5.index else None
    # any FAIR decision same side in band within +-60s of probe fill
    near=FA[(FA.slug==sl)&(FA.side==r.side)&((FA.tsec-r.tsec).abs()<=60)]
    rows.append(dict(slug=sl,seg=r.seg,p_side=r.side,p_px=r.px,p_off=r.offset_s,win=r.win,
        f_side=None if q is None else q.side,f_px=np.nan if q is None else q.price,f_off=np.nan if q is None else q.off,
        f_win=np.nan if q is None else q.win, near_px=near.price.mean() if len(near) else np.nan))
T=pd.DataFrame(rows)
T['same']=T.p_side==T.f_side
print('\nTwin probe-first-fill vs farm fair-05 first entry, windows',len(T),'with farm entry',T.f_side.notna().sum())
print('same side',T.same.sum(),'/',T.f_side.notna().sum())
print('probe offset median %.0fs vs farm %.0fs'%(T.p_off.median(),T.f_off.median()))
m=T[T.same]; print('same side: probe px - farm px mean %+.3f (median %+.3f); n=%d'%((m.p_px-m.f_px).mean(),(m.p_px-m.f_px).median(),len(m)))
nn=T.dropna(subset=['near_px']); print('farm FAIR asks within 60s same side vs probe fill px: diff %+.4f n=%d'%((nn.p_px-nn.near_px).mean(),len(nn)))
print('probe wr %.3f farm wr same windows %.3f'%(T.win.mean(),T.f_win.mean()))
print('opposite side windows:',(~T.same & T.f_side.notna()).sum())
print(T.round(3).to_string())
# probe in-band windows: what did farm fair-05 do?
ib=T[(T.p_px>=.6)&(T.p_px<=.75)]
print('\nprobe in-band windows',len(ib),'probe wr %.3f px %.3f | farm fair-05 same windows wr %.3f px %.3f same-side %d'%(ib.win.mean(),ib.p_px.mean(),ib.f_win.mean(),ib.f_px.mean(),ib.same.sum()))
# Calibration of probe entries vs time: expected wr given px; binomial p-value for in-band
from scipy.stats import binom
k=int(b1.win.sum()); n=len(b1); p=b1.px.mean()
print('in-band first fills: k=%d n=%d px=%.3f  P(X<=k | p=px)=%.3f'%(k,n,p,binom.cdf(k,n,p)))
# Poisson-binomial exact via sim
rng=np.random.default_rng(1); sims=(rng.random((200000,n))<b1.px.values).sum(1); print(' poisson-binomial P(X<=k)=%.3f'%(sims<=k).mean())
T.to_csv('twin.csv',index=False)
