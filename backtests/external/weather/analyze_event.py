"""Event study around 'kill' observations: killed bucket's YES price at offsets relative to METAR obs time,
for kills where price 30 min before was >= PMIN. Also taker volume on killed bucket by offset window."""
import json, sys, os, collections, statistics
sys.path.insert(0, os.path.dirname(__file__))
from common import *
from load_px import *
PMIN = float(os.environ.get('PMIN', 0.10))
ev = load_events()
rows = {r['id']: r for r in json.load(open(f"{BASE}/obs.json")) if r.get('b_rout') is not None and r['official'] is not None}
offs = [-60, -30, -20, -15, -10, -7, -5, -3, -1, 0, 1, 2, 3, 4, 5, 7, 10, 15, 30]
traj = collections.defaultdict(lambda: collections.defaultdict(list)); vol = collections.defaultdict(lambda: collections.defaultdict(float))
nk = collections.Counter(); hi_trades = collections.defaultdict(list)
for eid, r in rows.items():
    e = ev[eid]
    if not os.path.exists(f"{PX}/{eid}_0_tr.json"): continue
    g = e['unit'] + e['kind']; H = e['kind'] == 'H'
    run = None; dead = set()
    for ts, lab, t10, *_ in r['obs']:
        if lab != 'METAR': continue
        v = to_unit(t10, e['unit']); run = v if run is None else (max(run, v) if H else min(run, v))
        for i, b in enumerate(e['buckets']):
            if i in dead: continue
            if (H and b['hi'] < run) or ((not H) and b['lo'] > run):
                dead.add(i)
                ph = load_ph(eid, i); p0 = px_at(ph, ts - 1800)
                if p0 is None or p0 < PMIN: continue
                nk[g] += 1
                for o in offs:
                    p = px_at(ph, ts + o * 60)
                    if p is not None: traj[g][o].append(p)
                for t in load_tr(eid, i) or []:
                    d = (t['ts'] - ts) / 60
                    if -30 <= d < 30:
                        w = int((d + 30) // 5) * 5 - 30
                        vol[g][(w, t['toyes'])] += t['size'] * t['py']
                        if d >= 0 and t['py'] >= 0.05: hi_trades[g].append((round(d, 1), round(t['py'], 3), round(t['size'], 1), t['toyes']))
for g in sorted(traj):
    print(f"{g}: kills with p(-30m)>={PMIN}: {nk[g]}")
    print("  offset(min): " + " ".join(f"{o:>5}" for o in offs))
    print("  median px:   " + " ".join(f"{statistics.median(traj[g][o]):5.3f}" if traj[g][o] else "    -" for o in offs))
    print("  mean px:     " + " ".join(f"{statistics.mean(traj[g][o]):5.3f}" if traj[g][o] else "    -" for o in offs))
    print("  taker $ into dead-YES (buyYES / sellYES) per 5-min window from -30..+30:")
    print("   " + " ".join(f"{w}:{vol[g].get((w, True), 0):.0f}/{vol[g].get((w, False), 0):.0f}" for w in range(-30, 30, 5)))
    hs = sorted(hi_trades[g])
    print(f"  trades at py>=5c after obs ts: {len(hs)}; first 25:", hs[:25])
