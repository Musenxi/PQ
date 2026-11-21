exec(open('/home/user/PQ/backtests/ensemble_research/load.py').read())
tp=t[t.leg==1].dropna(subset=['win'])[['slug','start','tsec','off','side','price','winner']].copy()
tp=tp.drop_duplicates(['slug','tsec','side','price']).sort_values(['slug','tsec'])
tp=tp[(tp.off>=0)&(tp.off<300)]
tp.to_pickle('/tmp/claude-0/-home-user-PQ/d5070770-f3cb-5e62-af7b-136bed3d3eee/scratchpad/tape.pkl')
print(len(tp), tp.slug.nunique()); print(tp.groupby('slug').size().describe())
print(pd.to_datetime(tp.start.min(),unit='s'),pd.to_datetime(tp.start.max(),unit='s'))
print(tp.off.describe()); print(tp.price.describe())
print(np.histogram(tp.off,bins=range(0,301,30)))
