#!/usr/bin/env python3
"""1h probe: FAIR-only shadow farm for Polymarket BTC 1h up/down (PAPER ONLY).

Fork of farm.py v2.0.1 (same execution model, same book-freshness
instrumentation: every fill logs book_age_ms / book_hash / would_reject),
re-pointed at the hourly market (btc-updown-1h-<hour start>), which also
settles on the Chainlink TWAP-60 stream (crypto-price variant=hourly;
winner = Up iff close >= open; cross-verified vs Gamma/CLOB outcomes
2026-11-19).

Why: from 2026-11-21 08:59 JST the 1h market's taker feeRate drops
0.07 -> 0.01 (the 5m/15m markets only drop to 0.05), cutting fee drag
~7x. The probe tests whether the book lags a Binance-based TWAP-aware
fair value at the 1h horizon by more than the (now small) fee.

12 accounts, one family (FAIR): gap {0.03, 0.06, 0.10} x tau_min
{300, 900} (remaining-seconds floor; both bind at this duration) x band
{(0.15, 0.92), (0.30, 0.80)}. $50 paper bankroll, $5 stake each.
Read criteria are pre-registered in docs/probe-1h-2026-11-19.md:
family x window accounting via farm_report.py, block-bootstrap CI,
fresh/stale split via fair_booksplit.py, >= 1 week and >= 100 windows.
"""
import argparse
import ast
import json
import math
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("FARM_DATA_DIR") or os.path.join(HERE, "data")

BINANCE = "https://data-api.binance.vision"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
PM_WEB = "https://polymarket.com"
UA = {"User-Agent": "Mozilla/5.0 (paper-farm)"}
STAKE = 5.0
START_CASH = 50.0
# UNLIMITED_CASH (lizi, 2026-11-19): paper accounts never bust --
# the bankroll gate is off so every family keeps collecting data;
# cash/pnl accounting is unchanged (cash may go negative).
UNLIMITED_CASH = True


def http_json(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p):
    """Inverse normal CDF (Acklam's approximation, |err| < 1.2e-9)."""
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285984469534e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def fee_for(shares, price, rate=0.07):
    return shares * rate * price * (1.0 - price)


def best_levels(book):
    bids = [(float(b["price"]), float(b["size"])) for b in book.get("bids", [])]
    asks = [(float(a["price"]), float(a["size"])) for a in book.get("asks", [])]
    best_bid = max(bids) if bids else (None, 0.0)
    best_ask = min(asks) if asks else (None, 0.0)
    return best_bid, best_ask


def sorted_levels(book):
    bids = sorted(((float(b["price"]), float(b["size"])) for b in book.get("bids", [])),
                  key=lambda x: -x[0])
    asks = sorted(((float(a["price"]), float(a["size"])) for a in book.get("asks", [])),
                  key=lambda x: x[0])
    return bids, asks


def walk_asks(levels, want_shares):
    """Fill want_shares walking ask levels -> (shares, cost, vwap, n_levels);
    None when visible depth covers < 99% of the order."""
    got = cost = 0.0
    n = 0
    for p, s in levels:
        if got >= want_shares:
            break
        take = min(s, want_shares - got)
        got += take
        cost += take * p
        n += 1
    if got < want_shares * 0.99:
        return None
    return got, cost, cost / got if got else 0.0, n


def walk_bids(levels, have_shares):
    """Sell have_shares walking bid levels -> (proceeds, vwap, n_levels);
    None when visible depth covers < 99% of the position."""
    sold = proceeds = 0.0
    n = 0
    for p, s in levels:
        if sold >= have_shares:
            break
        take = min(s, have_shares - sold)
        sold += take
        proceeds += take * p
        n += 1
    if sold < have_shares * 0.99:
        return None
    return proceeds, proceeds / sold if sold else 0.0, n


def append_jsonl(name, row):
    with open(os.path.join(DATA, name), "a") as f:
        f.write(json.dumps(row) + "\n")


