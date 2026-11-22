"""Market calibration: all buckets, YES price at local hour h vs realized. Bins by price; split by unit/kind.
Also favourite-longshot: ret of buying YES in each price bin (price + HS + fee)."""
import json, sys, os, collections, random, datetime as dt
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(__file__))
from common import *
from load_px import *
HS = float(os.environ.get('HS', 0.01))
ev = load_events()
rows = {r['id']: r for r in json.load(open(f"{BASE}/obs.json")) if r['official'] is not None}
bins = [0, .02, .05, .1, .2, .35, .5, .65, .8, .9, .95, .98, 1.01]
cal = collections.defaultdict(list)
for eid, r in rows.items():
    e = ev[eid]
    if not os.path.exists(f"{PX}/{eid}_0_ph.json"): continue
    z = ZoneInfo(e['tz'])
    for i in range(len(e['buckets'])):
        ph = load_ph(eid, i)
        for h in (-6, 0, 8, 12):   # -6 = 18:00 previous day
            d0 = dt.datetime(e['date'].year, e['date'].month, e['date'].day, tzinfo=z) + dt.timedelta(hours=h)
            p = px_at(ph, d0.timestamp())
            if p is None: continue
            b = next(k for k in range(len(bins) - 1) if bins[k] <= p < bins[k + 1])
            cal[(e['unit'] + e['kind'], h, b)].append((eid, p, int(r['official'] == i)))
for g in ['FH', 'FL', 'CH', 'CL']:
    for h in (-6, 0, 8, 12):
        lines = []
        for b in range(len(bins) - 1):
            v = cal.get((g, h, b))
            if not v or len(v) < 20: continue
            mp = sum(x[1] for x in v) / len(v); hr = sum(x[2] for x in v) / len(v)
            ret = sum(x[2] - min(x[1] + HS, 0.999) - 0.01 * x[1] * (1 - x[1]) for x in v) / len(v)
            lines.append(f"[{bins[b]:.2f},{bins[b+1]:.2f}) n={len(v)} px={mp:.3f} hit={hr:.3f} buyYES={ret:+.3f}")
        if lines: print(g, f"h={h}", *lines, sep="\n   ")
