exec(open('common.py').read())
import statsmodels.formula.api as smf, warnings; warnings.filterwarnings('ignore')
tp=pd.read_pickle(SP+'tape_feat.pkl'); tp['h']=np.where(tp.start<MED,1,2)
def bd(a,b,B=4000):
    a=np.asarray(a);b=np.asarray(b)
    m=a[rng.integers(0,len(a),(B,len(a)))].mean(1)-b[rng.integers(0,len(b),(B,len(b)))].mean(1); return np.percentile(m,[2.5,97.5])
print('robustness of chop>0 penalty, in-band one obs/window (first in-band row after T)')
for lo,hi in [(.55,.75),(.6,.75),(.5,.8)]:
  for T in [20,30,45,60,90]:
    o=tp[(tp.price>=lo)&(tp.price<hi)&(tp.off>=T)].drop_duplicates('slug')
    c=o[o.chop>0].ret; q=o[o.chop==0].ret
    print(f'[{lo},{hi}) T{T}: chop0 {q.mean():+.3f} n={len(q)} CI{np.round(boot(q),3)} | chop>0 {c.mean():+.3f} n={len(c)} | diff CI {np.round(bd(q,c),3)} | H1 {o[(o.h==1)&(o.chop==0)].ret.mean():+.3f} H2 {o[(o.h==2)&(o.chop==0)].ret.mean():+.3f}')
o=tp[(tp.price>=.55)&(tp.price<.75)&(tp.off>=30)].drop_duplicates('slug').copy()
o['chop1']=(o.chop>0).astype(int); o['bigrun']=(o.run_o>=.15).astype(int)
for f in ['ret ~ price + chop1','ret ~ price + chop1 + bigrun','ret ~ price + chop1 + rng','ret ~ price + chop1 + tsl + off']:
    r=smf.ols(f,o).fit(cov_type='HC1'); print(f, r.params.round(3).to_dict(), r.pvalues.round(3).to_dict())
print(pd.crosstab(o.chop1,o.bigrun,values=o.ret,aggfunc='mean').round(3)); print(pd.crosstab(o.chop1,o.bigrun))
print('winrate vs price by chop:'); print(o.groupby('chop1').agg(p=('price','mean'),w=('win','mean'),n=('win','size'),off=('off','mean')).round(3))
# all-price check: does chop matter outside band (full calibration)?
a=tp[(tp.off>=30)&(tp.price>=.3)&(tp.price<.9)].copy(); a['chop1']=(a.chop>0).astype(int)
a['pb']=pd.cut(a.price,[.3,.4,.5,.55,.75,.9])
a=a.groupby(['pb','slug']).first().reset_index().dropna(subset=['ret'])
print(a.groupby(['pb','chop1']).ret.agg(['mean','count']).unstack().round(3))
