"""Item 1b: does PM price vol properly? regime split by imputed sigma (farm's trailing 15m sigma)."""
exec(open('common.py').read())
import statsmodels.api as sm
f=pd.read_pickle(SP+'f.pkl'); f['sig']=f.start.map(ss.sig_imp); f['tvol']=f.start.map(ss.tvol)
f=f.dropna(subset=['sig']); f=f[(f.dask>0.03)&(f.dask<0.97)]
f['ls']=np.log(f.sig/f.sig.median())
f['zm']=norm.ppf(f.dask)
cl=lambda q: {'groups':pd.factorize(q.slug)[0]}
# market pricing: zm ~ z_side + z_side*ls
X=sm.add_constant(np.column_stack([f.z_side,f.z_side*f.ls,f.ls]))
r=sm.OLS(f.zm.values,X).fit(cov_type='cluster',cov_kwds=cl(f))
print('mkt zm ~ z + z*logsig + logsig:',r.params.round(3),r.bse.round(3))
# truth: win ~ z + z*logsig  (probit)
for h in (0,1,2):
    q=f if h==0 else f[f.half==h]
    X=sm.add_constant(np.column_stack([q.z_side,q.z_side*q.ls,q.ls]))
    r=sm.Probit(q.win.values,X).fit(disp=0,cov_type='cluster',cov_kwds=cl(q))
    print(f'H{h} truth win ~ z + z*ls + ls:',r.params.round(3),r.bse.round(3))
    X=sm.add_constant(np.column_stack([q.zm,q.zm*q.ls,q.ls]))
    r=sm.Probit(q.win.values,X).fit(disp=0,cov_type='cluster',cov_kwds=cl(q))
    print(f'H{h} mkt-resid win ~ zm + zm*ls + ls:',r.params.round(3),r.bse.round(3))
# edge for favourite (z>0, ask>0.5) vs dog by vol tercile, first tick per window
f['vt']=pd.qcut(f.ls,3,labels=['lowV','midV','hiV'])
print('\n edge buying traded side by vol tercile x (traded side is market favourite ask>=0.5)')
for (v,fav),q in f.groupby(['vt',f.dask>=0.5],observed=True):
    report(q.sort_values('tsec').drop_duplicates('slug'),f'{v} mktfav={fav}')
