"""Latency race around kill obs: trades on killed bucket (YES-equiv price py>=2c) by seconds after METAR obs time.
AWC publication measured live at ~140-215s after obs time (live_latency.py). Profit to whoever sold YES = py*size.
Excludes the disputed Miami Nov-7 low event (late METAR)."""
import json, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
from common import *
from load_px import *
ev = load_events(); rows = {r['id']: r for r in json.load(open(f"{BASE}/obs.json")) if r.get('b_rout') is not None}
bins = [(-600, 0), (0, 60), (60, 120), (120, 150), (150, 180), (180, 210), (210, 240), (240, 300), (300, 600), (600, 3600)]
agg = collections.defaultdict(lambda: [0.0, 0, 0.0]); days = set(); nk = collections.Counter(); wallets = collections.Counter()
for eid, r in rows.items():
    e = ev[eid]
    if e['slug'] == 'lowest-temperature-in-miami-on-november-7-2026' or not os.path.exists(f"{PX}/{eid}_0_tr.json"): continue
    g = e['unit'] + e['kind']; H = e['kind'] == 'H'; run = None; dead = set()
    days.add((g, str(e['date'])))
    for ts, lab, t10, *_ in r['obs']:
        if lab != 'METAR': continue
        v = to_unit(t10, e['unit']); run = v if run is None else (max(run, v) if H else min(run, v))
        for i, b in enumerate(e['buckets']):
            if i in dead: continue
            if (H and b['hi'] < run) or ((not H) and b['lo'] > run):
                dead.add(i); nk[g] += 1
                for t in load_tr(eid, i) or []:
                    d = t['ts'] - ts
                    if t['py'] < 0.02: continue
                    for lo, hi in bins:
                        if lo <= d < hi:
                            a = agg[(g, lo, t['toyes'])]; a[0] += t['size'] * t['py']; a[1] += 1; a[2] += t['size']
                            if 120 <= d < 300 and not t['toyes']: wallets[t['w']] += t['size'] * t['py']
ndays = collections.Counter(g for g, _ in days)
for g in sorted(nk):
    print(f"{g}: kills={nk[g]} days={ndays[g]}")
    for lo, hi in bins:
        s = agg.get((g, lo, False), [0, 0, 0]); b = agg.get((g, lo, True), [0, 0, 0])
        print(f"   [{lo:5d},{hi:5d})s  takerSELLdeadYES ${s[0]:7.0f} n={s[1]:4d} avg_py={(s[0]/s[2] if s[2] else 0):.3f} | takerBUYdeadYES ${b[0]:7.0f} n={b[1]:4d}")
tot = sum(wallets.values())
print("sellers of dead YES in 120-300s window: total $", round(tot), "top wallets share:", [round(v / tot, 2) for _, v in wallets.most_common(5)], "n wallets", len(wallets))
