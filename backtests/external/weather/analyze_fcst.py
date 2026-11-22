"""Forecast edge (US F markets): NBM (NBS) 06Z TXN + XND (std) from IEM MOS archive vs market prices at local 08:00/11:00.
Model: official value ~ Normal(txn + bias, k*xnd), integer-bucket probabilities with continuity correction.
bias,k fit on TRAIN dates (< split), evaluated on TEST dates. Trade: buy YES where p_model - p_mkt > TH, at p_mkt + HS."""
import json, sys, os, math, random, collections, datetime as dt
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(__file__))
from common import *
from load_px import *
HS = float(os.environ.get('HS', 0.01)); SPLIT = os.environ.get('SPLIT', '2026-11-09')
ev = load_events()
rows = {r['id']: r for r in json.load(open(f"{BASE}/obs.json")) if r.get('b_rout') is not None and r['official'] is not None}
def nbs(stn, date, kind, lead=0):
    """lead=0: same-day 06Z run for H (prev-day run for L, whose 12Z min is not in same-day run); lead=1: one day earlier."""
    rd = (date if kind == 'H' else date - dt.timedelta(days=1)) - dt.timedelta(days=lead)
    fn = f"{BASE}/mos/{stn}_NBS_{rd:%Y%m%d}06.json"
    if not os.path.exists(fn): return None
    try: d = json.load(open(fn))['data']
    except Exception: return None
    want = (date + dt.timedelta(days=1)).strftime('%Y-%m-%d') + ' 00:00' if kind == 'H' else date.strftime('%Y-%m-%d') + ' 12:00'
    for r in d:
        if r['ftime'] == want and r.get('txn') is not None and r.get('xnd') is not None: return r['txn'], max(r['xnd'], 1.0)
    return None
Phi = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
data = []
for eid, r in rows.items():
    e = ev[eid]
    if e['unit'] != 'F': continue
    f = nbs(e['stn'], e['date'], e['kind'])
    f1 = nbs(e['stn'], e['date'], e['kind'], 1)
    if not f or not f1: continue
    data.append((e, r, f, f1))
print("events with NBM:", len(data))
def fit(sub, kind):
    res = [(r['v_rout'] - f[0], f[1]) for e, r, f, _ in sub if e['kind'] == kind]
    bias = sum(x for x, _ in res) / len(res)
    k = math.sqrt(sum(((x - bias) / s) ** 2 for x, s in res) / len(res))
    return bias, k, len(res)
par = {k: fit([d for d in data if str(d[0]['date']) < SPLIT], k) for k in 'HL'}
print("train fit (bias = official - NBM txn, k = sd multiplier):", par)
def probs(e, f):
    b, k, _ = par[e['kind']]; mu = f[0] + b; sd = k * f[1]
    ps = []
    for bk in e['buckets']:
        lo = -1e9 if bk['lo'] == -999 else bk['lo'] - 0.5; hi = 1e9 if bk['hi'] == 999 else bk['hi'] + 0.5
        ps.append(Phi((hi - mu) / sd) - Phi((lo - mu) / sd))
    return ps
out = collections.defaultdict(list); cal = collections.defaultdict(lambda: [0, 0, 0, 0])
for e, r, f0, f1 in data:
    test = str(e['date']) >= SPLIT
    z = ZoneInfo(e['tz'])
    for h in ((-6, 0) if e['kind'] == 'L' else (-6, 0, 8, 11)):
        # use only a run available by decision time: 06Z run ~ available 07:30Z
        # H: h>=8 same-day 06Z run, else previous-day run; L: f0 is already the previous-day 06Z run
        pm = probs(e, f0 if (e['kind'] == 'L' or h >= 8) else f1)
        T = (dt.datetime(e['date'].year, e['date'].month, e['date'].day, tzinfo=z) + dt.timedelta(hours=h)).timestamp()
        mk = [px_at(load_ph(e['id'], i), T) for i in range(len(e['buckets']))]
        if any(x is None for x in mk): continue
        s = sum(mk)
        y = r['official']
        ll_m = -math.log(max(mk[y] / s, 1e-3)); ll_f = -math.log(max(pm[y], 1e-3))
        br_m = sum((mk[i] / s - (i == y)) ** 2 for i in range(len(mk))); br_f = sum((pm[i] - (i == y)) ** 2 for i in range(len(mk)))
        out[('score', e['kind'], h, test)].append((ll_m, ll_f, br_m, br_f, ll_m - ll_f))
        for i in range(len(mk)):
            bin_ = min(int(mk[i] * 10), 9)
            c = cal[(e['kind'], h, bin_)]; c[0] += 1; c[1] += (i == y); c[2] += mk[i]; c[3] += pm[i]
            for TH in (0.05, 0.10, 0.15):
                if pm[i] - mk[i] > TH and mk[i] + HS < 0.97:
                    p = mk[i] + HS
                    out[('trade', e['kind'], h, test, TH)].append((e['id'], (i == y) - p - 0.01 * p * (1 - p)))
for k in sorted(k for k in out if k[0] == 'score'):
    v = out[k]; n = len(v)
    print(f"score {k[1]} h={k[2]} {'TEST' if k[3] else 'TRAIN'} n={n} logloss mkt={sum(x[0] for x in v)/n:.3f} nbm={sum(x[1] for x in v)/n:.3f} brier mkt={sum(x[2] for x in v)/n:.3f} nbm={sum(x[3] for x in v)/n:.3f}")
def boot(v, n=2000):
    random.seed(2); by = collections.defaultdict(list)
    for a, x in v: by[a].append(x)
    ks = list(by); ms = []
    for _ in range(n):
        smp = [random.choice(ks) for _ in ks]; ms.append(sum(sum(by[q]) for q in smp) / sum(len(by[q]) for q in smp))
    ms.sort(); return ms[50], ms[1949]
for k in sorted(k for k in out if k[0] == 'trade'):
    v = out[k]
    if len(v) < 10: continue
    lo, hi = boot(v)
    print(f"trade {k[1]} h={k[2]} {'TEST' if k[3] else 'TRAIN'} TH={k[4]} n={len(v)} ret/sh={sum(x for _, x in v)/len(v):+.4f} CI[{lo:+.3f},{hi:+.3f}]")
print("calibration (kind,h,price-bin): n, realized, mean mkt px, mean nbm p")
for k in sorted(cal):
    c = cal[k]
    if c[0] >= 30: print(k, c[0], f"{c[1]/c[0]:.3f} {c[2]/c[0]:.3f} {c[3]/c[0]:.3f}")
