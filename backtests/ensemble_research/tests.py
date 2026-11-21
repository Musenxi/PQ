#!/usr/bin/env python3
"""Ensemble / cross-account research on the 2026-11-22 data snapshot.
Run from this directory:  python3 tests.py   (needs pandas, numpy, scikit-learn, statsmodels)
Each block prints one table quoted in docs/ensemble-research-2026-11-22.md.
Unit: ret = (win - ask - fee/share) / ask, i.e. net return per $ staked, hold to official settlement.
De-dup: identical (slug, side, price, second) decisions across correlated accounts count once."""
import os; os.chdir(os.path.dirname(os.path.abspath(__file__)))
exec(open('load.py').read())
import statsmodels.api as sm, statsmodels.formula.api as smf
x['tsr'] = x.tsec.round(0)
u = x.drop_duplicates(['slug', 'side', 'price', 'tsr']).copy()
u['lp'] = np.log(u.price / (1 - u.price))
cl = lambda d: dict(cov_type='cluster', cov_kwds={'groups': pd.factorize(d.slug)[0]})
B = sm.families.Binomial()

print('== T1 calibration: win ~ logit(price), window-clustered')
print(smf.glm('win~lp', u, family=B).fit(**cl(u)).summary().tables[1])

print('== T2 price-bucket edge (all families, de-duped)')
u['pb'] = pd.cut(u.price, [0, .3, .4, .5, .6, .75, .9, 1])
print(u.groupby('pb', observed=True).agg(n=('ret', 'size'), nwin=('slug', 'nunique'), px=('price', 'mean'), wr=('win', 'mean'), ret=('ret', 'mean')).round(3))

print('== T3 does any signal add info beyond price?')
f = x[x.family == 'FAIR'].drop_duplicates(['slug', 'side', 'price', 'tsr']).copy()
f = f[(f.fair > .01) & (f.fair < .99)]; f['lp'] = np.log(f.price / (1 - f.price)); f['lf'] = np.log(f.fair / (1 - f.fair))
print('FAIR', smf.glm('win~lp+lf', f, family=B).fit(**cl(f)).summary().tables[1])
for fam in ['MOM', 'REV']:
    d = x[x.family == fam].drop_duplicates(['slug', 'side', 'price', 'tsr']).copy()
    d['lp'] = np.log(d.price / (1 - d.price)); d['smove'] = np.where(d.side == 'Up', d.move, -d.move)
    print(fam, smf.glm('win~lp+smove', d, family=B).fit(**cl(d)).summary().tables[1])

print('== T4 pairwise logic: A first trade | B already agree/oppose/none (96 cells)')
fams = sorted(first.family.unique()); rows = []
for A in fams:
    a = first[first.family == A]
    for Bf in fams:
        if A == Bf: continue
        b = first[first.family == Bf][['slug', 'side', 'tsec']].rename(columns={'side': 'bs', 'tsec': 'bt'})
        m = a.merge(b, on='slug', how='left')
        st = np.where(m.bt.isna() | (m.bt > m.tsec), 'none', np.where(m.bs == m.side, 'agree', 'oppose'))
        for k in ['agree', 'oppose', 'none']:
            d = m[st == k]
            if len(d) >= 30: rows.append((A, Bf, k, len(d), d.ret.mean(), d.ret.std() / np.sqrt(len(d))))
r = pd.DataFrame(rows, columns=['A', 'B', 'state', 'n', 'ret', 'se']); r['z'] = r.ret / r.se
print(len(r), 'cells; max z', r.z.max().round(2), '(expected max of', len(r), 'null draws ~2.5)')
print(r.sort_values('z', ascending=False).head(8).round(3).to_string())

print('== T5 consensus: net #families already on my side')
fs = first.sort_values('tsec'); rows = []
for slug, d in fs.groupby('slug'):
    seen = {}
    for q in d.itertuples():
        ag = sum(sd == q.side for sd in seen.values()); rows.append((2 * ag - len(seen), q.ret)); seen[q.family] = q.side
c = pd.DataFrame(rows, columns=['net', 'ret'])
print(c.groupby(c.net.clip(-3, 3)).ret.agg(['size', 'mean']).round(3))

print('== T6 window sequence')
w = s.dropna(subset=['winner']).drop_duplicates('slug').sort_values('start')
w['up'] = (w.winner == 'Up').astype(int); w['pu'] = w.up.shift(); w['ps'] = w.start.shift()
cc = w[w.start - w.ps == 300]
print('P(up|prev up)=%.3f  P(up|prev down)=%.3f  n=%d' % (cc[cc.pu == 1].up.mean(), cc[cc.pu == 0].up.mean(), len(cc)))
print('spot-sign != official winner: %.3f of windows' % ((w.close > w.open).astype(int) != w.up).mean())

print('== T7 follow-the-hot-account (trailing L windows, top-k accounts)')
P = x.groupby(['start', 'account']).ppnl.sum().unstack().sort_index(); Pt = P.fillna(0); act = P.notna()
for L, k in [(72, 5), (144, 5), (288, 1)]:
    out = []
    for i in range(L, len(P)):
        n = act.iloc[i - L:i].sum(); tr = (Pt.iloc[i - L:i].sum() / np.maximum(n, 1))[n >= 10]
        rr = P.iloc[i][tr.nlargest(k).index].dropna()
        if len(rr): out.append(rr.mean())
    o = np.array(out); print('L=%d top%d  $/window %.3f (se %.3f)  vs all-account avg %.3f' % (L, k, o.mean(), o.std() / np.sqrt(len(o)), Pt.sum().sum() / act.sum().sum()))

print('== T8 other sources')
cs = rd('copy-trade/copy_settlements.jsonl.gz'); print('copy-trade n=%d wr=%.3f pnl=%.2f' % (len(cs), (cs.side == cs.winner).mean(), cs.pnl.sum()))
p = rd('pm5-forward/results.jsonl.gz').dropna(subset=['winner']); print('pm5 n=%d hit=%.3f' % (len(p), p.win.mean()))
t1, s1, W1 = prep(rd('farm-1h/trades.jsonl.gz'), rd('farm-1h/settlements.jsonl.gz'))
y = t1[t1.leg == 1].dropna(subset=['win']).copy(); y['feeps'] = fee_ps(y.tsec.values, y.price.values, h1=True)
y['ret'] = (y.win - y.price - y.feeps) / y.price; y['tsr'] = y.tsec.round(0)
y = y.drop_duplicates(['slug', 'side', 'price', 'tsr']); y['pb'] = pd.cut(y.price, [0, .4, .5, .6, .75, 1])
print('1h farm', W1.size, 'windows'); print(y.groupby(['family', 'pb'], observed=True).agg(n=('ret', 'size'), wr=('win', 'mean'), px=('price', 'mean'), ret=('ret', 'mean')).round(3))
print('== T9 walk-forward ML over all family states: run ml.py')
