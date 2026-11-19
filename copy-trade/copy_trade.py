#!/usr/bin/env python3
"""copy_trade.py -- paper mirror of viniangusso's BTC 5m buys.

Polls the public data-api v2 activity feed for one verified-profitable
wallet (see docs/x-post-viniangusso-2026-11-19.md) and paper-buys $5 of
the same side in the same market at the CURRENT CLOB ask the moment the
trade is detected. The point is to measure how much of his 3-5 pt
per-trade edge survives copy latency + market prices: every settlement
books both the mirror PnL (our ask) and a shadow PnL at his exact fill
price (the upper bound). Settlement is Gamma-official only
(umaResolutionStatus == resolved), same as the farm.

Pre-registered read: >= 1 week; report mirrored trades, mean detection
lag, mean price disadvantage vs his fills, mirror PnL vs his-price
shadow PnL. Paper only; no keys, no orders.
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

WALLET = "0x03b4c58b1bb31007cb97e2c8f2216d33c805d29c"
DATA_API = "https://data-api.polymarket.com/v2"
CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
STAKE = 5.0
POLL_S = 12
MAX_LAG_S = 290          # mirror anything detected while its window is still open;
# the public activity feed's own latency is minutes (72 of the first 74
# detections arrived > 120 s after his fill), so a tight cutoff mirrors
# almost nothing -- the line's job is to MEASURE the disadvantage, and
# lag + price_disadv are logged on every row
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def append_jsonl(name, row):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, name), "a") as f:
        f.write(json.dumps(row) + "\n")


def read_jsonl(name):
    p = os.path.join(DATA_DIR, name)
    if not os.path.exists(p):
        return []
    out = []
    for line in open(p):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def fee_rate_for(slug, cache={}):
    if slug in cache:
        return cache[slug]
    rate = 0.07
    try:
        ev = http_json(GAMMA + "/events?slug=" + slug)
        m = ev[0]["markets"][0]
        fs = m.get("feeSchedule") or {}
        if fs.get("rate") is not None:
            rate = float(fs["rate"])
    except Exception:
        pass
    cache[slug] = rate
    return rate


def book_asks(token_id):
    b = http_json(CLOB + "/book?token_id=" + token_id)
    asks = sorted(((float(a["price"]), float(a["size"])) for a in b.get("asks", [])))
    ts_ms = b.get("timestamp")
    age_ms = None
    if ts_ms:
        age_ms = int(time.time() * 1000) - int(ts_ms)
    return asks, age_ms


def walk_asks(asks, want_shares):
    got = cost = 0.0
    for price, size in asks:
        take = min(size, want_shares - got)
        got += take
        cost += take * price
        if got >= want_shares * 0.999:
            return got, cost, cost / got
    return None


def gamma_winner(slug):
    try:
        ev = http_json(GAMMA + "/events?slug=" + slug)
        m = ev[0]["markets"][0]
        if not m.get("closed") or m.get("umaResolutionStatus") != "resolved":
            return None
        prices = [float(x) for x in (json.loads(m["outcomePrices"]) if isinstance(m["outcomePrices"], str) else m["outcomePrices"])]
        outcomes = m["outcomes"]
        if isinstance(outcomes, str):
            outcomes = json.loads(outcomes)
        if max(prices) >= 0.999 and sum(prices) <= 1.001:
            return outcomes[prices.index(max(prices))]
        if abs(prices[0] - 0.5) < 1e-9 and abs(prices[1] - 0.5) < 1e-9:
            return "Split"
    except Exception:
        pass
    return None


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    state_path = os.path.join(DATA_DIR, "copy_state.json")
    state = {"seen": [], "open": []}
    if os.path.exists(state_path):
        try:
            state = json.load(open(state_path))
        except Exception:
            pass
    seen = set(state.get("seen", []))
    open_pos = state.get("open", [])
    seeded = bool(seen)
    print("[copy] up; seeded=%s open=%d seen=%d" % (seeded, len(open_pos), len(seen)), flush=True)

    def save():
        state["seen"] = sorted(seen)[-6000:]
        state["open"] = open_pos
        with open(state_path, "w") as f:
            json.dump(state, f)

    while True:
        # --- settlements ---
        still_open = []
        for pos in open_pos:
            w = gamma_winner(pos["slug"])
            if w is None:
                still_open.append(pos)
                continue
            pay = pos["shares"] if w == pos["side"] else (0.5 * pos["shares"] if w == "Split" else 0.0)
            pnl = pay - pos["cost"] - pos["fees"]
            pay_h = pos["shares_his"] if w == pos["side"] else (0.5 * pos["shares_his"] if w == "Split" else 0.0)
            pnl_his = pay_h - STAKE - pos["shares_his"] * 0.07 * pos["his_price"] * (1 - pos["his_price"])
            append_jsonl("copy_settlements.jsonl",
                         {"slug": pos["slug"], "side": pos["side"], "winner": w,
                          "our_price": pos["price"], "his_price": pos["his_price"],
                          "lag_s": pos["lag_s"], "pnl": round(pnl, 4),
                          "pnl_his_price": round(pnl_his, 4),
                          "settled_at": now_iso()})
            print("[copy] settled %s %s winner=%s pnl=%+.2f (his-price %+.2f)"
                  % (pos["slug"], pos["side"], w, pnl, pnl_his), flush=True)
        if len(still_open) != len(open_pos):
            open_pos = still_open
            save()

        # --- poll his activity ---
        try:
            page = http_json(DATA_API + "/activity?user=" + WALLET + "&limit=100")
            rows = page.get("data", page if isinstance(page, list) else [])
        except Exception as e:
            print("[copy] activity poll failed:", repr(e), flush=True)
            rows = []
        new_seen = False
        for r in reversed(rows):
            if r.get("type") != "TRADE" or r.get("side") != "BUY":
                continue
            key = (r.get("transaction_hash") or "") + ":" + (r.get("token_id") or r.get("asset") or "") + ":" + str(r.get("timestamp"))
            if key in seen:
                continue
            seen.add(key)
            new_seen = True
            if not seeded:
                continue  # first poll only seeds the seen set
            slug = r.get("slug") or r.get("event_slug") or ""
            if "btc-updown-5m" not in slug:
                continue
            his_ts = float(r.get("timestamp") or 0)
            lag = time.time() - his_ts
            side = r.get("outcome") or ""
            his_price = float(r.get("price") or 0)
            row = {"ts": now_iso(), "slug": slug, "side": side,
                   "his_price": his_price, "his_usdc": r.get("usdc_size"),
                   "lag_s": round(lag, 1), "disposition": None}
            start = int(slug.rsplit("-", 1)[1])
            if lag > MAX_LAG_S or time.time() > start + 300:
                row["disposition"] = "skipped_late"
                append_jsonl("copy_trades.jsonl", row)
                continue
            try:
                asks, age_ms = book_asks(r.get("token_id") or r.get("asset"))
            except Exception as e:
                row["disposition"] = "book_fail"
                append_jsonl("copy_trades.jsonl", row)
                continue
            if not asks:
                row["disposition"] = "no_asks"
                append_jsonl("copy_trades.jsonl", row)
                continue
            want = STAKE / asks[0][0]
            fill = walk_asks(asks, want)
            if fill is None:
                row["disposition"] = "thin_book"
                append_jsonl("copy_trades.jsonl", row)
                continue
            shares, cost, vwap = fill
            rate = fee_rate_for(slug)
            fees = shares * rate * vwap * (1 - vwap)
            row.update({"disposition": "mirrored", "our_price": round(vwap, 4),
                        "shares": round(shares, 3), "cost": round(cost, 4),
                        "fees": round(fees, 4), "book_age_ms": age_ms,
                        "price_disadv": round(vwap - his_price, 4)})
            append_jsonl("copy_trades.jsonl", row)
            open_pos.append({"slug": slug, "side": side, "shares": shares,
                             "cost": cost, "fees": fees, "price": vwap,
                             "his_price": his_price,
                             "shares_his": STAKE / his_price if his_price else 0.0,
                             "lag_s": round(lag, 1)})
            print("[copy] mirror %s %s his=%.3f our=%.3f lag=%.0fs"
                  % (slug, side, his_price, vwap, lag), flush=True)
        if not seeded:
            seeded = True
            print("[copy] seeded seen set with %d keys" % len(seen), flush=True)
        if new_seen:
            save()
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
