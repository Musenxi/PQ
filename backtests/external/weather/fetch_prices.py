"""Per event: 1-min CLOB prices-history of every bucket's YES token + all data-api v2 trades per bucket.
Two threads (one per host), ~2.5 req/s each. Output raw json per (event, bucket)."""
import json, os, sys, time, threading, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from common import *
OUT = f"{BASE}/px"; os.makedirs(OUT, exist_ok=True)
ev = load_events()
order = sorted(ev.values(), key=lambda e: (e['unit'] != 'F', -e['date'].toordinal(), -e['vol']))
only = sys.argv[1] if len(sys.argv) > 1 else None
if only == 'F': order = [e for e in order if e['unit'] == 'F']
if only == 'CH': order = [e for e in order if e['unit'] == 'C' and e['kind'] == 'H' and str(e['date']) >= (sys.argv[2] if len(sys.argv) > 2 else '2026-11-12')]

def get(url):
    for k in range(5):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research"}), timeout=60).read())
        except Exception as ex:
            code = getattr(ex, 'code', None)
            if code == 404: return None
            time.sleep(2 * (k + 1) + (10 if code == 429 else 0))
    return None

def prices_worker():
    for e in order:
        a, b = day_bounds(e['date'], e['tz'])
        for i, bk in enumerate(e['buckets']):
            fn = f"{OUT}/{e['id']}_{i}_ph.json"
            if os.path.exists(fn): continue
            d = get(f"https://clob.polymarket.com/prices-history?market={bk['yes']}&startTs={int(a-18*3600)}&endTs={int(b+3*3600)}&fidelity=1")
            if d is not None: json.dump(d, open(fn, 'w'))
            time.sleep(0.28)

def trades_worker():
    for e in order:
        for i, bk in enumerate(e['buckets']):
            fn = f"{OUT}/{e['id']}_{i}_tr.json"
            if os.path.exists(fn): continue
            allt, cur, n = [], None, 0
            while True:
                url = f"https://data-api.polymarket.com/v2/trades?condition={bk['cond']}&limit=500" + (f"&cursor={cur}" if cur else "")
                d = get(url); time.sleep(0.28)
                if d is None: break
                for t in d.get('data', []):
                    allt.append({k: t[k] for k in ('side', 'outcome', 'size', 'price', 'timestamp', 'proxy_wallet', 'transaction_hash')})
                cur = (d.get('pagination') or {}).get('next_cursor'); n += 1
                if not cur or n > 40: break
            json.dump(allt, open(fn, 'w'))
th = [threading.Thread(target=prices_worker), threading.Thread(target=trades_worker)]
[t.start() for t in th]; [t.join() for t in th]
print("done")
