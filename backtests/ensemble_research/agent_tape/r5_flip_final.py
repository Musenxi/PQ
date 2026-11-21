exec(open('common.py').read())
tp=pd.read_pickle(SP+'tape_feat.pkl'); tp['h']=np.where(tp.start<MED,1,2)
# hysteresis chop: crossing counted only when q moves from <=0.5-db to >=0.5+db or reverse
def hyst(g,db):
    q=g.q.values; st=0; c=0; out=[]
    for v in q:
        s=1 if v>=.5+db else (-1 if v<=.5-db else 0)
        if s!=0:
            if st!=0 and s!=st: c+=1
            st=s
        out.append(c)
    return pd.Series(out,index=g.index)
for db in [0.0,0.03,0.05]:
    tp['ch']=tp.groupby('slug',group_keys=False).apply(lambda g:hyst(g,db))
    def bd(a,b,B=4000):
        a=np.asarray(a);b=np.asarray(b)
        m=a[rng.integers(0,len(a),(B,len(a)))].mean(1)-b[rng.integers(0,len(b),(B,len(b)))].mean(1); return np.percentile(m,[2.5,97.5])
    out=[]
    for nm,lo,hi in [('FAV',.55,.75),('DOG',.3,.45)]:
        o=tp[(tp.price>=lo)&(tp.price<hi)&(tp.off>=30)].drop_duplicates('slug')
        a=o[o.ch>0]; b=o[o.ch==0]
        line=f'db={db} {nm}: chop>0 {a.ret.mean():+.3f}(n{len(a)}) chop0 {b.ret.mean():+.3f}(n{len(b)}) diffCI {np.round(bd(a.ret,b.ret),3)}'
        for h in [1,2]: line+=f' | H{h} diff {a[a.h==h].ret.mean()-b[b.h==h].ret.mean():+.3f}'
        print(line)
    # Rule B tradable: post-flip underdog
    B_=tp[(tp.price>=.3)&(tp.price<.45)&(tp.off>=30)&(tp.ch>0)].drop_duplicates('slug')
    A_=tp[(tp.price>=.55)&(tp.price<.75)&(tp.off>=30)&(tp.ch==0)].drop_duplicates('slug')
    print('  ruleB',{k:round(v,3) if isinstance(v,float) else v for k,v in summ(B_,'B').items()})
    print('  ruleA',{k:round(v,3) if isinstance(v,float) else v for k,v in summ(A_,'A').items()})
# per-day stability of rule B (db=0.03)
tp['ch']=tp.groupby('slug',group_keys=False).apply(lambda g:hyst(g,0.03))
B_=tp[(tp.price>=.3)&(tp.price<.45)&(tp.off>=30)&(tp.ch>0)].drop_duplicates('slug').copy()
B_['day']=pd.to_datetime(B_.start,unit='s').dt.date
print(B_.groupby('day').ret.agg(['mean','count']).round(3))
print('B price %.3f win %.3f off %.1f'%(B_.price.mean(),B_.win.mean(),B_.off.mean()))
# power: per-window sd of ret
sd=B_.ret.std(); print('B sd',sd.round(3))
for eff in [0.05,0.08,0.10]: print('n for 80% power one-sided a=.05 eff',eff, int(((1.645+0.842)*sd/eff)**2))
o=tp[(tp.price>=.55)&(tp.price<.75)&(tp.off>=30)].drop_duplicates('slug')
print('fav chop-diff sd approx',o.ret.std().round(3))
