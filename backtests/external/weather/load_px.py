"""Helpers to load per-bucket price paths and trades."""
import json, os, bisect
from common import BASE
PX = f"{BASE}/px"
def load_ph(eid, i):
    fn = f"{PX}/{eid}_{i}_ph.json"
    if not os.path.exists(fn): return None
    try: h = json.load(open(fn)).get('history', [])
    except Exception: return None
    return [(x['t'], x['p']) for x in h]
def load_tr(eid, i):
    fn = f"{PX}/{eid}_{i}_tr.json"
    if not os.path.exists(fn): return None
    out = []
    try: raw = json.load(open(fn))
    except Exception: return None
    for t in raw:
        yes = t['outcome'].lower() == 'yes'
        py = t['price'] if yes else 1 - t['price']
        # taker buys YES exposure if (BUY & yes) or (SELL & no)
        toyes = (t['side'] == 'BUY') == yes
        out.append(dict(ts=t['timestamp'], py=py, size=t['size'], toyes=toyes, usd=t['size'] * t['price'], w=t['proxy_wallet']))
    out.sort(key=lambda x: x['ts'])
    return out
def px_at(ph, ts):
    """last price at or before ts"""
    if not ph: return None
    k = bisect.bisect_right([t for t, _ in ph], ts) - 1
    if k < 0: return None
    if ts - ph[k][0] > 3 * 3600: return None
    return ph[k][1]
