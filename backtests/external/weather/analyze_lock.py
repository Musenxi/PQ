"""Lock-in latency. For each routine obs that kills buckets (H: bucket.hi < new running max;
L: bucket.lo > new running min), track killed bucket's YES price (1-min history) & trades after obs time.
Dead-bucket trade $ = trades with ts >= obs_ts+LAT at YES price py>=MINP."""
import json, sys, os, collections, statistics
sys.path.insert(0, os.path.dirname(__file__))
from common import *
from load_px import *
LAT = int(os.environ.get('LAT', 240)); MINP = 0.02
ev = load_events()
rows = {r['id']: r for r in json.load(open(f"{BASE}/obs.json")) if r.get('b_rout') is not None and r['official'] is not None}
kills = []; agg = collections.defaultdict(float); ev_n = collections.Counter(); per_event = collections.defaultdict(float)
lag_bins = [(0, 300), (300, 900), (900, 1800), (1800, 3600), (3600, 4 * 3600), (4 * 3600, 99 * 3600)]
for eid, r in rows.items():
    e = ev[eid]
    if not os.path.exists(f"{PX}/{eid}_0_ph.json") or not os.path.exists(f"{PX}/{eid}_0_tr.json"): continue
    ev_n[e['unit'] + e['kind']] += 1
    bks = e['buckets']; H = e['kind'] == 'H'
    run = None; dead = set()
    for ts, lab, t10, *_ in r['obs']:
        if lab != 'METAR': continue
        v = to_unit(t10, e['unit'])
        run = v if run is None else (max(run, v) if H else min(run, v))
        for i, b in enumerate(bks):
            if i in dead: continue
            if (H and b['hi'] < run) or ((not H) and b['lo'] > run):
                dead.add(i)
                ph = load_ph(eid, i); tr = load_tr(eid, i)
                pre = px_at(ph, ts - 120)
                if pre is None or pre < MINP: continue   # only interesting if it was alive in price
                rec = dict(eid=eid, grp=e['unit'] + e['kind'], i=i, ts=ts, pre=pre,
                           p5=px_at(ph, ts + 300), p10=px_at(ph, ts + 600), p30=px_at(ph, ts + 1800), p60=px_at(ph, ts + 3600), p180=px_at(ph, ts + 3 * 3600))
                # time until price < MINP
                tdead = None
                for t, p in ph:
                    if t >= ts and p < MINP: tdead = t - ts; break
                rec['t_below'] = tdead
                # trades after kill
                for t in tr:
                    if t['ts'] < ts + LAT or t['py'] < MINP: continue
                    lag = t['ts'] - ts
                    for lo, hi in lag_bins:
                        if lo <= lag < hi:
                            key = (e['unit'] + e['kind'], lo, 'takerYES' if t['toyes'] else 'takerNO')
                            agg[key + ('usd',)] += t['size'] * t['py']   # $ of YES-equivalent paid at dead price = edge $ for counterparty
                            agg[key + ('n',)] += 1
                    if t['toyes']: per_event[eid] += t['size'] * t['py']
                kills.append(rec)
json.dump(kills, open(f"{BASE}/kills.json", "w"))
print("events with px+tr:", dict(ev_n), "kills with pre>=2c:", len(kills))
for g in sorted(set(k['grp'] for k in kills)):
    K = [k for k in kills if k['grp'] == g]
    def med(x):
        x = [v for v in x if v is not None]; return f"{statistics.median(x):.3f}" if x else '-'
    tb = [k['t_below'] for k in K if k['t_below'] is not None]
    print(f"{g} kills={len(K)} median px: pre={med(k['pre'] for k in K)} +5m={med(k['p5'] for k in K)} +10m={med(k['p10'] for k in K)} +30m={med(k['p30'] for k in K)} +60m={med(k['p60'] for k in K)}")
    print(f"   frac still >=5c: +10m {sum((k['p10'] or 0)>=.05 for k in K)/len(K):.2f} +30m {sum((k['p30'] or 0)>=.05 for k in K)/len(K):.2f} +60m {sum((k['p60'] or 0)>=.05 for k in K)/len(K):.2f}; t_below2c median {statistics.median(tb)/60 if tb else -1:.1f}min (n={len(tb)}/{len(K)})")
    for lo, hi in lag_bins:
        a = agg.get((g, lo, 'takerYES', 'usd'), 0); na = agg.get((g, lo, 'takerYES', 'n'), 0)
        b = agg.get((g, lo, 'takerNO', 'usd'), 0); nb = agg.get((g, lo, 'takerNO', 'n'), 0)
        print(f"   lag {lo/60:5.0f}-{hi/60:5.0f}m: taker-buys-dead-YES ${a:8.0f} ({na:.0f} tr)  taker-sells-dead-YES ${b:8.0f} ({nb:.0f} tr)")
ndays = len(set(ev[k]['date'] for k in per_event)) or 1
print("dead-YES taker buy $ (=maker capture upper bound) total", round(sum(per_event.values())), "per day", round(sum(per_event.values()) / ndays))
