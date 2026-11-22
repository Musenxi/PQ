"""H1 part 1: how often do alternative 'daily extreme' definitions land in a different bucket than the
official routine-hourly-T-group value. Uses BASE/obs.json from build_obs.py."""
import json, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
from common import BASE
rows = [r for r in json.load(open(f"{BASE}/obs.json")) if r.get('b_rout') is not None and r['official'] is not None]
def cmp(rs, key, kind):
    rs = [r for r in rs if r.get(key) is not None]
    if not rs: return None
    sgn = 1 if kind == 'H' else -1
    beyond = sum(sgn * (r[key] - r['b_rout']) > 0 for r in rs)
    vb = sum(sgn * (r['v' + key[1:]] - r['v_rout']) > 0 for r in rs)
    return f"n={len(rs)} value-beyond={vb} ({vb/len(rs):.0%}) bucket-beyond={beyond} ({beyond/len(rs):.0%})"
for u in ['F', 'C']:
    for k in ['H', 'L']:
        rs = [r for r in rows if r['unit'] == u and r['kind'] == k]
        print(f"== {u}{k} n={len(rs)} match={sum(r['b_rout']==r['official'] for r in rs)}")
        for key in ['b_all', 'b_6h', 'b_cli']:
            print("  ", key, cmp(rs, key, k))
