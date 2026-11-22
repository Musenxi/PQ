"""Per-window order-flow snapshot for BTC updown markets (added
2026-11-22 at lizi's instruction): after each window closes, pull the
full public trade tape for both tokens from the data-api (v2) and
split the flow into market-maker-like flow (wallets buying BOTH sides
in roughly balanced dollars) and DIRECTIONAL flow (everyone else).
The directional net flow per side is an information source the fair
model has never had; snapshots accumulate next to the deep recorder
as features for the model retrain (~2026-12-03). Read-only; touches
no strategy.

Output: data/flow-YYYY-MM-DD.jsonl (UTC), one row per window:
  {slug, start, mins, pulled_at, trades,
   raw:  {Up: {buy, sell}, Down: {buy, sell}},          # USD, all wallets
   mm_usd,                                             # two-sided buy USD
   dir:  {Up: {buy, sell, net, wallets}, Down: {...}}} # non-MM wallets
"""
import json
import os
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
STATE = os.path.join(HERE, "flow_state.json")
GAMMA = "https://gamma-api.polymarket.com"
API = "https://data-api.polymarket.com/v2"
ASSETS = [("btc", 5), ("btc", 60)]  # (symbol, window minutes)


def http_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "flow-snap/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def tape(token_id):
    rows, cursor, pages = [], None, 0
    while pages < 60:
        url = f"{API}/trades?token_id={token_id}&limit=500"
        if cursor:
            url += f"&cursor={cursor}"
        r = http_json(url)
        rows += r.get("data", [])
        cursor = (r.get("pagination") or {}).get("next_cursor")
        pages += 1
        if not cursor:
            break
        time.sleep(0.15)
    return rows


def snapshot(slug):
    ev = http_json(f"{GAMMA}/events?slug={slug}")
    m = ev[0]["markets"][0]
    toks = json.loads(m["clobTokenIds"])
    per_wallet = defaultdict(lambda: defaultdict(float))
    raw = {"Up": {"buy": 0.0, "sell": 0.0}, "Down": {"buy": 0.0, "sell": 0.0}}
    n = 0
    for i, tok in enumerate(toks):
        side = "Up" if i == 0 else "Down"
        for t in tape(tok):
            usd = float(t["size"]) * float(t["price"])
            kind = "buy" if t["side"] == "BUY" else "sell"
            raw[side][kind] += usd
            per_wallet[t["proxy_wallet"]][(side, kind)] += usd
            n += 1
    mm_usd = 0.0
    direction = {"Up": {"buy": 0.0, "sell": 0.0, "wallets": 0},
                 "Down": {"buy": 0.0, "sell": 0.0, "wallets": 0}}
    for w, d in per_wallet.items():
        bu, bd = d[("Up", "buy")], d[("Down", "buy")]
        two_sided = bu + bd >= 50 and min(bu, bd) >= 0.4 * max(bu, bd, 1e-9)
        if two_sided:
            mm_usd += bu + bd
            continue
        for side in ("Up", "Down"):
            b, s = d[(side, "buy")], d[(side, "sell")]
            direction[side]["buy"] += b
            direction[side]["sell"] += s
            if b or s:
                direction[side]["wallets"] += 1
    for side in ("Up", "Down"):
        direction[side]["net"] = direction[side]["buy"] - direction[side]["sell"]
        for k in ("buy", "sell", "net"):
            direction[side][k] = round(direction[side][k], 2)
        for k in ("buy", "sell"):
            raw[side][k] = round(raw[side][k], 2)
    return {"slug": slug, "trades": n, "raw": raw,
            "mm_usd": round(mm_usd, 2), "dir": direction,
            "pulled_at": datetime.now(timezone.utc).isoformat()}


def main():
    os.makedirs(DATA, exist_ok=True)
    done = set()
    if os.path.exists(STATE):
        done = set(json.load(open(STATE)).get("done", []))
    print("[flow] snapshotter up", flush=True)
    while True:
        try:
            now = int(time.time())
            for sym, mins in ASSETS:
                span = mins * 60
                # windows that ended 60-900 s ago
                last_end = now - (now % span)
                for end in (last_end, last_end - span):
                    start = end - span
                    if not (60 <= now - end <= 900):
                        continue
                    slug = f"{sym}-updown-{mins}m-{start}" if mins == 5 \
                        else f"{sym}-updown-1h-{start}"
                    if slug in done:
                        continue
                    row = snapshot(slug)
                    row["start"] = start
                    row["mins"] = mins
                    day = datetime.fromtimestamp(now, timezone.utc) \
                        .strftime("%Y-%m-%d")
                    with open(os.path.join(DATA, f"flow-{day}.jsonl"),
                              "a") as f:
                        f.write(json.dumps(row) + "\n")
                    done.add(slug)
                    print(f"[flow] {slug} trades={row['trades']} "
                          f"dir_net Up {row['dir']['Up']['net']:+.0f} / "
                          f"Down {row['dir']['Down']['net']:+.0f} "
                          f"mm ${row['mm_usd']:.0f}", flush=True)
            json.dump({"done": sorted(done)[-400:]}, open(STATE, "w"))
        except Exception as e:
            print("[flow] error:", e, flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
