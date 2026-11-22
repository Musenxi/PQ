"""Fetch data-api v2 trades for markets in meta.json.gz, newest first.
usage: python -I fetch_trades.py DAYS [durs=5m,15m,1h]
Stores RAW/trades/<slug>.json.gz : list of [ts, outcome_index, side(1=BUY,-1=SELL), price, size]"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get_json, RAW, save_gz, load_gz

days = float(sys.argv[1])
durs = (sys.argv[2] if len(sys.argv) > 2 else "5m,15m,1h").split(",")
TD = os.path.join(RAW, "trades"); os.makedirs(TD, exist_ok=True)
from concurrent.futures import ThreadPoolExecutor
tmax = 1795287600
def one(v):
    rows, cur = [], None
    dur = {"5m": 300, "15m": 900, "1h": 3600}[v["dur"]]
    need = v["start"] + {"5m": 0, "15m": 600, "1h": 2700}[v["dur"]]  # only trades after this are needed
    for page in range(40):
        url = f"https://data-api.polymarket.com/v2/trades?condition={v['cond']}&limit=500"
        if cur:
            url += "&cursor=" + cur
        d = get_json(url, min_gap=0.34)
        if not d:
            break
        for r in d.get("data", []):
            rows.append([r["timestamp"], r["outcome_index"], 1 if r["side"] == "BUY" else -1,
                         r["price"], r["size"]])
        pg = d.get("pagination") or {}
        cur = pg.get("next_cursor")
        if not pg.get("has_more") or not cur:
            break
        if rows and min(r[0] for r in rows[-500:]) < need:
            break
    rows.sort()
    save_gz(os.path.join(TD, v["slug"] + ".json.gz"), rows)
    return len(rows)

t0 = time.time()
while True:
    meta = {}
    for fn in ("meta.json.gz", "meta_rev.json.gz"):
        if os.path.exists(os.path.join(RAW, fn)):
            meta.update({k: v for k, v in load_gz(os.path.join(RAW, fn)).items() if v})
    todo = [v for v in meta.values() if v and v["dur"] in durs and v["start"] >= tmax - days * 86400
            and not os.path.exists(os.path.join(TD, v["slug"] + ".json.gz"))]
    todo.sort(key=lambda v: -v["start"])
    print("todo", len(todo), round(time.time() - t0), flush=True)
    if not todo:
        if os.path.exists(os.path.join(RAW, "meta.done")):
            break
        time.sleep(60); continue
    with ThreadPoolExecutor(4) as ex:
        for n, k in enumerate(ex.map(one, todo[:600])):
            pass
print("done")
