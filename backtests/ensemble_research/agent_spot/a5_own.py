"""Item 5: own ideas -- pre-entry info from previous windows (Chainlink prints), side asymmetry."""
exec(open('common.py').read())
import statsmodels.api as sm
w=ss.copy()
prev=w.shift(1); ok=(pd.Series(w.index,index=w.index).diff()==300)
w['pd']=np.where(ok,prev.d,np.nan); w['pwin']=np.where(ok,prev.winner,None)
w['ogap']=np.where(ok,w.open-prev.close,np.nan)
w['upw']=(w.winner=='Up').astype(float)
print('open_i - close_{i-1}:',w.ogap.describe().round(2).to_dict())
for v in ['pd','ogap']:
    q=w.dropna(subset=[v]); 
    for h,qq in [(1,q[q.index<MED]),(2,q[q.index>=MED])]:
        r=sm.OLS(qq.upw,sm.add_constant(np.sign(qq[v]))).fit(cov_type='HC1')
        print(f'P(Up) ~ sign({v}) H{h}: {r.params.iloc[1]:+.3f} se {r.bse.iloc[1]:.3f} n{len(qq)}')
# tradable versions: first row per window whose side == rule side (all families leg1), price band 0.2-0.8
x=t[(t.price>=0.2)&(t.price<=0.8)].copy()
x=x.join(w[['pd','ogap','pwin']],on='start')
for v in ['pd','ogap']:
    for lab,sideexpr in [('follow',np.where(x[v]>0,'Up','Down')),('fade',np.where(x[v]>0,'Down','Up'))]:
        q=x[x[v].notna()&(x.side==sideexpr)]
        report(q.sort_values('tsec').drop_duplicates('slug'),f'{lab} sign({v})')
# side asymmetry by price band
x2=t.copy(); x2['pb']=pd.cut(x2.price,[0.1,0.3,0.5,0.55,0.75,0.9])
print()
for (pb,sd),q in x2.groupby(['pb','side'],observed=True):
    report(q.sort_values('tsec').drop_duplicates('slug'),f'band={pb} side={sd}')
