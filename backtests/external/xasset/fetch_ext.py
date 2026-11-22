"""Coinbase 1m candles (BTC/ETH/SOL/XRP) + Deribit DVOL (1m) and BTC perp funding, last DAYS.
usage: python -I fetch_ext.py DAYS"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import get_json, RAW, save_gz, load_gz
from datetime import datetime, timezone

days = float(sys.argv[1])
end = int(time.time()) // 60 * 60
start = end - int(days * 86400)
iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
for a in ["BTC", "ETH", "SOL", "XRP"]:
    p = os.path.join(RAW, f"cb_{a}_1m.json.gz")
    if os.path.exists(p):
        continue
    rows = {}
    t = start
    while t < end:
        t2 = min(t + 300 * 60, end)
        d = get_json(f"https://api.exchange.coinbase.com/products/{a}-USD/candles?granularity=60&start={iso(t)}&end={iso(t2)}", min_gap=0.4)
        for r in d or []:
            rows[r[0]] = r  # [time, low, high, open, close, volume]
        t = t2
    save_gz(p, sorted(rows.values()))
    print(a, len(rows), flush=True)

for c in ["BTC", "ETH"]:
    p = os.path.join(RAW, f"dvol_{c}.json.gz")
    if os.path.exists(p):
        continue
    rows = {}
    t = start * 1000
    while t < end * 1000:
        t2 = min(t + 1000 * 60000, end * 1000)
        d = get_json(f"https://www.deribit.com/api/v2/public/get_volatility_index_data?currency={c}&start_timestamp={t}&end_timestamp={t2}&resolution=60", min_gap=0.4)
        for r in d["result"]["data"]:
            rows[r[0]] = r  # [ms, open, high, low, close]
        t = t2
    save_gz(p, sorted(rows.values()))
    print("dvol", c, len(rows), flush=True)

p = os.path.join(RAW, "funding_BTC.json.gz")
if not os.path.exists(p):
    rows = []
    t = start * 1000
    while t < end * 1000:
        t2 = min(t + 700 * 3600000, end * 1000)
        d = get_json(f"https://www.deribit.com/api/v2/public/get_funding_rate_history?instrument_name=BTC-PERPETUAL&start_timestamp={t}&end_timestamp={t2}", min_gap=0.4)
        rows += d["result"]; t = t2
    save_gz(p, rows); print("funding", len(rows))
