from common import *
t,s,W=load_1h()
print('windows with winner',len(W),'fam counts',t.groupby('family').slug.nunique().to_dict())
print('time range',pd.to_datetime(t.tsec.min(),unit='s'),pd.to_datetime(t.tsec.max(),unit='s'))
# decisions: dedupe identical decisions across accounts within family (same slug,side,price,ts rounded)
t['tsr']=t.tsec.round(0)
d=t.drop_duplicates(['family','slug','side','price','tsr']).copy()
d['r']=ret(d.win,d.price,d.tsec); d['r_new']=ret(d.win,d.price,d.tsec,r=0.01)
d['fee_era']=np.where(d.tsec<FEECUT,'pre','post')
print('distinct decisions',d.groupby('family').size().to_dict())
bands=[(0,.4),(.4,.5),(.5,.6),(.6,.75),(.75,.85),(.85,1.01)]
for fam in ['FAIR','LATE','BAND']:
    x=d[d.family==fam]
    print(f'\n== {fam}  all:',fmt(cboot(x,'r')))
    for lo,hi in bands:
        y=x[(x.price>=lo)&(x.price<hi)]
        if len(y): print(f'  ask[{lo},{hi}) ',fmt(cboot(y,'r')),' wr=%.3f px=%.3f'%(y.win.mean(),y.price.mean()))
    for e in ['pre','post']:
        y=x[x.fee_era==e]
        if len(y): print('  era',e,fmt(cboot(y,'r')))
# sweet band FAIR: first entry per window only (one decision per window, like probe)
x=d[(d.family=='FAIR')]
for lo,hi in [(.5,.75),(.6,.75),(.55,.75)]:
    y=x[(x.price>=lo)&(x.price<=hi)]
    f=y.sort_values('tsec').drop_duplicates('slug')
    print(f'\nFAIR band {lo}-{hi}: all decisions',fmt(cboot(y,'r')),'| first per window',fmt(cboot(f,'r')),
          ' wr=%.3f px=%.3f'%(f.win.mean(),f.price.mean()))
    # by time-of-day era
    for e in ['pre','post']:
        z=f[f.fee_era==e]
        if len(z): print('   ',e,fmt(cboot(z,'r')),'wr=%.3f px=%.3f'%(z.win.mean(),z.price.mean()))
    # entry offset distribution
    print('   entry offset min: median %.1f q25 %.1f q75 %.1f'%tuple(np.percentile(f.off/60,[50,25,75])))
# by account fair-05 actual settlement pnl per window
s['start']=start(s.slug)
st=s[s.account.str.startswith(('fair','late','band'))].copy(); st['fam']=st.account.str.split('-').str[0]
print('\nfamily-sum pnl per window (accounts summed):')
for f,g in st.groupby('fam'):
    pw=g.groupby('slug').pnl.sum(); print(f,len(pw),'%.2f mean %.3f'%(pw.sum(),pw.mean()))
d.to_pickle('/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/dec1h.pkl')
