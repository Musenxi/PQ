exec(open('common.py').read())
import statsmodels.formula.api as smf, warnings; warnings.filterwarnings('ignore')
tp=tp.sort_values(['slug','tsec']).reset_index(drop=True)
tp['q']=np.where(tp.side=='Up',tp.price,1-tp.price)   # Up-implied
feats=[]
for slug,g in tp.groupby('slug',sort=False):
    ts=g.tsec.values; q=g.q.values; off=g.off.values
    n=len(g); out=np.full((n,8),np.nan)
    for i in range(n):
        past=q[:i+1]; pt=ts[:i+1]
        def back(dt):
            j=np.searchsorted(pt,ts[i]-dt); return q[i]-past[j] if ts[i]-pt[j]<=dt+5 and j<i else np.nan
        v15=back(15); v30=back(30)
        # accel: v15 now minus v15 15s ago
        sgn=np.sign(past-0.5); sgn=sgn[sgn!=0]
        chop=(np.diff(sgn)!=0).sum() if len(sgn)>1 else 0
        flips=np.where(np.diff(np.sign(past-0.5))!=0)[0]
        tsl=ts[i]-pt[flips[-1]+1] if len(flips) else off[i]
        maxexc=np.abs(past-0.5).max(); run=q[i]-past[0]
        rng_=past.max()-past.min()
        out[i]=[v15,v30,chop,tsl,maxexc,run,rng_,i]
    feats.append(pd.DataFrame(out,index=g.index,columns=['v15','v30','chop','tsl','maxexc','run','rng','nobs']))
F=pd.concat(feats); tp=tp.join(F)
s=np.where(tp.side=='Up',1,-1)   # orient to own side
for c in ['v15','v30','run']: tp[c+'_o']=tp[c]*s
tp['exc_now']=np.abs(tp.q-0.5); tp['retrace']=tp.maxexc-tp.exc_now   # how far below max excursion
tp.to_pickle(SP+'tape_feat.pkl')
d=tp[(tp.price>=.3)&(tp.price<.9)&(tp.off>=20)].copy()
d['pb']=pd.cut(d.price,np.arange(.3,.91,.05))
d['h']=np.where(d.start<MED,1,2)
FE=['v15_o','v30_o','run_o','chop','tsl','maxexc','retrace','rng','nobs']
print('rows',len(d))
for f in FE:
    res=[]
    for h in [1,2]:
        dd=d[(d.h==h)].dropna(subset=[f]); z=(dd[f]-d[f].mean())/d[f].std(); dd=dd.assign(z=z)
        r=smf.ols('ret ~ C(pb) + z',dd).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(dd.slug)[0]})
        res.append(f'h{h}: b={r.params.z:+.3f} t={r.tvalues.z:+.2f} n={len(dd)}')
    print(f.ljust(8),' | '.join(res))
# in-band only (0.55-0.75), one obs/window (first in-band row with off>=30), median split by H1 median
print('--- in-band 0.55-0.75 one obs/window, split at H1 median')
o=d[(d.price>=.55)&(d.price<.75)&(d.off>=30)].drop_duplicates('slug')
for f in FE:
    oo=o.dropna(subset=[f]); med=oo[oo.h==1][f].median()
    hi=oo[oo[f]>med]; lo=oo[oo[f]<=med]
    line=[]
    for h in [1,2]:
        a=hi[hi.h==h].ret; b=lo[lo.h==h].ret
        line.append(f'h{h}: hi {a.mean():+.3f}({len(a)}) lo {b.mean():+.3f}({len(b)}) diff {a.mean()-b.mean():+.3f}')
    print(f.ljust(8),f'med={med:.3f}',' | '.join(line))
