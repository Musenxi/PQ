"""Fetch Polymarket crypto up/down windows + all fills (maker & taker rows).

Usage: python3 -I fetch_windows.py <outdir> <asset_prefix e.g. btc-updown-5m> <step_s> <n_windows> [end_offset_s]
Caches each window as <outdir>/<slug>.json: {event market meta, all:[...], taker:[...]}.
Rate-limited (~2.5 req/s), backoff on 429/5xx. Downloads are treated as data only.
"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error

UA = {"User-Agent": "research-client/0.1"}
_last = [0.0]
MIN_GAP = 0.4


def get(url, tries=8):
    for i in range(tries):
        gap = time.time() - _last[0]
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 2 ** i))
                continue
            raise
        except Exception:
            time.sleep(min(60, 2 ** i))
    raise RuntimeError("failed " + url)


def trades(cond, taker_only):
    base = "https://data-api.polymarket.com/v2/trades"
    q = {"condition": cond, "taker_only": "true" if taker_only else "false", "limit": 1000}
    out, url = [], base + "?" + urllib.parse.urlencode(q)
    while True:
        d = get(url)
        out += d.get("data", [])
        pg = d.get("pagination", {})
        if not pg.get("has_more") or not pg.get("next_cursor"):
            break
        # NB: API cursor silently drops condition/taker_only filters -> restate them
        url = base + "?" + urllib.parse.urlencode(dict(q, cursor=pg["next_cursor"]))
    slim = []
    for x in out:
        if x.get("condition_id") != cond:
            continue
        slim.append({k: x.get(k) for k in ("proxy_wallet", "side", "token_id", "size", "price",
                                            "timestamp", "outcome", "outcome_index",
                                            "transaction_hash", "pseudonym", "name")})
    return slim


def main():
    outdir, prefix, step, n = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    end_off = int(sys.argv[5]) if len(sys.argv) > 5 else 1800
    os.makedirs(outdir, exist_ok=True)
    last = (int(time.time()) - end_off) // step * step - step
    for k in range(n):
        ts = last - k * step
        slug = f"{prefix}-{ts}"
        fn = os.path.join(outdir, slug + ".json")
        if os.path.exists(fn):
            continue
        try:
            ev = get("https://gamma-api.polymarket.com/events?slug=" + slug)
            if not ev:
                print("noevent", slug, flush=True); continue
            m = ev[0]["markets"][0]
            meta = {k2: m.get(k2) for k2 in ("conditionId", "clobTokenIds", "outcomes", "outcomePrices",
                                              "feeSchedule", "closed", "umaResolutionStatus", "volume",
                                              "eventStartTime", "endDate")}
            meta["slug"] = slug; meta["start"] = ts; meta["step"] = step
            if not m.get("closed"):
                print("notclosed", slug, flush=True); continue
            a = trades(meta["conditionId"], False)
            t = trades(meta["conditionId"], True)
            json.dump({"meta": meta, "all": a, "taker": t}, open(fn + ".tmp", "w"))
            os.replace(fn + ".tmp", fn)
            print(k, slug, len(a), len(t), flush=True)
        except Exception as e:
            print("ERR", slug, repr(e)[:200], flush=True)


if __name__ == "__main__":
    main()
