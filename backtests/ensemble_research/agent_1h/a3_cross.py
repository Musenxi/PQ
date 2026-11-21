"""Cross-market 1h vs 5m consistency. Mid approx: ask-0.005 (bid+0.005 for swing exit bids).
5m-implied 1h P(Up): D_k (5m-farm open of current 5m window - open of hour's first 5m window, same source)
 + market-implied in-window displacement m = sig*sqrt(r5)*Phi^-1(q5); P = Phi((D+m)/(sig*sqrt(tau)))."""
from obs import *
from scipy.stats import norm
import statsmodels.api as sm
SIG=8.8; H=0.005
a=obs1h(); b=obs5m(); W5=winners5(); _,_,W1=load_1h()
pw=rd('live-probe-1h/settlements.jsonl.gz').groupby('slug').winner.first(); W1=pd.concat([W1,pw[~pw.index.isin(W1.index)]])
s5=pd.concat([rd(f'{d}/settlements.jsonl.gz') for d in ['farm-5m-old','farm-5m-band-farm2']]).dropna(subset=['open']).groupby('slug').open.first()
O5=pd.Series(s5.values,index=start(pd.Series(s5.index)).values); O5=O5[~O5.index.duplicated()]
def pup(side,price,isbid):
    mid=np.where(isbid,price+H,price-H); return np.where(side=='Up',mid,1-mid)
