import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
exec(open('load.py').read())
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
fams=sorted(first.family.unique())
x['tsr']=x.tsec.round(0)
u=x.drop_duplicates(['family','slug','side','price','tsr']).sort_values('tsec').copy()
# state of each family's first decision relative to this trade's side & time
fd=first[['slug','family','side','tsec','price']]
feat=u[['slug','family','side','price','off','tsec','start','win','ret','feeps']].copy()
for f in fams:
    b=fd[fd.family==f].set_index('slug')
    bs=feat.slug.map(b.side); bt=feat.slug.map(b.tsec)
    known=bt.notna()&(bt<feat.tsec)
    feat['st_'+f]=np.where(~known,0,np.where(bs==feat.side,1,-1))
    feat['px_'+f]=np.where(known, np.where(bs==feat.side, feat.slug.map(b.price), 1-feat.slug.map(b.price)), np.nan)
# previous window's winner aligned with side
ws=W.copy(); st=pd.Series(W.index.str.split('-').str[-1].astype(int),index=W.index)
prev=pd.Series(W.values,index=st.values)
feat['prev_same']=np.where(feat.start.map(lambda s: prev.get(s-300,None)).isna(),0, np.where(feat.start.map(lambda s: prev.get(s-300,None))==feat.side,1,-1))
for f in fams: feat['is_'+f]=(feat.family==f).astype(int)
feat['lp']=np.log(feat.price/(1-feat.price))
feat['hour']=pd.to_datetime(feat.start,unit='s').dt.hour
X=[c for c in feat.columns if c.startswith(('st_','px_','is_'))]+['lp','off','prev_same','hour']
days=np.sort(feat.start.unique()); cuts=list(np.quantile(feat.start,[.4,.55,.7,.85]))+[feat.start.max()+1]
res=[]
for i in range(len(cuts)-1):
    tr=feat[feat.start<cuts[i]]; te=feat[(feat.start>=cuts[i])&(feat.start<cuts[i+1])]
    for name,mdl in [('gbm',HistGradientBoostingClassifier(max_depth=3,learning_rate=.05,max_iter=150,min_samples_leaf=80,l2_regularization=1.0)),
                     ('logit',None)]:
        if name=='logit':
            Xl=[c for c in X if not c.startswith('px_')]
            mdl=LogisticRegression(C=.1,max_iter=2000).fit(tr[Xl],tr.win); ph=mdl.predict_proba(te[Xl])[:,1]
        else:
            mdl.fit(tr[X],tr.win); ph=mdl.predict_proba(te[X])[:,1]
        e=ph-te.price-te.feeps
        for th in [0,.02,.04]:
            sel=te[e>th]
            res.append((i,name,th,len(te),len(sel),sel.slug.nunique(),sel.ret.mean(), te.ret.mean()))
r=pd.DataFrame(res,columns=['fold','m','th','nte','nsel','nwin','ret_sel','ret_all'])
print(r.round(4).to_string())
print(r.assign(tot=r.ret_sel*r.nsel).groupby(['m','th']).apply(lambda d: pd.Series({'n':d.nsel.sum(),'ret':d.tot.sum()/max(d.nsel.sum(),1)})).round(4))
