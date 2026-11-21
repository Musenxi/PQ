"""Build per-decision-tick table reconstructing spot state from stamped fields."""
exec(open('/home/user/PQ/backtests/ensemble_research/load.py').read())
from scipy.stats import norm
t=t[t.leg==1].copy()
t['dec']=t.tsec-t.fill_delay_s
t['tick']=t.dec.round(0)
t['tau']=300-(t.dec-t.start)
ss=s.dropna(subset=['winner']).drop_duplicates('slug').set_index('slug')
t['open']=t.slug.map(ss.open); t['close']=t.slug.map(ss.close)
t['fair_up']=np.where(t.side=='Up',t.fair,1-t.fair)
t['dask']=t.fair-t.gap   # decision-time ask of traded side
t['feeps']=fee_ps(t.tsec.values,t.price.values)
t.to_pickle('/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/rows.pkl')
# tick-level check of consistency
g=t.dropna(subset=['fair_up']).groupby(['slug','tick']).fair_up.agg(['min','max','size'])
print('fair_up spread within tick', (g['max']-g['min']).describe())
both=t.groupby(['slug','tick']).agg(mo=('move_open','first'),fu=('fair_up','first'),tau=('tau','first'),op=('open','first'))
b=both.dropna()
print('ticks with move_open & fair', len(b), b.index.get_level_values(0).nunique())
b=b[(b.fu>0.02)&(b.fu<0.98)&(b.tau>60)]
b['z']=norm.ppf(b.fu)
b['sig']=np.log(1+b.mo/b.op)/(b.z*np.sqrt(b.tau-40))
b=b[np.abs(b.z)>0.15]
print(b.sig.describe()); print((b.sig*np.sqrt(300)*b.op).describe())
