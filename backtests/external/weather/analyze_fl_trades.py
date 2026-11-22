"""Trade-based check of late-day strategies (prices-history may be stale in thin markets).
At local hour h, current bucket c from routine obs published by T. For 'beyond' bucket b (H: c+1, L: c-1) and c,
collect actual trades in [T, T+W]: executable evidence. Sell-YES-into-bids = trades where taker sold YES (toyes False) at py.
Return per share of selling YES (=buying NO) at py: py - y_b - fee. Clustered bootstrap by event."""
import json, sys, os, random, collections, datetime as dt
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(__file__))
from common import *
from load_px import *
LAT = 300; W = int(os.environ.get('W', 7200)); UNIT = os.environ.get('UNIT', 'F')
ev = load_events()
rows = {r['id']: r for r in json.load(open(f"{BASE}/obs.json")) if r.get('b_rout') is not None and r['official'] is not None}
def bucket_of(v, bks):
    for i, b in enumerate(bks):
        if b['lo'] <= v <= b['hi']: return i
fee = lambda p: 0.01 * p * (1 - p)
res = collections.defaultdict(list)
for eid, r in rows.items():
    e = ev[eid]
    if e['unit'] != UNIT or not os.path.exists(f"{PX}/{eid}_0_tr.json"): continue
    f = max if e['kind'] == 'H' else min; sg = 1 if e['kind'] == 'H' else -1
    z = ZoneInfo(e['tz'])
    for h in ([12, 14, 16, 18] if e['kind'] == 'H' else [8, 10, 12, 15, 18]):
        T = dt.datetime(e['date'].year, e['date'].month, e['date'].day, h, tzinfo=z).timestamp()
        ro = [to_unit(t10, e['unit']) for ts, lab, t10, *_ in r['obs'] if lab == 'METAR' and ts + LAT <= T]
        if not ro: continue
        c = bucket_of(f(ro), e['buckets'])
        if c is None: continue
        y = r['official']
        for tag, j in (('beyond', c + sg), ('current', c)):
            if not (0 <= j < len(e['buckets'])): continue
            tr = [t for t in (load_tr(eid, j) or []) if T <= t['ts'] < T + W]
            if not tr: res[(tag, e['kind'], h, 'notrade')].append((eid, 0)); continue
            for t in tr:
                # sell YES at py (beyond) or buy YES at py (current)
                pnl = (t['py'] - (y == j) - fee(t['py'])) if tag == 'beyond' else ((y == j) - t['py'] - fee(t['py']))
                key = (tag, e['kind'], h, 'takerSELLyes' if not t['toyes'] else 'takerBUYyes')
                res[key].append((eid, pnl, t['size'], t['py']))
def boot(v, n=1000):
    random.seed(3); by = collections.defaultdict(list)
    for x in v: by[x[0]].append(x[1])
    ks = list(by); ms = []
    for _ in range(n):
        s = [random.choice(ks) for _ in ks]; ms.append(sum(sum(by[k]) for k in s) / max(1, sum(len(by[k]) for k in s)))
    ms.sort(); return ms[25], ms[974]
print(f"UNIT={UNIT} window={W}s")
for k in sorted(res):
    v = res[k]
    if k[3] == 'notrade': print(k, 'events with no trades:', len(v)); continue
    lo, hi = boot(v); usd = sum(x[2] * x[3] for x in v); sh = sum(x[2] for x in v)
    wpnl = sum(x[1] * x[2] for x in v)
    print(f"{k} trades={len(v)} events={len(set(x[0] for x in v))} vwap={usd/sh:.3f} pnl/sh(eq-wt)={sum(x[1] for x in v)/len(v):+.3f} CI[{lo:+.3f},{hi:+.3f}] size-wt pnl$={wpnl:+.0f} on {sh:.0f} sh")
