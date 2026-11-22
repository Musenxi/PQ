"""Per event: compute resolution value from routine METAR T-groups, alt definitions, and compare to official bucket.
Writes BASE/obs.json"""
import json, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
from common import *
ev = load_events()
cli = {}
for s in ['KLAX','KDEN','KSEA','KHOU','KAUS','KLGA','KSFO','KORD','KATL','KDAL','KMIA']:
    try:
        for r in json.load(open(f"{BASE}/cli/{s}.json"))['results']:
            cli[(s, r['valid'])] = (r['high'], r['low'])
    except Exception: pass
metars = {}
def bucket_of(v, bks):
    for i, b in enumerate(bks):
        if b['lo'] <= v <= b['hi']: return i
    return None
rows = []
for e in ev.values():
    if e['stn'] not in metars: metars[e['stn']] = load_metar(e['stn'])
    M = metars[e['stn']]
    a, b = day_bounds(e['date'], e['tz'])
    obs = []
    for (k, lab), raw in M.items():
        ts = metar_ts(k)
        if a <= ts < b:
            t, bc, mx, mn = temps(raw)
            obs.append(dict(ts=ts, lab=lab, t10=t if t is not None else (bc * 10 if bc is not None else None), tg=t is not None, mx6=mx, mn6=mn))
    obs.sort(key=lambda o: o['ts'])
    rout = [o for o in obs if o['lab'] == 'METAR' and o['t10'] is not None]
    allo = [o for o in obs if o['t10'] is not None]
    off = [i for i, bk in enumerate(e['buckets']) if bk['res'] == 1]
    r = dict(id=e['id'], slug=e['slug'], stn=e['stn'], kind=e['kind'], unit=e['unit'], date=str(e['date']), n_rout=len(rout), n_speci=len(obs) - len(rout),
             tg_frac=(sum(o['tg'] for o in rout) / len(rout)) if rout else None, official=off[0] if len(off) == 1 else None,
             nb=len(e['buckets']), vol=e['vol'])
    if rout:
        f = max if e['kind'] == 'H' else min
        v_r = f(to_unit(o['t10'], e['unit']) for o in rout)
        v_a = f(to_unit(o['t10'], e['unit']) for o in allo)
        r.update(v_rout=v_r, v_all=v_a, b_rout=bucket_of(v_r, e['buckets']), b_all=bucket_of(v_a, e['buckets']))
        g = [o['mx6' if e['kind'] == 'H' else 'mn6'] for o in obs if o[('mx6' if e['kind'] == 'H' else 'mn6')] is not None]
        # 6h groups only fully inside the day: report time - 6h >= day start
        g2 = [o['mx6' if e['kind'] == 'H' else 'mn6'] for o in obs if o[('mx6' if e['kind'] == 'H' else 'mn6')] is not None and o['ts'] - 6*3600 >= a - 600]
        if g2:
            v6 = f(f(to_unit(x, e['unit']) for x in g2), v_r)
            r.update(v_6h=v6, b_6h=bucket_of(v6, e['buckets']))
        c = cli.get((e['stn'], str(e['date'])))
        if c and e['unit'] == 'F':
            cv = c[0] if e['kind'] == 'H' else c[1]
            if isinstance(cv, (int, float)): r.update(v_cli=int(cv), b_cli=bucket_of(int(cv), e['buckets']))
        # time of extreme (first time the final extreme reached)
        for o in rout:
            if to_unit(o['t10'], e['unit']) == v_r: r['t_ext'] = o['ts']; break
        r['last_rout'] = rout[-1]['ts']; r['day_a'] = a; r['day_b'] = b
    r['obs'] = [(o['ts'], o['lab'], o['t10'], o['mx6'], o['mn6']) for o in obs if o['t10'] is not None]
    rows.append(r)
json.dump(rows, open(f"{BASE}/obs.json", 'w'))
ok = [r for r in rows if r.get('b_rout') is not None and r['official'] is not None]
print("events", len(rows), "with obs+official", len(ok))
for u in ['F', 'C']:
    s = [r for r in ok if r['unit'] == u]
    print(u, len(s), "match", sum(r['b_rout'] == r['official'] for r in s), "match_all(incl SPECI)", sum(r['b_all'] == r['official'] for r in s))
mm = [r for r in ok if r['b_rout'] != r['official']]
for r in mm[:40]:
    print(r['slug'], r['stn'], 'rout', r['v_rout'], r['b_rout'], 'off', r['official'], 'all', r['v_all'], 'nrout', r['n_rout'], 'tg', round(r['tg_frac'], 2))