def read_jsonl(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


FARM_VERSION = "1h-0.1"
STALE_BOOK_MS = 1000        # v2.1 filter threshold (audit 2026-11-19)
FUTURE_BOOK_MS = -2000      # or future-dated beyond plausible clock skew
# v2.0.1 (deployed 2026-11-19, RECORD-ONLY observation build): books carry
# the CLOB server timestamp/hash; every fill logs book_age_ms (fill tick),
# dec_book_age_ms (decision tick) and would_reject = whether the v2.1
# filter would have refused that fill (either book stale by the thresholds
# above). Behaviour is UNCHANGED for books: nothing is filtered, so the
# next 24h of run2 data can be split fresh vs would-reject for attribution.
# state.json carries the all-tick book-age histogram + hash-repeat count,
# which is what tests whether the timestamp field measures staleness at
# all. Two behaviour changes DO ride along (both FAIR-irrelevant):
# execute_buy no longer band-checks leg-2 pair fills (v1 behaviour; the
# pair_cost gate is the leg-2 control) -- SNIPE data starts a new segment
# at this deployment -- and trade rows log wait_s/attempts (time from the
# FIRST decision attempt to fill, not just the last). The filtering build
# is farm_v2_1.py; whether/when it deploys is pre-registered in
# docs/audit-2026-11-19.md (24h decision rule).


def would_reject_age(age_ms):
    """Would the v2.1 filter refuse a book of this age?"""
    return age_ms is None or age_ms > STALE_BOOK_MS or age_ms < FUTURE_BOOK_MS


def age_bucket(age_ms):
    if age_ms is None:
        return "missing"
    if age_ms < 0:
        return "neg"
    for hi, name in ((100, "0_100"), (250, "100_250"), (500, "250_500"),
                     (1000, "500_1000"), (2000, "1000_2000"),
                     (5000, "2000_5000")):
        if age_ms < hi:
            return name
    return "gt5000"
ENTRY_DELAY_S = 60  # fair-anchored families may not enter in a window's first seconds


# ---------------------------------------------------------------- accounts
def build_configs():
    cfgs = []
    n = 0
    for gap in (0.03, 0.06, 0.10):
        for tau_min in (300, 900):
            for band in ((0.15, 0.92), (0.30, 0.80)):
                n += 1
                cfgs.append({"id": f"fair-{n:02d}", "family": "FAIR", "gap": gap,
                             "tau_min": tau_min, "band": band})
    # LATE (added 2026-11-19 at lizi's instruction): cross-window /
    # late-hour certainty. Only in the last tau_max seconds of the
    # hour, only on the side whose TWAP path margin is already
    # margin_z sigma (z recovered from the model fair), and only when
    # the thin 1h book still prices that side at least `gap` below
    # fair. Read with the 1h probe's post-fee-flip criteria, reported
    # as its own family.
    n = 0
    for margin_z in (2.0, 3.0):
        for gap in (0.03, 0.05):
            for band in ((0.15, 0.92), (0.30, 0.80)):
                n += 1
                cfgs.append({"id": f"late-{n:02d}", "family": "LATE",
                             "margin_z": margin_z, "gap": gap, "band": band,
                             "tau_max": 600})
    return cfgs


class Account:
    def __init__(self, cfg):
        self.cfg = cfg
        self.id = cfg["id"]
        self.cash = START_CASH
        self.pos = {}            # side -> {shares, cost, fees, price}
        self.entered = False     # leg-1 done for the live window
        self.entry_ts = None
        self.order = None        # queued order (v2 execution model)
        self.first_try = None    # ts of first decision attempt for the
        self.tries = 0           # pending buy; wait_s measures from here
        self.exited = False
        self.trades = 0
        self.settled = 0
        self.wins = 0
        self.pnl = 0.0

    @property
    def alive(self):
        return True if UNLIMITED_CASH else self.cash >= 1.0

    def snapshot(self):
        return {"cash": round(self.cash, 2), "pnl": round(self.pnl, 2),
                "trades": self.trades, "settled": self.settled,
                "wins": self.wins, "alive": self.alive,
                "in_pos": bool(self.pos)}


# ------------------------------------------------------------------- window
class Window:
    def __init__(self, start_ts):
        self.start = start_ts
        self.end = start_ts + 3600
        self.slug = f"btc-updown-1h-{start_ts}"
        self.token = {}
        self.open_price = None
        self.fee_rate = 0.07
        self.basis = None
        self.basis_sampled = False
        self.loaded = False

    def load(self):
        ev = http_json(f"{GAMMA}/events?slug={self.slug}")
        if not ev:
            return False
        m = ev[0]["markets"][0]
        toks = ast.literal_eval(m["clobTokenIds"])
        outs = ast.literal_eval(m["outcomes"])
        self.token = dict(zip(outs, toks))
        fs = m.get("feeSchedule") or {}
        if fs.get("rate"):
            self.fee_rate = float(fs["rate"])
        cp = http_json(f"{PM_WEB}/api/crypto/crypto-price?" + urllib.parse.urlencode(
            {"symbol": "BTC", "variant": "hourly", "eventStartTime": self.start}))
        if cp.get("openPrice"):
            self.open_price = float(cp["openPrice"])
        # a window counts as loaded only once its open price exists: at the
        # rollover instant the price API can briefly answer without one,
        # and marking loaded then would dead-end the whole window
        self.loaded = self.open_price is not None
        return self.loaded

    def settlement(self):
        # Winner from the OFFICIAL resolution (Gamma outcomePrices),
        # same fix as the 5m farm: the crypto-price close print's
        # sign disagreed with the official resolution on 2 of this
        # probe's first 7 hourly windows (both near-ties). The print
        # is fetched only to record open/close; a 0.5/0.5 split
        # falls back to the crypto-price sign, as before.
        try:
            ev = http_json(f"{GAMMA}/events?slug={self.slug}")
        except Exception:
            return None
        if not ev:
            return None
        m = ev[0]["markets"][0]
        if not m.get("closed") or not m.get("outcomePrices"):
            return None
        # outcomePrices are provisional during the UMA proposal
        # window; book only once the resolution is final
        _st = m.get("umaResolutionStatus")
        if _st and _st != "resolved":
            return None
        outs = ast.literal_eval(m["outcomes"])
        prices = [float(x) for x in ast.literal_eval(m["outcomePrices"])]
        cp = {}
        try:
            cp = http_json(f"{PM_WEB}/api/crypto/crypto-price?" + urllib.parse.urlencode(
                {"symbol": "BTC", "variant": "hourly", "eventStartTime": self.start}))
        except Exception:
            pass
        op = float(cp["openPrice"]) if cp.get("openPrice") is not None else None
        cl = float(cp["closePrice"]) if cp.get("closePrice") is not None else None
        if max(prices) >= 0.999 and sum(prices) <= 1.001:
            return outs[prices.index(max(prices))], op, cl
        if cp.get("completed") and cp.get("closePrice") is not None:
            winner = "Up" if float(cp["closePrice"]) >= float(cp["openPrice"]) else "Down"
            return winner, op, cl
        return None


# --------------------------------------------------------------------- feed
def parse_endpoint(spec):
    spec = spec.strip()
    if spec.startswith("["):
        host, _, rest = spec[1:].partition("]")
        return host, int(rest.lstrip(":") or 8765)
    host, _, port = spec.partition(":")
    return host, int(port or 8765)


class FeedClient:
    """binance_feed.py over TCP; samples stamped at local receipt."""

    def __init__(self, spec, token=None):
        self.addrs = [parse_endpoint(s) for s in spec.split(",") if s.strip()]
        self.token = token
        self.lock = threading.Lock()
        self.pending = []
        self.latest = None

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        idx = 0
        while True:
            addr = self.addrs[idx % len(self.addrs)]
            try:
                with socket.create_connection(addr, timeout=10) as s:
                    s.settimeout(20)
                    if self.token:
                        s.sendall(f"AUTH {self.token}\n".encode())
                    buf = b""
                    while True:
                        chunk = s.recv(65536)
                        if not chunk:
                            raise ConnectionError("feed closed")
                        buf += chunk
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            if not line.strip():
                                continue
                            try:
                                d = json.loads(line)
                            except Exception:
                                continue
                            if "p" not in d:
                                continue
                            recv = time.time()
                            with self.lock:
                                self.pending.append((recv, float(d["p"])))
                                self.latest = (recv, float(d["p"]), float(d.get("ts") or recv))
            except Exception:
                pass
            idx += 1
            time.sleep(1.0)

    def drain(self):
        with self.lock:
            out, self.pending = self.pending, []
            return out

    def fresh_latest(self, max_age=2.5):
        with self.lock:
            if self.latest and time.time() - self.latest[0] <= max_age:
                return self.latest
            return None


# ------------------------------------------------------------------ signals
def price_at(prices, t):
    """Last sampled price at or before time t (deque of (ts, price))."""
    out = None
    for ts, p in prices:
        if ts <= t:
            out = p
        else:
            break
    return out


def acvr_stats(prices, lookback=180):
    """Lag-1 autocorrelation + Lo-MacKinlay VR(5) on 1s log returns, plus
    the direction of the last 5 seconds. Same maths as acvr_paper.py."""
    if not prices:
        return None, None, None
    grid = {}
    for t, p in prices:
        grid[int(t)] = p
    if len(grid) < lookback + 10:
        return None, None, None
    secs = sorted(grid)[-(lookback + 1):]
    series = []
    last = None
    for s in range(secs[0], secs[-1] + 1):
        if s in grid:
            last = grid[s]
        if last is not None:
            series.append(last)
    if len(series) < lookback + 1:
        return None, None, None
    series = series[-(lookback + 1):]
    rets = [math.log(series[i] / series[i - 1]) for i in range(1, len(series))]
    n = len(rets)
    mean = sum(rets) / n
    var1 = sum((r - mean) ** 2 for r in rets) / n
    if var1 <= 0:
        return None, None, None
    rho = sum((rets[i] - mean) * (rets[i - 1] - mean) for i in range(1, n)) / (n * var1)
    q = 5
    rq = [sum(rets[i:i + q]) for i in range(0, n - q + 1)]
    mq = sum(rq) / len(rq)
    varq = sum((r - mq) ** 2 for r in rq) / len(rq)
    vr = varq / (q * var1)
    last_move = series[-1] - series[-6] if len(series) >= 6 else 0.0
    if last_move == 0:
        return rho, vr, None
    return rho, vr, ("Up" if last_move > 0 else "Down")


# ------------------------------------------------------------------ recovery
def recover(accounts):
    """Rebuild cash/stats from logs; settle or restore open positions."""
    by_id = {a.id: a for a in accounts}
    settled_keys = set()
    for row in read_jsonl("settlements.jsonl"):
        a = by_id.get(row.get("account"))
        if not a:
            continue
        settled_keys.add((a.id, row["slug"]))
        a.settled += 1
        a.pnl += float(row.get("pnl", 0))
        if float(row.get("pnl", 0)) > 0:
            a.wins += 1
    open_pos = {}
    trades = read_jsonl("trades.jsonl")
    for a in accounts:
        a.trades = sum(1 for t in trades if t.get("account") == a.id)
    for t in trades:
        key = (t.get("account"), t.get("slug"))
        if key in settled_keys or t.get("account") not in by_id:
            continue
        open_pos.setdefault(key, []).append(t)
    now = time.time()
    restored = {}
    for (aid, slug), rows in sorted(open_pos.items()):
        a = by_id[aid]
        start = int(slug.rsplit("-", 1)[1])
        exits = [t for t in rows if t.get("leg") == "exit"]
        if exits:
            e, b = exits[0], rows[0]
            pnl = float(e["proceeds"]) - float(e["fees"]) - float(b["cost"]) - float(b["fees"])
            append_jsonl("settlements.jsonl",
                         {"account": aid, "slug": slug, "winner": None, "exited": True,
                          "recovered": True, "pnl": round(pnl, 4),
                          "settled_at": datetime.now(timezone.utc).isoformat()})
            a.settled += 1
            a.pnl += pnl
            if pnl > 0:
                a.wins += 1
            settled_keys.add((aid, slug))
            print(f"[recover] {aid} {slug} rebuilt exit pnl={pnl:+.2f}", flush=True)
            continue
        pos = {}
        for t in rows:
            if t.get("leg") in (1, 2):
                pos[t["side"]] = {"shares": float(t["shares"]), "cost": float(t["cost"]),
                                  "fees": float(t["fees"]), "price": float(t["price"])}
        if not pos:
            continue
        ets = None
        leg1 = [t for t in rows if t.get("leg") == 1]
        if leg1:
            try:
                ets = datetime.fromisoformat(leg1[0]["ts"]).timestamp()
            except Exception:
                ets = None
        if start + 3600 > now:
            restored[aid] = (slug, pos, ets)  # window still live; hand back below
        else:
            w = Window(start)
            try:
                s = w.settlement()
            except Exception:
                s = None
            if s:
                winner = s[0]
                payout = pos.get(winner, {}).get("shares", 0.0)
                pnl = payout - sum(p["cost"] + p["fees"] for p in pos.values())
                append_jsonl("settlements.jsonl",
                             {"account": aid, "slug": slug, "winner": winner,
                              "paired": len(pos) == 2, "recovered": True,
                              "pnl": round(pnl, 4),
                              "settled_at": datetime.now(timezone.utc).isoformat()})
                a.settled += 1
                a.pnl += pnl
                if pnl > 0:
                    a.wins += 1
                settled_keys.add((aid, slug))
                print(f"[recover] {aid} {slug} settled pnl={pnl:+.2f}", flush=True)
            else:
                restored[aid] = (slug, pos, ets)  # settle later via pending queue
    for a in accounts:
        open_cost = 0.0
        for t in trades:
            if t.get("account") == a.id and (a.id, t.get("slug")) not in settled_keys \
                    and t.get("leg") in (1, 2):
                open_cost += float(t["cost"]) + float(t["fees"])
        a.cash = START_CASH + a.pnl - open_cost
    return restored


# ------------------------------------------------------------------- engine
def queue_order(a, kind, side, ctx, extra=None, shares_fixed=None):
    """Queue an order on the decision tick; it fills on a LATER tick against
    that tick's book (one-tick execution delay, v2 execution model)."""
    if a.order is not None:
        return False
    dec_meta = (ctx.get("book_meta") or {}).get(side) or {}
    a.order = {"kind": kind, "side": side, "slug": ctx["slug"],
               "queued_at": ctx["now"], "extra": extra or {},
               "shares_fixed": shares_fixed,
               "dec_age_ms": dec_meta.get("age_ms"),
               "dec_hash": dec_meta.get("hash")}
    if kind in ("buy1", "buy2"):
        if a.first_try is None:
            a.first_try = ctx["now"]
            a.tries = 0
        a.tries += 1
    if kind == "buy1":
        a.entered = True
    return True


def execute_buy(a, win, side, leg, ctx, order):
    """Fill a queued buy walking the current ask depth at VWAP."""
    levels = ctx["levels"][side]["asks"]
    if not levels:
        return False
    want = order["shares_fixed"] if order["shares_fixed"] else STAKE / levels[0][0]
    fill = walk_asks(levels, want)
    if fill is None:
        return False
    shares, cost, vwap, nlev = fill
    band = a.cfg.get("band")
    if leg == 1 and band and not (band[0] <= vwap <= band[1]):
        return False
    if leg == 2:
        held = next(iter(a.pos))
        pair_cost = a.pos[held]["price"] + vwap + fee_for(1, vwap, win.fee_rate)
        if pair_cost >= a.cfg["pair_max"]:
            return False
    fees = fee_for(shares, vwap, win.fee_rate)
    if not UNLIMITED_CASH and a.cash < cost + fees:
        return False
    a.cash -= cost + fees
    a.pos[side] = {"shares": shares, "cost": cost, "fees": fees, "price": vwap}
    a.trades += 1
    if leg == 1:
        a.entry_ts = ctx["now"]
    meta = (ctx.get("book_meta") or {}).get(side) or {}
    row = {"account": a.id, "family": a.cfg["family"],
           "ts": datetime.now(timezone.utc).isoformat(), "slug": win.slug,
           "leg": leg, "side": side, "price": round(vwap, 4),
           "shares": round(shares, 3), "cost": round(cost, 4),
           "fees": round(fees, 4),
           "fill_delay_s": round(ctx["now"] - order["queued_at"], 1),
           "wait_s": round(ctx["now"] - a.first_try, 1) if a.first_try else None,
           "attempts": a.tries,
           "book_age_ms": meta.get("age_ms"), "book_hash": meta.get("hash"),
           "dec_book_age_ms": order.get("dec_age_ms"),
           "would_reject": bool(would_reject_age(meta.get("age_ms"))
                                or would_reject_age(order.get("dec_age_ms"))),
           "levels": nlev}
    row.update(order["extra"])
    a.first_try = None
    a.tries = 0
    append_jsonl("trades.jsonl", row)
    print(f"[trade] {a.id} {'BUY' if leg == 1 else 'PAIR'} {side} @ {vwap:.3f} "
          f"cash={a.cash:.2f} {win.slug}", flush=True)
    return True


def execute_exit(a, win, ctx, order):
    """Fill a queued exit walking the current bid depth at VWAP; if the bid
    side cannot absorb the position, stay in (retried on later ticks)."""
    held = order["side"]
    if held not in a.pos:
        return
    p = a.pos[held]
    fill = walk_bids(ctx["levels"][held]["bids"], p["shares"])
    if fill is None:
        return
    proceeds, vwap, nlev = fill
    sfee = fee_for(p["shares"], vwap, win.fee_rate)
    pnl = proceeds - sfee - p["cost"] - p["fees"]
    a.cash += proceeds - sfee
    emeta = (ctx.get("book_meta") or {}).get(held) or {}
    append_jsonl("trades.jsonl",
                 {"account": a.id, "family": "SNIPE",
                  "ts": datetime.now(timezone.utc).isoformat(),
                  "slug": win.slug, "leg": "exit", "side": held,
                  "price": round(vwap, 4), "shares": round(p["shares"], 3),
                  "proceeds": round(proceeds, 4), "fees": round(sfee, 4),
                  "book_age_ms": emeta.get("age_ms"),
                  "book_hash": emeta.get("hash"),
                  "dec_book_age_ms": order.get("dec_age_ms"),
                  "would_reject": bool(would_reject_age(emeta.get("age_ms"))
                                       or would_reject_age(order.get("dec_age_ms"))),
                  "levels": nlev})
    a.trades += 1
    a.settled += 1
    a.pnl += pnl
    if pnl > 0:
        a.wins += 1
    append_jsonl("settlements.jsonl",
                 {"account": a.id, "slug": win.slug, "winner": None,
                  "exited": True, "exit_price": round(vwap, 4), "pnl": round(pnl, 4),
                  "cash_after": round(a.cash, 2),
                  "settled_at": datetime.now(timezone.utc).isoformat()})
    print(f"[trade] {a.id} EXIT {held} @ {vwap:.3f} pnl={pnl:+.2f} {win.slug}",
          flush=True)
    a.pos = {}
    a.exited = True


def process_order(a, win, ctx):
    o = a.order
    if o is None:
        return
    a.order = None
    if o["slug"] != win.slug:
        if o["kind"] == "buy1":
            a.entered = False
        return
    if o["kind"] == "exit":
        execute_exit(a, win, ctx, o)
    elif o["kind"] == "buy1":
        if not execute_buy(a, win, o["side"], 1, ctx, o):
            a.entered = False  # unfilled/cancelled; may re-decide later
    else:
        execute_buy(a, win, o["side"], 2, ctx, o)




def account_tick(a, win, ctx):
    cfg = a.cfg
    fam = cfg["family"]
    tau = ctx["tau"]
    books = ctx["books"]
    if a.order is not None:
        process_order(a, win, ctx)
    if fam == "SNIPE":
        snipe_tick(a, win, ctx)
        return
    if a.pos or a.entered or not a.alive or tau < 5:
        return
    side = None
    extra = {}
    if fam in ("MOM", "REV"):
        if not (cfg["tau_lo"] <= tau <= cfg["tau_hi"]):
            return
        mv = ctx["moves"].get(cfg["lookback"])
        if mv is None or abs(mv) < cfg["thr"]:
            return
        side = "Up" if mv > 0 else "Down"
        if fam == "REV":
            side = "Down" if side == "Up" else "Up"
        extra = {"move": round(mv, 1), "lookback": cfg["lookback"]}
    elif fam == "FAIR":
        if ctx.get("basis") is None or ctx["now"] - win.start < ENTRY_DELAY_S:
            return
        if tau < cfg["tau_min"]:
            return
        best_gap = None
        for s in ("Up", "Down"):
            ask = books[s][1][0]
            if ask is None or not (cfg["band"][0] <= ask <= cfg["band"][1]):
                continue
            gap = ctx["fairs"][s] - ask
            if best_gap is None or gap > best_gap[0]:
                best_gap = (gap, s)
        if not best_gap or best_gap[0] < cfg["gap"]:
            return
        side = best_gap[1]
        extra = {"gap": round(best_gap[0], 3), "fair": round(ctx["fairs"][side], 3),
                 "basis": round(ctx["basis"], 1)}
    elif fam == "LATE":
        if ctx.get("basis") is None or ctx["now"] - win.start < ENTRY_DELAY_S:
            return
        if tau > cfg["tau_max"]:
            return
        best_gap = None
        for s in ("Up", "Down"):
            ask = books[s][1][0]
            if ask is None or not (cfg["band"][0] <= ask <= cfg["band"][1]):
                continue
            f = ctx["fairs"][s]
            if f is None:
                continue
            z = norm_ppf(f)
            gap = f - ask
            if z >= cfg["margin_z"] and gap >= cfg["gap"]:
                if best_gap is None or gap > best_gap[0]:
                    best_gap = (gap, s, z)
        if not best_gap:
            return
        side = best_gap[1]
        extra = {"gap": round(best_gap[0], 3), "fair": round(ctx["fairs"][side], 3),
                 "margin_z": round(best_gap[2], 2),
                 "basis": round(ctx["basis"], 1)}
    elif fam == "OPENFADE":
        if ctx.get("basis") is None or win.open_price is None:
            return
        age = ctx["now"] - win.start
        if not (cfg["entry_start"] <= age <= cfg["entry_end"]):
            return
        move = (ctx["spot"] - ctx["basis"]) - win.open_price
        if abs(move) < cfg["thr"]:
            return
        side = "Down" if move > 0 else "Up"  # fade the opening move
        extra = {"move_open": round(move, 1), "thr": cfg["thr"],
                 "basis": round(ctx["basis"], 1)}
    elif fam == "ACVR":
        if ctx["rho"] is None or ctx["ac_dir"] is None:
            return
        if not (cfg["tau_lo"] <= tau <= cfg["tau_hi"]):
            return
        mom_fire = ctx["rho"] > cfg["thr"] and ctx["vr"] > 1.0
        rev_fire = ctx["rho"] < -cfg["thr"] and ctx["vr"] < 1.0
        if cfg["branch"] in ("mom", "both") and mom_fire:
            side = ctx["ac_dir"]
        elif cfg["branch"] in ("rev", "both") and rev_fire:
            side = "Down" if ctx["ac_dir"] == "Up" else "Up"
        if side is None:
            return
        extra = {"rho": round(ctx["rho"], 3), "vr": round(ctx["vr"], 3)}
    if side is None:
        return
    ask, asize = books[side][1]
    if ask is None or not (cfg["band"][0] <= ask <= cfg["band"][1]):
        return
    queue_order(a, "buy1", side, ctx, extra=extra)


def snipe_tick(a, win, ctx):
    cfg = a.cfg
    books = ctx["books"]
    now = ctx["now"]
    # leg 2: complete a pair cheaply
    if len(a.pos) == 1:
        held = next(iter(a.pos))
        other = "Down" if held == "Up" else "Up"
        oask, osize = books[other][1]
        if oask:
            pair_cost = a.pos[held]["price"] + oask + fee_for(1, oask, win.fee_rate)
            if pair_cost < cfg["pair_max"] and osize >= a.pos[held]["shares"] * 0.9:
                queue_order(a, "buy2", other, ctx,
                            shares_fixed=a.pos[held]["shares"],
                            extra={"pair_cost": round(pair_cost, 4)})
    # exit rule: queue a sale of an unpaired leg-1 held long enough; the
    # fill happens on a later tick against walked bid depth (v2)
    if (cfg["exit_after"] > 0 and len(a.pos) == 1 and not a.exited
            and a.entry_ts is not None and now - a.entry_ts >= cfg["exit_after"]):
        held = next(iter(a.pos))
        queue_order(a, "exit", held, ctx)
    # leg 1: fair-gap + jump entry, once per window
    if a.pos or a.entered or not a.alive:
        return
    if ctx.get("basis") is None or now - win.start < ENTRY_DELAY_S:
        return
    if ctx["tau"] < cfg["tau_min"]:
        return
    for side in ("Up", "Down"):
        ask, asize = books[side][1]
        if ask is None or not (cfg["band"][0] <= ask <= cfg["band"][1]):
            continue
        gap = ctx["fairs"][side] - ask
        directional = ctx["jump20"] if side == "Up" else -ctx["jump20"]
        if gap >= cfg["gap"] and directional >= 20.0:
            if queue_order(a, "buy1", side, ctx,
                           extra={"gap": round(gap, 3), "jump20": round(ctx["jump20"], 1),
                                  "basis": round(ctx["basis"], 1)}):
                break


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--feed", default=None)
    ap.add_argument("--feed-token", default=None)
    ap.add_argument("--data", default=None)
    args = ap.parse_args()
    if args.data:
        global DATA
        DATA = args.data
    os.makedirs(DATA, exist_ok=True)

    cfgs = build_configs()
    reg_path = os.path.join(DATA, "accounts.json")
    if not os.path.exists(reg_path):
        with open(reg_path, "w") as f:
            json.dump(cfgs, f, indent=1)
    accounts = [Account(c) for c in cfgs]
    by_id = {a.id: a for a in accounts}
    restored = recover(accounts)
    print(f"[farm] {len(accounts)} shadow accounts, stake=${STAKE}, "
          f"start cash=${START_CASH}", flush=True)

    feed = None
    if args.feed:
        feed = FeedClient(args.feed, args.feed_token or os.environ.get("FEED_TOKEN"))
        feed.start()
        print(f"[farm] price feed {args.feed} enabled (REST fallback)", flush=True)

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    prices = deque()
    basis_samples = deque(maxlen=8)  # pre-open Binance-minus-Chainlink samples
    win = None
    pending = []          # {account, slug, start, pos}
    winner_cache = {}     # slug -> (winner, open, close)
    settle_try = {}       # slug -> last settlement lookup time
    last_summary = time.time()
    book_polls = 0
    would_reject_books = 0
    hash_repeats = 0
    age_hist = {}
    prev_hash = {"Up": None, "Down": None}

    for aid, (slug, pos, ets) in restored.items():
        a = by_id[aid]
        start = int(slug.rsplit("-", 1)[1])
        if start == int(time.time()) // 3600 * 3600:
            a.pos = pos
            a.entered = True
            a.entry_ts = ets
            print(f"[farm] {aid} live position restored in {slug}", flush=True)
        else:
            pending.append({"account": aid, "slug": slug, "start": start, "pos": pos})

    while True:
        if deadline and time.time() > deadline:
            print("[farm] time budget reached, stopping", flush=True)
            break
        try:
            now = time.time()
            wstart = int(now) // 3600 * 3600

            # settle ANY pending slug whose winner is known -- no
            # head-of-line blocking (v1 stalled all later settlements
            # behind one slow window); lookups throttled per slug
            if pending:
                slugs = []
                for p in pending:
                    if p["slug"] not in slugs:
                        slugs.append(p["slug"])
                for slug in slugs:
                    if slug not in winner_cache:
                        if now - settle_try.get(slug, 0) < 10:
                            continue
                        settle_try[slug] = now
                        try:
                            s = Window(int(slug.rsplit("-", 1)[1])).settlement()
                            if s:
                                winner_cache[slug] = s
                        except Exception:
                            pass
                    if slug not in winner_cache:
                        continue
                    winner, op, cl = winner_cache[slug]
                    rest = []
                    for p in pending:
                        if p["slug"] != slug:
                            rest.append(p)
                            continue
                        a = by_id[p["account"]]
                        payout = p["pos"].get(winner, {}).get("shares", 0.0)
                        pnl = payout - sum(x["cost"] + x["fees"] for x in p["pos"].values())
                        a.cash += payout
                        a.settled += 1
                        a.pnl += pnl
                        if pnl > 0:
                            a.wins += 1
                        append_jsonl("settlements.jsonl",
                                     {"account": a.id, "slug": slug, "winner": winner,
                                      "open": op, "close": cl,
                                      "paired": len(p["pos"]) == 2,
                                      "pnl": round(pnl, 4),
                                      "cash_after": round(a.cash, 2),
                                      "settled_at": datetime.now(timezone.utc).isoformat()})
                        print(f"[settle] {a.id} {slug} winner={winner} "
                              f"pnl={pnl:+.2f} cash={a.cash:.2f}", flush=True)
                    pending = rest

            # window rollover
            if win is None or win.start != wstart:
                if win is not None:
                    for a in accounts:
                        if a.pos:
                            pending.append({"account": a.id, "slug": win.slug,
                                            "start": win.start, "pos": a.pos})
                        a.pos = {}
                        a.entered = False
                        a.exited = False
                        a.entry_ts = None
                        a.first_try = None
                        a.tries = 0
                win = Window(wstart)
                try:
                    win.load()
                    print(f"[window] {win.slug} open={win.open_price}", flush=True)
                except Exception as e:
                    print(f"[window] load failed {e}", flush=True)
            if win is not None and not win.loaded:
                try:
                    win.load()
                except Exception:
                    pass

            # spot: Tokyo feed first, REST fallback
            spot = None
            if feed is not None:
                for recv_ts, p in feed.drain():
                    prices.append((recv_ts, p))
                lat = feed.fresh_latest()
                if lat is not None:
                    spot = lat[1]
            if spot is None:
                b = http_json(f"{BINANCE}/api/v3/ticker/price?symbol=BTCUSDT", timeout=8)
                spot = float(b["price"])
                prices.append((now, spot))
            while prices and prices[0][0] < now - 900:
                prices.popleft()
            # basis (Binance minus Chainlink) is estimated ONLY from
            # pre-open data: this window's sample compares the mean Binance
            # spot over the 15 s before the window opened with the window's
            # Chainlink open print, averaged with earlier windows' samples.
            # v1 set basis from the first in-window tick, which anchored
            # s_est at the open (fair == 0.5) and hid the opening move.
            if win.open_price and not win.basis_sampled:
                pre = [p for t, p in prices if win.start - 15 <= t < win.start - 1]
                if pre:
                    basis_samples.append(sum(pre) / len(pre) - win.open_price)
                    win.basis_sampled = True
            if basis_samples:
                win.basis = sum(basis_samples) / len(basis_samples)
            basis = win.basis if win.basis is not None else 0.0
            s_est = spot - basis

            sigma = 0.00012
            pts = [p for _, p in prices]
            if len(pts) > 30:
                rets = [math.log(pts[i] / pts[i - 1]) for i in range(1, len(pts))]
                if len(rets) > 10:
                    mean = sum(rets) / len(rets)
                    var = sum((r - mean) ** 2 for r in rets) / len(rets)
                    step = max((prices[-1][0] - prices[0][0]) / max(len(pts) - 1, 1), 0.1)
                    sigma = max(math.sqrt(var) / math.sqrt(step), 1e-5)

            tau = max(win.end - now, 0)
            fair_up = None
            if win.open_price:
                if tau >= 60:
                    exp_twap = s_est
                    var_f = tau - 40.0
                else:
                    elapsed = 60.0 - tau
                    tw = [p - basis for t, p in prices if t >= win.end - 60]
                    realised = sum(tw) / len(tw) if tw else s_est
                    exp_twap = (realised * elapsed + s_est * tau) / 60.0
                    var_f = tau ** 3 / (3.0 * 60.0 * 60.0)
                z = math.log(exp_twap / win.open_price) / (sigma * math.sqrt(max(var_f, 1e-6)))
                fair_up = min(max(norm_cdf(z), 0.001), 0.999)

            books = {}
            levels = {}
            book_meta = {}
            for side in ("Up", "Down"):
                tok = win.token.get(side)
                if tok:
                    try:
                        bk = http_json(f"{CLOB}/book?token_id={tok}", timeout=8)
                        ts_ms = int(bk.get("timestamp") or 0)
                        # age at RECEIPT (fresh time.time()), not vs the
                        # loop-top `now`: request transit otherwise biases
                        # ages negative by the round-trip time
                        age_ms = int(time.time() * 1000) - ts_ms if ts_ms else None
                        book_meta[side] = {"ts": ts_ms, "age_ms": age_ms,
                                           "hash": bk.get("hash"),
                                           "stale": would_reject_age(age_ms)}
                        # record-only: count and histogram every book,
                        # but USE it exactly as v2 did (no filtering)
                        book_polls += 1
                        bkt = age_bucket(age_ms)
                        age_hist[bkt] = age_hist.get(bkt, 0) + 1
                        if bk.get("hash") is not None \
                                and bk.get("hash") == prev_hash[side]:
                            hash_repeats += 1
                        prev_hash[side] = bk.get("hash")
                        if book_meta[side]["stale"]:
                            would_reject_books += 1
                        books[side] = best_levels(bk)
                        bl, al = sorted_levels(bk)
                        levels[side] = {"bids": bl, "asks": al}
                    except Exception:
                        book_meta[side] = {"ts": None, "age_ms": None,
                                           "hash": None, "stale": True}
                        books[side] = ((None, 0.0), (None, 0.0))
                        levels[side] = {"bids": [], "asks": []}
                else:
                    book_meta[side] = {"ts": None, "age_ms": None,
                                       "hash": None, "stale": True}
                    books[side] = ((None, 0.0), (None, 0.0))
                    levels[side] = {"bids": [], "asks": []}

            moves = {}
            for L in (5, 10, 20, 30, 60):
                p0 = price_at(prices, now - L)
                moves[L] = (spot - p0) if p0 else None
            rho, vr, ac_dir = acvr_stats(prices)
            ctx = {"now": now, "tau": tau, "spot": spot, "slug": win.slug,
                   "basis": win.basis,
                   "fairs": {"Up": fair_up, "Down": (1.0 - fair_up) if fair_up is not None else None},
                   "books": books, "levels": levels, "book_meta": book_meta,
                   "moves": moves,
                   "jump20": moves[20] or 0.0,
                   "rho": rho, "vr": vr, "ac_dir": ac_dir}
            if fair_up is not None and win.loaded:
                for a in accounts:
                    try:
                        account_tick(a, win, ctx)
                    except Exception as e:
                        print(f"[warn] {a.id} tick error: {e}", flush=True)

            with open(os.path.join(DATA, "state.json"), "w") as f:
                json.dump({"updated": datetime.now(timezone.utc).isoformat(),
                           "farm_version": FARM_VERSION,
                           "book_polls": book_polls,
                           "would_reject_books": would_reject_books,
                           "hash_repeats": hash_repeats,
                           "book_age_hist": age_hist,
                           "basis": round(win.basis, 1) if win.basis is not None else None,
                           "window": win.slug,
                           "accounts": {a.id: a.snapshot() for a in accounts},
                           "pending": len(pending)}, f, indent=1)

            if now - last_summary > 3600:
                last_summary = now
                ranked = sorted(accounts, key=lambda a: -a.pnl)
                alive = sum(1 for a in accounts if a.alive)
                print(f"[summary] alive={alive}/{len(accounts)} top: " +
                      ", ".join(f"{a.id} {a.pnl:+.1f}" for a in ranked[:5]) +
                      " | bottom: " +
                      ", ".join(f"{a.id} {a.pnl:+.1f}" for a in ranked[-5:]), flush=True)
        except KeyboardInterrupt:
            print("[farm] stopped by user", flush=True)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("[warn] HTTP 429, backing off 15s", flush=True)
                time.sleep(15)
            else:
                print(f"[warn] loop error: HTTP {e.code}", flush=True)
        except Exception as e:
            print(f"[warn] loop error: {e}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
