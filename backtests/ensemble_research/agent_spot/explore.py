exec(open('/home/user/PQ/backtests/ensemble_research/load.py').read())
print(t.shape, t.family.value_counts().to_dict())
t['tau']=300-t.off
print(t.groupby('family').tau.describe())
print('windows',t.slug.nunique(),'with winner',t.winner.notna().groupby(t.slug).first().sum())
# settlements per slug
ss=s.dropna(subset=['winner']).drop_duplicates('slug')[['slug','winner','open','close','start']]
ss['sp']=np.where(ss.close>=ss.open,'Up','Down')
print('disagree',(ss.sp!=ss.winner).mean(), len(ss))
ss['d']=ss.close-ss.open
print(ss.assign(dis=ss.sp!=ss.winner).groupby(pd.cut(ss.d.abs(),[0,2,5,10,20,50,1e4])).dis.agg(['mean','size']))
print(t.fill_delay_s.describe())
print(t[t.family=='OPENFADE'][['move_open','basis','off','side','price']].describe())
print(t[t.family=='FAIR'][['fair','gap','basis','off','price']].describe())
print(t[t.family=='MVAL'][['fair','gap','basis','off','price','mv_entry']].describe())
# basis constant within window?
print(t.dropna(subset=['basis']).groupby('slug').basis.nunique().value_counts().head())
