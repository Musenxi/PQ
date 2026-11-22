"""Late-day strategies. At decision time T (local hour h), using only routine obs published by T
(obs ts + LAT seconds), compute running extreme -> current bucket c. Then:
  S1: buy YES on c at price p_c          payoff y_c - p_c - fee
  S2: buy NO on 'beyond' bucket (c+1 for H, c-1 for L)   payoff p_b - y_b - fee
  S3: buy NO on the SPECI-anchored bucket when SPECI running extreme is in a more extreme bucket than routine
Price: 1-min CLOB prices-history (last <= T) plus a flat half-spread HS. Also trade-VWAP variant.
CI: bootstrap over events (city-days)."""
import json, sys, os, random, collections, datetime as dt
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(__file__))
from common import *
from load_px import *
LAT = int(os.environ.get('LAT', 300)); HS = float(os.environ.get('HS', 0.01))
ev = load_events()
rows = {r['id']: r for r in json.load(open(f"{BASE}/obs.json")) if r.get('b_rout') is not None and r['official'] is not None}
def fee(p): return 0.01 * p * (1 - p)
def bucket_of(v, bks):
    for i, b in enumerate(bks):
        if b['lo'] <= v <= b['hi']: return i
res = collections.defaultdict(list)
for eid, r in rows.items():
    e = ev[eid]
    if not os.path.exists(f"{PX}/{eid}_0_ph.json"): continue
    phs = [load_ph(eid, i) for i in range(len(e['buckets']))]
    f = max if e['kind'] == 'H' else min
    sg = 1 if e['kind'] == 'H' else -1
    hours = [10, 12, 13, 14, 15, 16, 17, 19, 22] if e['kind'] == 'H' else [6, 8, 9, 10, 12, 15, 18, 21]
    z = ZoneInfo(e['tz'])
    for h in hours:
        T = dt.datetime(e['date'].year, e['date'].month, e['date'].day, h, 0, tzinfo=z).timestamp()
        ro = [to_unit(t10, e['unit']) for ts, lab, t10, *_ in r['obs'] if lab == 'METAR' and ts + LAT <= T]
        al = [to_unit(t10, e['unit']) for ts, lab, t10, *_ in r['obs'] if ts + LAT <= T]
        if not ro: continue
        c = bucket_of(f(ro), e['buckets']); s = bucket_of(f(al), e['buckets'])
        if c is None: continue
        y = r['official']
        pc = px_at(phs[c], T)
        if pc is not None:
            res[('S1', e['unit'], e['kind'], h)].append((eid, (y == c) - pc - HS - fee(pc), pc, y == c))
        b = c + sg
        if 0 <= b < len(phs):
            pb = px_at(phs[b], T)
            if pb is not None:
                res[('S2', e['unit'], e['kind'], h)].append((eid, pb - (y == b) - HS - fee(pb), pb, y == b))
        x6 = [to_unit(o[3 if e['kind'] == 'H' else 4], e['unit']) for o in r['obs'] if o[3 if e['kind'] == 'H' else 4] is not None and o[0] + LAT <= T and o[0] - 6 * 3600 >= r['day_a'] - 600]
        if x6:
            s6 = bucket_of(f(f(x6), f(ro)), e['buckets'])
            if s6 is not None and s6 != c:
                p6 = px_at(phs[s6], T)
                if p6 is not None:
                    res[('S4', e['unit'], e['kind'], h)].append((eid, p6 - (y == s6) - HS - fee(p6), p6, y == s6))
                    res[('S4c', e['unit'], e['kind'], h)].append((eid, (y == c) - pc - HS - fee(pc), pc, y == c))
        if s is not None and s != c:
            ps = px_at(phs[s], T)
            if ps is not None:
                res[('S3', e['unit'], e['kind'], h)].append((eid, ps - (y == s) - HS - fee(ps), ps, y == s))
def boot(v, n=2000):
    random.seed(1)
    by = collections.defaultdict(list)
    for eid, x, *_ in v: by[eid].append(x)
    ks = list(by)
    ms = []
    for _ in range(n):
        smp = [random.choice(ks) for _ in ks]
        tot = sum(sum(by[k]) for k in smp); cnt = sum(len(by[k]) for k in smp)
        ms.append(tot / cnt)
    ms.sort(); return ms[int(.025 * n)], ms[int(.975 * n)]
print(f"LAT={LAT}s HS={HS}")
for k in sorted(res):
    v = res[k]
    if len(v) < 15: continue
    m = sum(x for _, x, *_ in v) / len(v); lo, hi = boot(v)
    avgp = sum(p for _, _, p, _ in v) / len(v); hit = sum(yy for *_, yy in v) / len(v)
    print(f"{k[0]} {k[1]}{k[2]} h={k[3]:2d} n={len(v):4d} avg_px={avgp:.3f} hit={hit:.3f} ret/sh={m:+.4f} CI[{lo:+.4f},{hi:+.4f}]")
json.dump({"|".join(map(str, k)): v for k, v in res.items()}, open(f"{BASE}/late_res.json", "w"))
