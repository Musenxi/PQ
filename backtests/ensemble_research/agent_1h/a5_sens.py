from common import *
d=pd.read_pickle('/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/dec1h.pkl')
d['r01']=ret(d.win,d.price,d.tsec,r=.01)
f=d[(d.family=='FAIR')&(d.price>=.5)&(d.price<=.75)].sort_values('tsec').drop_duplicates('slug').copy()
OUT=(f.start>=1795190400)&(f.start<1795236660)
print('FAIR 0.5-0.75 first/window, fee.01: all',fmt(cboot(f,'r01')))
print('  excl README outage windows',fmt(cboot(f[~OUT],'r01')),' | outage-only',fmt(cboot(f[OUT],'r01')))
f['day']=pd.to_datetime(f.start,unit='s').dt.strftime('%m-%d')
for k,g in f.groupby('day'): print('  day',k,fmt(cboot(g,'r01')),'wr %.2f px %.2f'%(g.win.mean(),g.price.mean()))
f['early']=f.off<300
for k,g in f.groupby('early'): print('  entry<5min' if k else '  entry>=5min',fmt(cboot(g,'r01')),'wr %.2f px %.2f'%(g.win.mean(),g.price.mean()))
# fraction of windows FAIR fires in band 0.6-0.75 (rate per day)
nW=d.slug.nunique(); print('windows',nW,'fair 0.6-0.75 windows',d[(d.family=='FAIR')&(d.price>=.6)&(d.price<=.75)].slug.nunique())
# split-half stability of band ranking: random halves of windows
rng=np.random.default_rng(0); sl=d.slug.unique(); agree=0
x=d[d.family=='FAIR']
for i in range(500):
    h=set(rng.choice(sl,len(sl)//2,replace=False)); A=x[x.slug.isin(h)]; B=x[~x.slug.isin(h)]
    ra=A[(A.price>=.5)&(A.price<=.75)].r01.mean()-A[(A.price<.5)].r01.mean(); rb=B[(B.price>=.5)&(B.price<=.75)].r01.mean()-B[(B.price<.5)].r01.mean()
    agree+= (ra>0)==(rb>0)
print('split-half sign agreement of (band - below0.5) contrast: %.2f'%(agree/500))
# Power analysis
from scipy.stats import norm
for p in [.6,.65,.7]:
    sd=np.sqrt(p*(1-p))/p
    for dlt in [.05,.10]:
        n2=((norm.ppf(.975)+norm.ppf(.8))*sd/dlt)**2; n1=((norm.ppf(.95)+norm.ppf(.8))*sd/dlt)**2
        print(f'power p={p} sd/$={sd:.3f} edge={dlt:+.2f}: n(2-sided .05)={n2:.0f}  n(1-sided .05)={n1:.0f}')
sd=np.sqrt(.65*.35)/.65
for n in [60,90,120]: print(f'MDE80 at n={n}: {2.80*sd/np.sqrt(n):.3f}/$')
# empirical sd of per-window $-return in farm band
print('empirical sd per-window r (FAIR first 0.5-.75): %.3f'%f.r01.std())
