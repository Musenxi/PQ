#!/usr/bin/env python3
"""Basket arbitrage scanner for Polymarket NegRisk multi-outcome events.

Record-only: never places orders. For every NegRisk event (a categorical
market where exactly one outcome resolves YES), it periodically fetches the
CLOB books of every outcome's YES token and computes what it would cost to
buy Q shares of EVERY outcome (walking the ask ladders, taker fees included
at each market's own feeSchedule rate). The basket pays exactly Q dollars at
resolution, so profit(Q) = Q - total_cost(Q) > 0 is a locked arbitrage on
paper. Opportunities and near misses are logged with full book detail so
frequency, size and duration can be judged from data.

Stdlib only. Env: ARB_DATA_DIR (default ./data).
"""
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_DIR = os.environ.get("ARB_DATA_DIR", "data")
SCAN_INTERVAL = 60.0        # cold scan cadence (s)
HOT_INTERVAL = 5.0          # rescan cadence for near/profitable events (s)
HOT_MARGIN = -0.25          # net profit at PRIMARY_Q above this -> hot
UNIVERSE_REFRESH = 1200.0   # re-fetch event universe every 20 min
MIN_EVENT_LIQUIDITY = 1000.0
Q_GRID = (10, 25, 50, 100, 250)
PRIMARY_Q = 25
LOG_PROFIT_FLOOR = 0.0      # log full row when profit(PRIMARY_Q) > this
LOG_SUM_CEIL = 1.0          # ... or when gross best-ask sum < this
UA = {"User-Agent": "arb-scan/1.0", "Accept-Encoding": "gzip"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def http_json(url, payload=None, timeout=20):
    data = None
    headers = dict(UA)
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return json.loads(raw)


def fetch_universe():
    """Return list of NegRisk categorical events with >=3 live binary markets."""
    events = []
    offset = 0
    while offset <= 2000:
        page = http_json(f"{GAMMA}/events?active=true&closed=false&limit=100&offset={offset}")
        if not page:
            break
        for e in page:
            if not e.get("negRisk"):
                continue
            markets = []
            liq = 0.0
            for m in e.get("markets", []):
                if not (m.get("negRisk") and m.get("active") and not m.get("closed")
                        and m.get("acceptingOrders") and m.get("enableOrderBook")):
                    continue
                try:
                    tokens = json.loads(m["clobTokenIds"])
                    outcomes = json.loads(m["outcomes"])
                except Exception:
                    continue
                if len(tokens) != 2 or outcomes != ["Yes", "No"]:
                    continue
                rate = 0.0
                if m.get("feesEnabled"):
                    rate = float((m.get("feeSchedule") or {}).get("rate", 0.07))
                try:
                    mid = float(json.loads(m["outcomePrices"])[0])
                except Exception:
                    mid = None
                markets.append({
                    "token": tokens[0],
                    "label": m.get("groupItemTitle") or m.get("question", "?"),
                    "rate": rate,
                    "mid": mid,
                })
                liq += float(m.get("liquidityClob") or 0)
            if len(markets) >= 3 and liq >= MIN_EVENT_LIQUIDITY:
                events.append({
                    "slug": e.get("slug"),
                    "title": e.get("title"),
                    "end": e.get("endDate"),
                    "liquidity": liq,
                    "markets": markets,
                })
        if len(page) < 100:
            break
        offset += 100
    return events


def fetch_books(token_ids):
    """Batch-fetch CLOB books. Returns {token_id: {'asks': [(p, s)], 'bids': [(p, s)]}}."""
    books = {}
    for i in range(0, len(token_ids), 100):
        chunk = token_ids[i:i + 100]
        payload = [{"token_id": t} for t in chunk]
        try:
            resp = http_json(f"{CLOB}/books", payload=payload)
        except Exception:
            resp = []
        for b in resp or []:
            asks = sorted(
                ((float(a["price"]), float(a["size"])) for a in b.get("asks", [])),
                key=lambda x: x[0])
            bids = sorted(
                ((float(a["price"]), float(a["size"])) for a in b.get("bids", [])),
                key=lambda x: -x[0])
            books[b.get("asset_id")] = {"asks": asks, "bids": bids}
    return books


def walk_cost(asks, rate, q):
    """Cost (incl. taker fee) to buy q shares walking the ask ladder; None if depth < q."""
    cost = 0.0
    left = q
    for p, s in asks:
        take = min(s, left)
        cost += take * p + take * rate * p * (1 - p)
        left -= take
        if left <= 1e-9:
            return cost
    return None


def walk_proceeds(bids, rate, q):
    """Net proceeds (after taker fee) from selling q shares walking the
    bid ladder; None if depth < q."""
    got = 0.0
    left = q
    for p, s in bids:
        take = min(s, left)
        got += take * p - take * rate * p * (1 - p)
        left -= take
        if left <= 1e-9:
            return got
    return None


def eval_event(ev, books):
    """Compute basket metrics for one event from fetched books."""
    legs = []
    total_depth = None
    sum_best = 0.0
    for m in ev["markets"]:
        book = books.get(m["token"])
        if not book or not book["asks"]:
            return None
        depth = sum(s for _, s in book["asks"])
        total_depth = depth if total_depth is None else min(total_depth, depth)
        sum_best += book["asks"][0][0]
        legs.append({
            "label": m["label"],
            "best_ask": book["asks"][0][0],
            "best_ask_size": book["asks"][0][1],
            "best_bid": book["bids"][0][0] if book["bids"] else None,
            "bid_depth": sum(s for _, s in book["bids"]),
            "rate": m["rate"],
            "asks": book["asks"],
            "bids": book["bids"],
        })
    profits = {}
    for q in Q_GRID:
        if total_depth is not None and total_depth < q:
            continue
        total = 0.0
        ok = True
        for leg, m in zip(legs, ev["markets"]):
            c = walk_cost(leg["asks"], m["rate"], q)
            if c is None:
                ok = False
                break
            total += c
        if ok:
            profits[q] = q - total
    # sell side: mint a full set for $1/share-set and sell every leg
    # into the bids; profit = net proceeds - q. Same exhaustiveness
    # guard as the buy side.
    profits_sell = {}
    sum_best_bids = 0.0
    bids_ok = all(l["best_bid"] is not None for l in legs)
    if bids_ok:
        sum_best_bids = sum(l["best_bid"] for l in legs)
        for q in Q_GRID:
            if any(l["bid_depth"] < q for l in legs):
                continue
            total = 0.0
            ok = True
            for leg, m in zip(legs, ev["markets"]):
                pr = walk_proceeds(leg["bids"], m["rate"], q)
                if pr is None:
                    ok = False
                    break
                total += pr
            if ok:
                profits_sell[q] = total - q
    mids = [m["mid"] for m in ev["markets"]]
    sum_mids = round(sum(mids), 4) if all(x is not None for x in mids) else None
    has_other = any("other" in (m["label"] or "").lower() for m in ev["markets"])
    # A basket is a true arbitrage only if the listed outcomes carry ~all the
    # probability mass: an explicit "Other" leg, or mid prices summing to ~1.
    # Otherwise the missing mass is an unlisted outcome that can win and pay
    # $0 on every leg (the classic NegRisk trap).
    exhaustive = bool(has_other or (sum_mids is not None and sum_mids >= 0.97))
    return {
        "sum_best_asks": round(sum_best, 4),
        "sum_mids": sum_mids,
        "has_other": has_other,
        "exhaustive": exhaustive,
        "max_shares": total_depth,
        "profits": {str(q): round(p, 4) for q, p in profits.items()},
        "sum_best_bids": round(sum_best_bids, 4) if bids_ok else None,
        "profits_sell": {str(q): round(p, 4) for q, p in profits_sell.items()},
        "legs": [{"label": l["label"], "ask": l["best_ask"], "size": l["best_ask_size"]}
                 for l in legs],
    }


def append_jsonl(name, row):
    path = os.path.join(DATA_DIR, name)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    universe = []
    universe_at = 0.0
    hot_until = {}       # slug -> hot expiry ts
    last_logged = {}     # slug -> ts of last full opportunity row
    stats = {"scans": 0, "events": 0, "books": 0, "errors": 0,
             "sums": [], "n_profit": 0, "n_near": 0, "n_trap": 0}
    stats_hour = time.time()
    print(f"[{now_iso()}] arb-scan starting", flush=True)
    while True:
        loop_start = time.time()
        try:
            if loop_start - universe_at > UNIVERSE_REFRESH or not universe:
                universe = fetch_universe()
                universe_at = loop_start
                print(f"[{now_iso()}] universe: {len(universe)} NegRisk events", flush=True)
            hot_slugs = {s for s, exp in hot_until.items() if exp > loop_start}
            # the loop ticks at HOT_INTERVAL; each event is rescanned when its
            # own per-event timer expires (HOT_INTERVAL if hot, else SCAN_INTERVAL)
            due = []
            for ev in universe:
                nxt = ev.get("_next_scan", 0.0)
                if loop_start >= nxt:
                    due.append(ev)
            if due:
                tokens = [m["token"] for ev in due for m in ev["markets"]]
                books = fetch_books(tokens)
                stats["books"] += len(tokens)
                for ev in due:
                    hot = ev["slug"] in hot_slugs
                    ev["_next_scan"] = loop_start + (HOT_INTERVAL if hot else SCAN_INTERVAL)
                    res = eval_event(ev, books)
                    if res is None:
                        continue
                    stats["events"] += 1
                    stats["sums"].append(res["sum_best_asks"])
                    p_primary = res["profits"].get(str(PRIMARY_Q))
                    if p_primary is not None and p_primary > HOT_MARGIN:
                        hot_until[ev["slug"]] = loop_start + 300
                        stats["n_near"] += 1
                    if p_primary is not None and p_primary > 0:
                        if res["exhaustive"]:
                            stats["n_profit"] += 1
                        else:
                            stats["n_trap"] += 1
                    ps_primary = res["profits_sell"].get(str(PRIMARY_Q))
                    if ps_primary is not None and ps_primary > 0 and res["exhaustive"]:
                        stats["n_profit"] += 1
                    qualifies = (p_primary is not None and p_primary > LOG_PROFIT_FLOOR) \
                        or (ps_primary is not None and ps_primary > LOG_PROFIT_FLOOR) \
                        or res["sum_best_asks"] < LOG_SUM_CEIL
                    # genuine candidates log at most every 30 s; non-exhaustive
                    # traps at most hourly (they are plentiful and slow-moving)
                    log_gap = 30 if res["exhaustive"] else 3600
                    if qualifies and loop_start - last_logged.get(ev["slug"], 0) >= log_gap:
                        last_logged[ev["slug"]] = loop_start
                        append_jsonl("opportunities.jsonl", {
                            "ts": now_iso(),
                            "event": ev["slug"],
                            "title": ev["title"],
                            "end": ev["end"],
                            "n_outcomes": len(ev["markets"]),
                            **res,
                        })
                stats["scans"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"[{now_iso()}] scan error: {type(e).__name__}: {e}", flush=True)
        if loop_start - stats_hour >= 3600:
            sums = sorted(stats["sums"])
            rollup = {
                "ts": now_iso(),
                "scans": stats["scans"],
                "event_evals": stats["events"],
                "books_fetched": stats["books"],
                "errors": stats["errors"],
                "events_profitable_q25": stats["n_profit"],
                "events_near_q25": stats["n_near"],
                "events_trap_q25": stats["n_trap"],
                "sum_best_asks_min": sums[0] if sums else None,
                "sum_best_asks_p10": sums[len(sums) // 10] if sums else None,
                "sum_best_asks_median": sums[len(sums) // 2] if sums else None,
            }
            append_jsonl("scan_stats.jsonl", rollup)
            print(f"[{now_iso()}] rollup: {json.dumps(rollup)}", flush=True)
            stats = {"scans": 0, "events": 0, "books": 0, "errors": 0,
                     "sums": [], "n_profit": 0, "n_near": 0, "n_trap": 0}
            stats_hour = loop_start
        elapsed = time.time() - loop_start
        time.sleep(max(1.0, HOT_INTERVAL - elapsed))


if __name__ == "__main__":
    main()
