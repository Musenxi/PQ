#!/usr/bin/env python3
"""Tail-end 'bonds' paper tracker for Polymarket.

Paper-only: never places orders. Strategy under test: buy the near-certain
side of a binary market when its best ask is in [0.95, 0.99], hold to
resolution, collect $1 per share. This is 'selling insurance': many small
wins, rare full-stake losses (reversals, resolution disputes). The tracker
exists to measure, after taker fees, whether the realised win rate beats
the entry prices often enough to be net positive -- and how fat the tail is.

Faithful $50 framing: a paper bankroll of $50 funds positions of $10 each
(max ~5 concurrent, lockup included). Candidates that arrive while the
bankroll is fully deployed are still recorded as SHADOW entries and settled
the same way, so the data shows both the pure per-trade edge (all entries)
and what a real $50 portfolio would have captured (funded entries only).

Entry rules (v1):
  - binary Yes/No market, live order book, not a 5-minute up/down market
  - resolution between 30 min and 60 days away at entry
  - market liquidityClob >= $2,000
  - bought side's best ask in [0.95, 0.99], $10 fillable walking the ask
    ladder with VWAP <= 0.995, fees at the market's own feeSchedule rate
  - one entry per market, ever

Settlement: poll Gamma until the market is closed with a final price of
0, 0.5 (split/disputed) or 1 for the bought token; pnl = payout - cost - fees.

Stdlib only. Env: TAIL_DATA_DIR (default ./data).
"""
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_DIR = os.environ.get("TAIL_DATA_DIR", "data")
BAND_LO, BAND_HI = 0.95, 0.99
VWAP_CAP = 0.995
STAKE = 10.0
BANKROLL = 50.0
MIN_TTE = timedelta(minutes=30)
MAX_TTE = timedelta(days=60)
MIN_LIQ = 2000.0
PREFILTER_LO, PREFILTER_HI = 0.94, 0.995
SCAN_INTERVAL = 300.0
UA = {"User-Agent": "tail-track/1.0", "Accept-Encoding": "gzip"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(msg):
    print(f"[{now_iso()}] {msg}", flush=True)


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


def append_jsonl(name, row):
    path = os.path.join(DATA_DIR, name)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


def read_jsonl(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# ---------------- universe ----------------

def fetch_candidates():
    """Gamma markets prefiltered by last price; returns candidate dicts with
    the near-certain side identified. Book truth is checked separately."""
    now = datetime.now(timezone.utc)
    cands = []
    offset = 0
    scanned = 0
    while offset <= 3000:
        try:
            page = http_json(
                f"{GAMMA}/markets?active=true&closed=false&limit=100&offset={offset}"
                f"&order=volume24hr&ascending=false")
        except Exception as e:
            log(f"universe page offset={offset} failed: {e}")
            break
        if not page:
            break
        stop = False
        for m in page:
            scanned += 1
            try:
                v24 = float(m.get("volume24hr") or 0)
            except Exception:
                v24 = 0
            if v24 < 300:
                stop = True
                continue
            if not (m.get("active") and not m.get("closed")
                    and m.get("acceptingOrders") and m.get("enableOrderBook")):
                continue
            slug = m.get("slug") or ""
            if "updown-5m" in slug:
                continue
            end = parse_ts(m.get("endDate") or "")
            if end is None:
                continue
            tte = end - now
            if tte < MIN_TTE or tte > MAX_TTE:
                continue
            try:
                liq = float(m.get("liquidityClob") or 0)
                prices = [float(x) for x in json.loads(m["outcomePrices"])]
                tokens = json.loads(m["clobTokenIds"])
                outcomes = json.loads(m["outcomes"])
            except Exception:
                continue
            if liq < MIN_LIQ or len(prices) != 2 or len(tokens) != 2 or len(outcomes) != 2:
                continue
            fs = m.get("feeSchedule") or {}
            if fs.get("rate") is not None:
                rate = float(fs["rate"])
            elif m.get("feesEnabled"):
                rate = 0.07
            else:
                rate = 0.0
            for idx in (0, 1):
                if PREFILTER_LO <= prices[idx] <= PREFILTER_HI:
                    cands.append({
                        "market_id": str(m["id"]),
                        "slug": slug,
                        "question": m.get("question"),
                        "end": m.get("endDate"),
                        "tte_hours": round(tte.total_seconds() / 3600.0, 2),
                        "side_idx": idx,
                        "side": outcomes[idx],
                        "token": tokens[idx],
                        "gamma_price": prices[idx],
                        "rate": rate,
                        "neg_risk": bool(m.get("negRisk")),
                        "liquidity": liq,
                        "volume24hr": v24,
                    })
        offset += 100
        if stop:
            break
    return cands, scanned


def fetch_books(tokens):
    books = {}
    for i in range(0, len(tokens), 100):
        batch = tokens[i:i + 100]
        try:
            resp = http_json(f"{CLOB}/books",
                             payload=[{"token_id": t} for t in batch], timeout=30)
        except Exception as e:
            log(f"books batch failed: {e}")
            continue
        for b in resp or []:
            asks = []
            for a in b.get("asks", []):
                try:
                    asks.append((float(a["price"]), float(a["size"])))
                except Exception:
                    pass
            asks.sort()
            books[b.get("asset_id")] = asks
    return books


def walk_fill(asks, dollars, rate):
    """Spend up to `dollars` walking the ask ladder. Returns dict or None if
    the ladder cannot fill >=98% of the stake."""
    if not asks:
        return None
    best = asks[0][0]
    spent = 0.0
    shares = 0.0
    fees = 0.0
    for price, size in asks:
        if spent >= dollars:
            break
        afford = (dollars - spent) / price
        take = min(size, afford)
        if take <= 0:
            continue
        spent += take * price
        shares += take
        fees += take * rate * price * (1.0 - price)
    if shares <= 0 or spent < 0.98 * dollars:
        return None
    return {"best_ask": best, "vwap": spent / shares, "shares": shares,
            "cost": spent, "fees": fees}


# ---------------- state ----------------

def load_state():
    entries = read_jsonl("entries.jsonl")
    settlements = read_jsonl("settlements.jsonl")
    settled_ids = {s["market_id"] for s in settlements}
    entered_ids = {e["market_id"] for e in entries}
    open_entries = [e for e in entries if e["market_id"] not in settled_ids]
    return entries, settlements, entered_ids, open_entries


def funded_open_cost(open_entries):
    return sum(e["cost"] for e in open_entries if e.get("funded"))


# ---------------- settlement ----------------

def check_settlements(open_entries):
    """Settle any open entries whose market has closed with a final price."""
    still_open = []
    settled_now = []
    for e in open_entries:
        final = None
        try:
            m = http_json(f"{GAMMA}/markets/{e['market_id']}", timeout=15)
            if m and m.get("closed"):
                prices = [float(x) for x in json.loads(m["outcomePrices"])]
                p = prices[e["side_idx"]]
                if abs(p) < 1e-9 or abs(p - 0.5) < 1e-9 or abs(p - 1.0) < 1e-9:
                    final = p
        except Exception as ex:
            log(f"settle check failed {e['market_id']}: {ex}")
        if final is None:
            still_open.append(e)
            continue
        payout = e["shares"] * final
        pnl = payout - e["cost"] - e["fees"]
        row = {
            "ts": now_iso(),
            "market_id": e["market_id"],
            "slug": e["slug"],
            "question": e["question"],
            "side": e["side"],
            "funded": e["funded"],
            "entry_ts": e["ts"],
            "end": e["end"],
            "vwap": e["vwap"],
            "shares": e["shares"],
            "cost": e["cost"],
            "fees": e["fees"],
            "final_price": final,
            "payout": round(payout, 4),
            "pnl": round(pnl, 4),
            "dispute_split": final == 0.5,
        }
        append_jsonl("settlements.jsonl", row)
        settled_now.append(row)
        log(f"settled {e['slug']} side={e['side']} final={final} pnl={pnl:+.2f} "
            f"funded={e['funded']}")
    return still_open, settled_now


# ---------------- main loop ----------------

def scan_cycle(entered_ids, open_entries):
    cands, scanned = fetch_candidates()
    fresh = [c for c in cands if c["market_id"] not in entered_ids]
    n_cand_seen = len(cands)
    if fresh:
        books = fetch_books([c["token"] for c in fresh])
        open_cost = funded_open_cost(open_entries)
        for c in fresh:
            asks = books.get(c["token"])
            fill = walk_fill(asks, STAKE, c["rate"]) if asks else None
            if fill is None:
                continue
            if not (BAND_LO <= fill["best_ask"] <= BAND_HI):
                continue
            if fill["vwap"] > VWAP_CAP:
                continue
            funded = (open_cost + fill["cost"]) <= BANKROLL + 1e-9
            row = {
                "ts": now_iso(),
                "market_id": c["market_id"],
                "slug": c["slug"],
                "question": c["question"],
                "side_idx": c["side_idx"],
                "side": c["side"],
                "token": c["token"],
                "end": c["end"],
                "tte_hours": c["tte_hours"],
                "best_ask": fill["best_ask"],
                "vwap": round(fill["vwap"], 4),
                "shares": round(fill["shares"], 4),
                "cost": round(fill["cost"], 4),
                "fees": round(fill["fees"], 4),
                "rate": c["rate"],
                "neg_risk": c["neg_risk"],
                "liquidity": c["liquidity"],
                "funded": funded,
            }
            append_jsonl("entries.jsonl", row)
            entered_ids.add(c["market_id"])
            open_entries.append(row)
            if funded:
                open_cost += fill["cost"]
            log(f"entry {c['slug']} side={c['side']} ask={fill['best_ask']} "
                f"vwap={fill['vwap']:.4f} shares={fill['shares']:.2f} "
                f"funded={funded} tte={c['tte_hours']}h")
    return n_cand_seen, scanned


def stats_row(settlements, open_entries, extra):
    def agg(rows):
        if not rows:
            return {"n": 0, "w": 0, "l": 0, "pnl": 0.0, "fees": 0.0, "worst": 0.0}
        pnls = [r["pnl"] for r in rows]
        return {"n": len(rows),
                "w": sum(1 for p in pnls if p > 0),
                "l": sum(1 for p in pnls if p < 0),
                "pnl": round(sum(pnls), 4),
                "fees": round(sum(r["fees"] for r in rows), 4),
                "worst": round(min(pnls), 4)}
    funded = [s for s in settlements if s.get("funded")]
    shadow = [s for s in settlements if not s.get("funded")]
    return {
        "ts": now_iso(),
        **extra,
        "open_funded": sum(1 for e in open_entries if e.get("funded")),
        "open_shadow": sum(1 for e in open_entries if not e.get("funded")),
        "open_funded_cost": round(funded_open_cost(open_entries), 2),
        "settled_funded": agg(funded),
        "settled_shadow": agg(shadow),
        "settled_all": agg(settlements),
        "disputes": sum(1 for s in settlements if s.get("dispute_split")),
    }


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    entries, settlements, entered_ids, open_entries = load_state()
    log(f"tail-track starting: {len(entries)} entries, {len(settlements)} settled, "
        f"{len(open_entries)} open (funded open cost ${funded_open_cost(open_entries):.2f})")
    stats_hour = time.time()
    cycle_stats = {"candidates_seen": 0, "markets_scanned": 0, "cycles": 0}
    while True:
        loop_start = time.time()
        try:
            open_entries, settled_now = check_settlements(open_entries)
            if settled_now:
                settlements.extend(settled_now)
            n_cand, scanned = scan_cycle(entered_ids, open_entries)
            cycle_stats["candidates_seen"] += n_cand
            cycle_stats["markets_scanned"] += scanned
            cycle_stats["cycles"] += 1
        except Exception as e:
            log(f"cycle error: {e}")
        if loop_start - stats_hour >= 3600:
            row = stats_row(settlements, open_entries, cycle_stats)
            append_jsonl("tail_stats.jsonl", row)
            log(f"stats: settled_all={row['settled_all']} funded={row['settled_funded']} "
                f"open_f={row['open_funded']} open_s={row['open_shadow']}")
            cycle_stats = {"candidates_seen": 0, "markets_scanned": 0, "cycles": 0}
            stats_hour = loop_start
        elapsed = time.time() - loop_start
        time.sleep(max(5.0, SCAN_INTERVAL - elapsed))


if __name__ == "__main__":
    main()
