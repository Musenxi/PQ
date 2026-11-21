#!/usr/bin/env python3
"""Round 2 of docs/ensemble-research-2026-11-22.md: side/regime/vol splits, execution
quality, live-probe slippage and band, 1h exit families, 5m late tail, in-band path filter."""
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
exec(open('load.py').read())
x['tsr'] = x.tsec.round(0)
u = x.drop_duplicates(['slug', 'side', 'price', 'tsr']).sort_values('tsec').copy()
u['pb'] = pd.cut(u.price, [0, .3, .5, .6, .75, .9, 1])
def bw(d):
    a = d.groupby('slug').ret.mean().values; rng = np.random.default_rng(1)
    b = [rng.choice(a, len(a)).mean() for _ in range(1000)]
    return '%5d/%3d %+.3f [%+.3f,%+.3f]' % (len(d), len(a), a.mean(), *np.percentile(b, [2.5, 97.5]))

print('== side x band / by day')
print(u.pivot_table(index='pb', columns='side', values='ret', aggfunc='mean', observed=True).round(3))
u['day'] = pd.to_datetime(u.start, unit='s').dt.date
print(u.pivot_table(index='day', columns='side', values='ret', aggfunc='mean').round(3))

print('== trend alignment and vol regime')
w = s.dropna(subset=['open', 'close']).drop_duplicates('slug').set_index('start'); op, cl = w.open, w.close
def trail(st, n):
    a = [st - 300 * k for k in range(1, n + 1) if st - 300 * k in cl.index]
    return np.nan if len(a) < .75 * n else cl[max(a)] - op[min(a)]
def vol(st, n):
    a = [st - 300 * k for k in range(1, n + 1) if st - 300 * k in cl.index]
    return np.nan if len(a) < .75 * n else np.mean([abs(cl[i] - op[i]) for i in a])
S = pd.Series(u.start.unique())
for n in [3, 12, 48]:
    m = dict(zip(S, S.map(lambda q: trail(q, n)))); tr = u.start.map(m); d = u[tr.notna()]
    al = np.sign(tr[tr.notna()]) * np.where(d.side == 'Up', 1, -1)
    print('trend %2d with %s | against %s' % (n, bw(d[al > 0]), bw(d[al < 0])))
u['vol'] = u.start.map(dict(zip(S, S.map(lambda q: vol(q, 12))))); d = u.dropna(subset=['vol'])
q = d.vol.quantile([.33, .67]).values
for nm, m in [('low', d.vol < q[0]), ('mid', (d.vol >= q[0]) & (d.vol < q[1])), ('high', d.vol >= q[1])]:
    print(nm, 'band.55-.75', bw(d[m & (d.price > .55) & (d.price < .75)]), ' <.5', bw(d[m & (d.price < .5)]))

print('== execution quality')
print(u.groupby(u.levels.clip(1, 3)).ret.agg(['size', 'mean']).round(3))
v = u.dropna(subset=['book_age_ms'])
print(v.groupby(pd.cut(v.book_age_ms, [-1, 200, 1000, 2000, 1e9]), observed=True).ret.agg(['size', 'mean']).round(3))

print('== live probes: slippage and band')
for nm in ['live-probe-1h', 'live-probe-5m']:
    o = rd(nm + '/orders.jsonl.gz'); st = rd(nm + '/settlements.jsonl.gz')
    m = st.merge(o[o.error.isna()].drop_duplicates('slug', keep='last')[['slug', 'ask']], on='slug', how='left')
    m['px'] = m.filled_cost / m.filled_shares; m['win'] = m.side == m.winner
    print(nm, 'fills', len(m), 'slip mean %.4f' % (m.px - m.ask).mean())
    print(m.groupby(pd.cut(m.px, [0, .5, .6, .75, 1]), observed=True).agg(n=('win', 'size'), wr=('win', 'mean'), px=('px', 'mean'), pnl=('pnl', 'sum')).round(3))

print('== 1h exit families vs hold (fair-05, same windows)')
ts, ss, _ = prep(rd('farm-1h-swing/trades.jsonl.gz'), rd('farm-1h-swing/settlements.jsonl.gz'))
ss['family'] = ss.account.map(ts.drop_duplicates('account').set_index('account').family)
f5 = rd('farm-1h/settlements.jsonl.gz').query("account=='fair-05'").set_index('slug').pnl
g = ss.groupby(['family', 'slug']).pnl.mean().unstack(0); g['hold'] = g.index.map(f5); g = g.dropna(subset=['hold'])
print(g.drop(columns='hold').sub(g.hold, axis=0).agg(['mean', 'std', 'count']).round(3))

print('== 5m late tail')
for lo in [.8, .85, .9]:
    d = u[(u.off >= 180) & (u.price >= lo)]; print('px>=%.2f n=%d ret %+.4f' % (lo, len(d), d.ret.mean()))

print('== in-band path: price change since first observation in window')
u['upq'] = np.where(u.side == 'Up', u.price, 1 - u.price)
e = u.groupby('slug').agg(t0=('tsec', 'first'), q0=('upq', 'first'))
u['q0'] = u.slug.map(e.q0); u['t0'] = u.slug.map(e.t0); uu = u[u.tsec - u.t0 >= 15].copy()
uu['d'] = np.where(uu.side == 'Up', uu.upq - uu.q0, -(uu.upq - uu.q0))
b = uu[(uu.price > .55) & (uu.price < .75)]; med = b.start.median()
for nm, m in [('flat/fell <.05', b.d < .05), ('rose .05-.15', (b.d >= .05) & (b.d < .15)), ('rose >=.15', b.d >= .15)]:
    print(nm.ljust(15), bw(b[m]), ' H1', bw(b[m & (b.start <= med)]), ' H2', bw(b[m & (b.start > med)]))
