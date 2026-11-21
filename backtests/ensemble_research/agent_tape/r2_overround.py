exec(open('common.py').read())
u=tp[tp.side=='Up'][['slug','start','tsec','off','price','win','fee']].sort_values('tsec')
d=tp[tp.side=='Down'][['slug','tsec','price','win','fee']].sort_values('tsec')
m=pd.merge_asof(u,d,on='tsec',by='slug',tolerance=2.0,direction='nearest',suffixes=('_u','_d')).dropna(subset=['price_d'])
m['spread']=m.price_u+m.price_d-1
print('pairs',len(m),'windows',m.slug.nunique()); print(m.spread.describe()); print(m.spread.round(2).value_counts().sort_index().head(20))
# cheap / fav side returns
m['pc']=np.minimum(m.price_u,m.price_d); m['pf']=np.maximum(m.price_u,m.price_d)
cu=m.price_u<m.price_d
m['wc']=np.where(cu,m.win_u,m.win_d); m['wf']=1-m.wc
m['fc']=np.where(cu,m.fee_u,m.fee_d); m['ff']=np.where(cu,m.fee_d,m.fee_u)
m['rc']=(m.wc-m.pc-m.fc)/m.pc; m['rf']=(m.wf-m.pf-m.ff)/m.pf
m=m[m.price_u!=m.price_d]
# midpoint-implied: is cheap side priced above its winrate more than fav?  edge per share vs mid
m['mid_c']=(m.pc+(1-m.pf))/2
f1=m.drop_duplicates('slug')   # one per window (first pair)
f1['sb']=pd.cut(f1.spread,[-1,0.005,0.015,0.03,1])
print(f1.groupby('sb').agg(n=('rc','size'),spread=('spread','mean'),pc=('pc','mean'),wc=('wc','mean'),rc=('rc','mean'),rf=('rf','mean'),midc=('mid_c','mean')).round(3))
# any pair per window, take a random pair? use all pairs clustered
import statsmodels.formula.api as smf
m['logit_mid']=np.log(m.mid_c/(1-m.mid_c))
for nm,df in [('first pair',f1),('all pairs',m)]:
    r=smf.ols('rf ~ spread + pf',df).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(df.slug)[0]})
    print(nm,'rf~spread+pf', r.params.round(3).to_dict(), r.pvalues.round(3).to_dict())
    r=smf.ols('rc ~ spread + pc',df).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(df.slug)[0]})
    print(nm,'rc~spread+pc', r.params.round(3).to_dict(), r.pvalues.round(3).to_dict())
# per-share edge of fav minus cheap (who absorbs the overround?)
m['ef']=m.wf-m.pf; m['ec']=m.wc-m.pc
g=m.groupby('slug').agg(ef=('ef','mean'),ec=('ec','mean'),sp=('spread','mean'),start=('start','first'))
print('window-avg per-share edge fav %.3f cheap %.3f spread %.3f'%(g.ef.mean(),g.ec.mean(),g.sp.mean()))
g['diff']=g.ef-g.ec; print('fav-cheap diff CI',g['diff'].mean(),boot(g['diff']))
g['wide']=g.sp>g.sp.median()
print(g.groupby('wide')[['ef','ec','diff']].agg(['mean','count']).round(3))
for w in [False,True]: print(w,boot(g[g.wide==w]['diff']))
# spread change: within window, delta spread between consecutive pairs predicts?
m=m.sort_values(['slug','tsec']); m['dsp']=m.groupby('slug').spread.diff()
m['dpu']=m.groupby('slug').price_u.diff(); 
print('pairs with spread change',m.dsp.notna().sum())
mm=m.dropna(subset=['dsp'])
mm['ru']=(mm.win_u-mm.price_u-mm.fee_u)/mm.price_u
r=smf.ols('ru ~ dsp + price_u',mm).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(mm.slug)[0]}); print('ru~dsp',r.params.round(3).to_dict(),r.pvalues.round(3).to_dict())
