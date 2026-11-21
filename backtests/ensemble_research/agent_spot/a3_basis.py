"""Item 3: basis (Binance - Chainlink, 24-window running mean of pre-open samples)."""
exec(open('common.py').read())
import statsmodels.api as sm
bw=t.dropna(subset=['basis']).groupby('start').basis.first().sort_index()
B=pd.DataFrame({'basis':bw})
B['db']=B.basis.diff()   # ~ (new sample - dropped sample)/24
B['gap_s']=pd.Series(B.index,index=B.index).diff()
B.loc[B.gap_s>600,'db']=np.nan
B['bdev']=B.basis-B.basis.rolling(12,min_periods=6).mean()
print(B.describe().round(2))
x=t.dropna(subset=['basis']).copy()
x=x.join(B[['db','bdev']],on='start')
x['upwin']=(x.winner=='Up').astype(float)
x['sgn']=np.where(x.side=='Up',1,-1)
# per window first row, residual from Up perspective
x['pu']=np.where(x.side=='Up',x.price,1-x.price)
x['res_up']=x.upwin-x.pu
fr=x.sort_values('tsec').drop_duplicates('slug')
for v in ['basis','db','bdev']:
    q=fr.dropna(subset=[v])
    for h in (1,2):
        qq=q[q.half==h]; X=sm.add_constant((qq[v]-q[v].mean())/q[v].std())
        r=sm.OLS(qq.res_up.values,X).fit(cov_type='HC1')
        print(f'{v} H{h}: res_up ~ std({v}) coef {r.params.iloc[1]:+.4f} se {r.bse.iloc[1]:.4f} n{len(qq)}')
# side richness: edge of buying traded side, split by sign agreement of side with db, and basis tercile
x['bt']=pd.qcut(x.basis,3,labels=['loB','midB','hiB'])
print()
for (b,sd),q in x.groupby(['bt','side'],observed=True):
    report(q.sort_values('tsec').drop_duplicates('slug'),f'{b} side={sd}')
for (b,sd),q in x.dropna(subset=['db']).groupby([np.sign(x.db),'side'],observed=True):
    report(q.sort_values('tsec').drop_duplicates('slug'),f'sign(db)={b} side={sd}')
