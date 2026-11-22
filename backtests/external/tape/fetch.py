"""Fetch Polymarket BTC up/down window metadata (Gamma) + taker fill tape (Data API v2).

Usage: python -I fetch.py <kind:5m|15m|1h> <n_windows> <outdir> [end_ts]
Cache: <outdir>/<kind>/meta/<start>.json, <outdir>/<kind>/trades/<start>.json.gz
Rate: global token bucket ~2.7 req/s across a small thread pool; backoff on 429/5xx.
"""
import gzip, json, os, sys, threading, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

GAMMA = "https://gamma-api.polymarket.com/events"
DATA = "https://data-api.polymarket.com/v2/trades"
STEP = {"5m": 300, "15m": 900, "1h": 3600}
RATE = float(os.environ.get("RATE", "2.7"))

_lock = threading.Lock()
_next = [0.0]


def throttle():
    with _lock:
        now = time.time()
        t = max(now, _next[0])
        _next[0] = t + 1.0 / RATE
    if t > now:
        time.sleep(t - now)


def get(url):
    for k in range(8):
        throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "research-client/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 2 ** k)); continue
            raise
        except Exception:
            time.sleep(min(60, 2 ** k))
    raise RuntimeError("failed " + url)


def legacy_slug(s):
    """Pre-2026-11-10 16:00 UTC hourly slugs: bitcoin-up-or-down-november-10-2026-5am-et"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    d = datetime.fromtimestamp(s, ZoneInfo("America/New_York"))
    h = d.hour % 12 or 12
    return f"bitcoin-up-or-down-{d.strftime('%B').lower()}-{d.day}-{d.year}-{h}{'am' if d.hour < 12 else 'pm'}-et"


def slug_of(kind, s):
    if kind == "1h" and (s < 1794326400 or os.environ.get("LEGACY")):
        return legacy_slug(s)
    return f"btc-updown-{kind}-{s}"


def fetch_meta(kind, starts, mdir):
    todo = [s for s in starts if not os.path.exists(f"{mdir}/{s}.json")
            or (kind == "1h" and "missing" in open(f"{mdir}/{s}.json").read())]
    for i in range(0, len(todo), 20):
        chunk = todo[i:i + 20]
        bys = {slug_of(kind, s): s for s in chunk}
        q = "&".join(f"slug={x}" for x in bys)
        evs = get(f"{GAMMA}?{q}")
        got = set()
        for e in evs:
            s = bys[e["slug"]]
            m = e["markets"][0]
            rec = {k: m.get(k) for k in ("conditionId", "clobTokenIds", "outcomePrices",
                                         "umaResolutionStatus", "feeSchedule", "closed",
                                         "endDate", "eventStartTime", "volume")}
            rec["start"] = s
            json.dump(rec, open(f"{mdir}/{s}.json", "w"))
            got.add(s)
        for s in chunk:
            if s not in got:
                json.dump({"start": s, "missing": True}, open(f"{mdir}/{s}.json", "w"))
        print(f"[meta {kind}] {i + len(chunk)}/{len(todo)}", flush=True)


def fetch_trades(kind, s, mdir, tdir):
    out = f"{tdir}/{s}.json.gz"
    if os.path.exists(out):
        return 0
    m = json.load(open(f"{mdir}/{s}.json"))
    if m.get("missing") or not m.get("conditionId"):
        return 0
    rows, cur, n = [], None, 0
    while True:
        url = f"{DATA}?condition={m['conditionId']}&limit=1000" + (f"&cursor={cur}" if cur else "")
        d = get(url); n += 1
        for t in d["data"]:
            rows.append([t["timestamp"], t["outcome_index"], 1 if t["side"] == "BUY" else -1,
                         t["price"], t["size"], t["proxy_wallet"][-10:]])
        p = d.get("pagination") or {}
        if not p.get("has_more") or not p.get("next_cursor"):
            break
        cur = p["next_cursor"]
    tmp = out + ".tmp"
    with gzip.open(tmp, "wt") as f:
        json.dump(rows, f)
    os.replace(tmp, out)
    return n


def main():
    kind, n, outdir = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    step = STEP[kind]
    end = int(sys.argv[4]) if len(sys.argv) > 4 else (int(time.time()) // step) * step - 2 * step
    starts = [end - i * step for i in range(n)]
    mdir, tdir = f"{outdir}/{kind}/meta", f"{outdir}/{kind}/trades"
    os.makedirs(mdir, exist_ok=True); os.makedirs(tdir, exist_ok=True)
    fetch_meta(kind, starts, mdir)
    done = [0]
    def job(s):
        try:
            fetch_trades(kind, s, mdir, tdir)
        except Exception as e:
            print("ERR", s, e, flush=True)
        done[0] += 1
        if done[0] % 100 == 0:
            print(f"[trades {kind}] {done[0]}/{len(starts)}", flush=True)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(job, starts))
    print("DONE", kind, flush=True)


if __name__ == "__main__":
    main()
