"""Item 5b: refine known price-band structure by spot state (fav sign) and sigma regime."""
exec(open('common.py').read())
f=t.dropna(subset=['fair']).copy()
f['pb']=pd.cut(f.price,[0.3,0.5,0.55,0.75],labels=['cheap.3-.5','mid','rich.55-.75'])
f=f[f.pb!='mid']
f['fav']=np.where(f.z_side>0,'spotfav','spotdis')
f['vt']=pd.qcut(np.log(f.sig),3,labels=['lowV','midV','hiV'])
for keys in [['pb','fav'],['pb','vt']]:
    for k,q in f.dropna(subset=keys).groupby(keys,observed=True):
        report(q.sort_values('tsec').drop_duplicates('slug'),str(k))
