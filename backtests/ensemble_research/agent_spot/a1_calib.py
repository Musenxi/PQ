"""Item 1: recalibrated spot model vs market-implied (ask)."""
exec(open('common.py').read())
from scipy.optimize import minimize
# distinct ticks per (slug,tick,side) with fair info
f=t.dropna(subset=['fair']).sort_values('tsec').drop_duplicates(['slug','tick','side']).copy()
f=f[f.tau>=20]
print('ticks',len(f),'windows',f.slug.nunique())
def nll(p,df):
    q=norm.cdf(p[0]*df.z_side+p[1]*np.sqrt(np.maximum(df.te,1))*0).clip(1e-6,1-1e-6)
    return -np.mean(df.win*np.log(q)+(1-df.win)*np.log(1-q))
tr=f[f.half==1]
a=minimize(lambda p: nll([p[0],0],tr),[0.7]).x[0]
print('fitted a (z multiplier) H1:',round(a,3),' (1/1.35=0.741)', ' H2 fit:',round(minimize(lambda p: nll([p[0],0],f[f.half==2]),[0.7]).x[0],3))
f['pcal']=norm.cdf(a*f.z_side)
f['pm']=f.dask  # market implied ask at decision
f['dev']=f.pcal-f.pm
# market vs model in logistic: win ~ logit(pm) + logit(pcal)
import statsmodels.api as sm
L=lambda p: np.log(p.clip(.01,.99)/(1-p.clip(.01,.99)))
for h in (1,2):
    q=f[f.half==h]
    X=sm.add_constant(np.column_stack([L(q.pm),L(q.pcal)]))
    r=sm.Logit(q.win.values,X).fit(disp=0,cov_type='cluster',cov_kwds={'groups':pd.factorize(q.slug)[0]})
    print(f'H{h} logit win~ logit(ask)+logit(pcal): coef',r.params.round(3),'se',r.bse.round(3))
# test half: edge by region; one obs per window per region (first tick)
print('\n-- test half H2, buy traded side, first tick per window per cell; ret per $ at fill price --')
f['tb']=pd.cut(f.tau,[20,60,120,180,240,285],right=False)
f['zb']=pd.cut(f.z_side.abs()*a,[0,0.25,0.6,1.2,10])
f['devb']=pd.cut(f.dev,[-1,0,0.05,0.1,1])
for col in ['tb','zb','devb']:
    for k,q in f.groupby(col,observed=True):
        q1=q.sort_values('tsec').drop_duplicates('slug')
        report(q1,f'{col}={k}')
# interaction: favoured side (z>0) vs underdog, by zb x tb, pooled over halves
print('\n-- traded side spot-favoured (z>0) vs not; by tau --')
for fav,q0 in f.groupby(f.z_side>0):
    for k,q in q0.groupby('tb',observed=True):
        report(q.sort_values('tsec').drop_duplicates('slug'),f'fav={fav} tau={k}')
f.to_pickle(SP+'f.pkl')