a['isbid']=a.src=='swingbid'; a['P1']=pup(a.side,a.price,a.isbid)
b['P5']=pup(b.side,b.price,False)
b=b.sort_values('tsec'); a=a.sort_values('tsec')
# 5m obs belonging to the hour; each 1h obs matched to nearest 5m obs within TOL s from a 5m window inside the same hour
TOL=5
b['hour']=(b.start//3600)*3600
a['hour']=a.start
m=pd.merge_asof(a,b[['tsec','hour','start','side','price','P5']].rename(columns={'start':'st5','side':'side5','price':'p5','tsec':'t5'}).assign(tsec=lambda d:d.t5),
                on='tsec',by='hour',direction='nearest',tolerance=TOL).dropna(subset=['st5'])
m['st5']=m.st5.astype(int)
m['D']=m.st5.map(O5)-m.hour.map(O5)
m=m.dropna(subset=['D'])
m['r5']=(m.st5+300-m.tsec).clip(1,300); m['tau']=(m.hour+3600-m.tsec).clip(1,3600)
m['mdisp']=SIG*np.sqrt(m.r5)*norm.ppf(m.P5.clip(.01,.99))
m['P1imp']=norm.cdf((m.D+m.mdisp)/(SIG*np.sqrt(m.tau)))
m['w1']=m.slug.map(W1); m=m.dropna(subset=['w1']); m['y1']=(m.w1=='Up').astype(int)
m['s5slug']='btc-updown-5m-'+m.st5.astype(str); m['y5']=(m.s5slug.map(W5)=='Up').astype(float)
m['min']=(m.off//60)
print('matched pairs',len(m),'windows',m.slug.nunique())
m['diff']=m.P1-m.P1imp
print('diff 1h-mid minus 5m-implied: mean %+.3f sd %.3f; |diff|>0.10: %.1f%%  >0.15: %.1f%%'%(m['diff'].mean(),m['diff'].std(),100*(m['diff'].abs()>.1).mean(),100*(m['diff'].abs()>.15).mean()))
lg=lambda p: np.log(np.clip(p,.01,.99)/(1-np.clip(p,.01,.99)))
def logit_test(y,X,cl,names):
    X=sm.add_constant(np.column_stack(X)); r=sm.Logit(y,X).fit(disp=0,cov_type='cluster',cov_kwds={'groups':pd.factorize(cl)[0]})
    return ' '.join(f'{n}={c:+.2f}(z={z:+.1f})' for n,c,z in zip(['c']+names,r.params,r.tvalues))
print('1h outcome ~ logit P1 + logit P1imp (cluster=1h window):',logit_test(m.y1,[lg(m.P1),lg(m.P1imp)],m.slug,['P1','P5imp']))
print('Brier 1h-mid %.4f  5m-implied %.4f  (n=%d)'%(((m.P1-m.y1)**2).mean(),((m.P1imp-m.y1)**2).mean(),len(m)))
# Relative-value trade using only OBSERVED 1h asks: buy observed 1h side if model prob of that side exceeds ask+fee+thr
m['Pside_imp']=np.where(m.side=='Up',m.P1imp,1-m.P1imp)
m['win']=(m.side==m.w1).astype(float)
ask=m[~m.isbid]
for thr in [0.0,0.05,0.10]:
    x=ask[ask.Pside_imp-ask.price>thr].copy()
    for lab,rr in [('fee.07',None),('fee.01',0.01)]:
        x['r']=ret(x.win,x.price,x.tsec,r=rr)
        f=x.sort_values('tsec').drop_duplicates('slug')
        print(f' RV buy 1h side when 5m-implied > ask+{thr:.2f} [{lab}]: all',fmt(cboot(x,'r')),'| first/window',fmt(cboot(f,'r')))
# reverse: 1h side overpriced vs 5m-implied -> buy OTHER 1h side at assumed ask 1-mid+H (complement, spread 0.01)
for thr in [0.05,0.10]:
    x=m[m.P1imp<m.P1-thr].copy()  # 1h Up rich -> buy 1h Down
    y=m[m.P1imp>m.P1+thr].copy()  # 1h Up cheap -> buy 1h Up
    x['px']=1-m.loc[x.index,'P1']+H; x['win']=(x.w1=='Down').astype(float)
    y['px']=m.loc[y.index,'P1']+H; y['win']=(y.w1=='Up').astype(float)
    z=pd.concat([x,y]); z['r']=ret(z.win,z.px,z.tsec,r=0.01); f=z.sort_values('tsec').drop_duplicates('slug')
    print(f' RV (assumed complement asks, fee .01) |gap|>{thr}: all',fmt(cboot(z,'r')),'| first/window',fmt(cboot(f,'r')))
# Does 1h price predict 5m outcome beyond 5m price? 1h-implied 5m prob: displacement implied by 1h minus D
m['m1']=SIG*np.sqrt(m.tau)*norm.ppf(m.P1.clip(.01,.99))-m.D
m['P5from1']=norm.cdf(m.m1/(SIG*np.sqrt(m.r5)))
mm=m.dropna(subset=['y5']); mm=mm[mm.y5.notna()]
print('\n5m outcome ~ logit P5 + logit P5from1h (cluster=1h window) n=%d:'%len(mm),logit_test(mm.y5,[lg(mm.P5),lg(mm.P5from1)],mm.slug,['P5','P5from1h']))
print('Brier 5m price %.4f  1h-implied %.4f'%(((mm.P5-mm.y5)**2).mean(),((mm.P5from1-mm.y5)**2).mean()))
# Hour-level: do 5m outcomes within an hour (first k windows) beyond D add? skip.
# ---- exact box in last 5m window (minutes 55-60)
L=m[(m.st5==m.hour+3300)].copy()
print('\nLast-5m-window matched pairs (|dt|<=%ds):'%TOL,len(L),'windows',L.slug.nunique())
# box: D>=0 -> 1h Up + 5m Down ; D<0 -> 1h Down + 5m Up. cost using observed ask where side matches, else complement approx
def askof(P_up_mid,side): return np.where(side=='Up',P_up_mid+H,1-P_up_mid+H)
L['leg1']=np.where(L.D>=0,'Up','Down'); L['leg5']=np.where(L.D>=0,'Down','Up')
L['c1']=np.where(L.side==L.leg1,L.price,askof(L.P1,L.leg1)); L['c5']=np.where(L.side5==L.leg5,L.p5,askof(L.P5,L.leg5))
L['cost']=L.c1+L.c5
L['obs_both']=(L.side==L.leg1)&(L.side5==L.leg5)
print(L[['slug','min','D','side','price','side5','p5','c1','c5','cost','obs_both','y1','y5']].round(3).to_string())
print('box cost<1 cases:',(L.cost<1).sum(),'of',len(L),'| cost<0.98:',(L.cost<.98).sum())
m.to_pickle('/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/cross.pkl')
