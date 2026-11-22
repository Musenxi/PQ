"""Fetch Gamma metadata for 5m/15m/1h up/down markets (btc/eth/sol/xrp).
usage: python -I fetch_meta.py DAYS"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get_json, RAW, save_gz, load_gz

ASSETS = ["btc", "eth", "sol", "xrp"]
DUR = {"5m": 300, "15m": 900, "1h": 3600}
out = os.path.join(RAW, sys.argv[2] if len(sys.argv) > 2 else "meta.json.gz")
meta = load_gz(out) if os.path.exists(out) else {}
days = float(sys.argv[1])
now = int(time.time()) // 3600 * 3600 - 3600
t0 = (now - int(days * 86400)) // 3600 * 3600
slugs = []
for t in range(t0, now, 300):
    for d, s in DUR.items():
        if t % s == 0:
            for a in ASSETS:
                sl = f"{a}-updown-{d}-{t}"
                if sl not in meta:
                    slugs.append(sl)
if len(sys.argv) > 3:
    slugs = slugs[::-1][:int(sys.argv[3])]
print("todo", len(slugs), flush=True)

def parse(e):
    m = e["markets"][0]
    em = e.get("eventMetadata") or {}
    a, _, d, t = e["slug"].split("-")
    return dict(slug=e["slug"], asset=a, dur=d, start=int(t), cond=m["conditionId"],
                tokens=json.loads(m["clobTokenIds"]), res=json.loads(m["outcomePrices"]),
                k=em.get("priceToBeat"), f=em.get("finalPrice"), fee=m.get("feeSchedule"),
                vol=m.get("volume"), closed=m.get("closed"), cfg=m.get("cryptoMarketConfigId"))

B = 20
for i in range(0, len(slugs), B):
    chunk = slugs[i:i + B]
    url = "https://gamma-api.polymarket.com/events?" + "&".join("slug=" + s for s in chunk)
    E = get_json(url, min_gap=0.4) or []
    got = set()
    for e in E:
        try:
            r = parse(e); meta[r["slug"]] = r; got.add(r["slug"])
        except Exception as ex:
            print("parse err", e.get("slug"), ex)
    for s in chunk:
        if s not in got:
            meta[s] = None
    if (i // B) % 50 == 0:
        save_gz(out, meta); print(i, len(meta), flush=True)
save_gz(out, meta)
print("done", len(meta), sum(v is not None for v in meta.values()))
open(os.path.join(RAW, "meta.done"), "w").write("1")
