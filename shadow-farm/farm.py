#!/usr/bin/env python3
"""Shadow-account farm for Polymarket BTC 5m up/down markets (PAPER ONLY).

One process, one Tokyo-feed connection, one pair of CLOB book polls per
tick -- shared by 60 virtual accounts, each with its own strategy
parameters, a $50 paper bankroll and a $5 stake. Accounts that run out of
cash stop trading (survival is part of the test).

Families (12 parameter sets each):
  MOM   follow the Binance spot move over a lookback
  REV   fade the Binance spot move over a lookback
  FAIR  buy the side whose TWAP-aware fair value exceeds the ask by a gap
  ACVR  lag-1 autocorrelation + variance-ratio branches (Dan1ro0 signal)
  SNIPE the v0.5 latency-snipe rules (fair gap + jump, optional pair/exit)

Purpose: a screen, not proof. With 60 accounts the best performer is
expected to look good by chance alone; judge family-level clustering and
require a long run before believing any single account.

Logs (in the data dir): accounts.json (registry), trades.jsonl,
settlements.jsonl, state.json (rewritten every tick).
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


def http_json(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fee_for(shares, price, rate=0.07):
    return shares * rate * price * (1.0 - price)


def best_levels(book):
    bids = [(float(b["price"]), float(b["size"])) for b in book.get("bids", [])]
    asks = [(float(a["price"]), float(a["size"])) for a in book.get("asks", [])]
    best_bid = max(bids) if bids else (None, 0.0)
    best_ask = min(asks) if asks else (None, 0.0)
    return best_bid, best_ask


def append_jsonl(name, row):
    with open(os.path.join(DATA, name), "a") as f:
        f.write(json.dumps(row) + "\n")


def read_jsonl(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


# ---------------------------------------------------------------- accounts
def build_configs():
    cfgs = []
    for L in (10, 30, 60):
        for thr in (20.0, 40.0):
            for band in ((0.15, 0.92), (0.35, 0.85)):
                cfgs.append({"family": "MOM", "lookback": L, "thr": thr,
                             "band": band, "tau_lo": 30, "tau_hi": 240})
                cfgs.append({"family": "REV", "lookback": L, "thr": thr,
                             "band": band, "tau_lo": 30, "tau_hi": 240})
    # MOM and REV interleaved above: 24 rows -> split into 12 + 12 below.
    mom = [c for c in cfgs if c["family"] == "MOM"]
    rev = [c for c in cfgs if c["family"] == "REV"]
    cfgs = []
    for i, c in enumerate(mom):
        c["id"] = f"mom-{i + 1:02d}"
        cfgs.append(c)
    for i, c in enumerate(rev):
        c["id"] = f"rev-{i + 1:02d}"
        cfgs.append(c)
    n = 0
    for gap in (0.05, 0.08, 0.12):
        for tau_min in (30, 60):
            for band in ((0.15, 0.92), (0.30, 0.80)):
                n += 1
                cfgs.append({"id": f"fair-{n:02d}", "family": "FAIR", "gap": gap,
                             "tau_min": tau_min, "band": band})
    n = 0
    for thr in (0.02, 0.05):
        for branch in ("mom", "rev", "both"):
            for tau_rng in ((30, 150), (60, 240)):
                n += 1
                cfgs.append({"id": f"acvr-{n:02d}", "family": "ACVR", "thr": thr,
                             "branch": branch, "tau_lo": tau_rng[0],
                             "tau_hi": tau_rng[1], "band": (0.15, 0.92)})
    n = 0
    for gap in (0.06, 0.08, 0.10):
        for pair_max in (0.95, 0.97):
            for exit_after in (0, 60):
                n += 1
                cfgs.append({"id": f"snipe-{n:02d}", "family": "SNIPE", "gap": gap,
                             "pair_max": pair_max, "exit_after": exit_after,
                             "tau_min": 60, "band": (0.15, 0.92)})
    return cfgs


class Account:
    def __init__(self, cfg):
        self.cfg = cfg
        self.id = cfg["id"]
        self.cash = START_CASH
        self.pos = {}            # side -> {shares, cost, fees, price}
        self.entered = False     # leg-1 done for the live window
        self.entry_ts = None
        self.exited = False
        self.trades = 0
        self.settled = 0
        self.wins = 0
        self.pnl = 0.0

    @property
    def alive(self):
        return self.cash >= 1.0

    def snapshot(self):
        return {"cash": round(self.cash, 2), "pnl": round(self.pnl, 2),
                "trades": self.trades, "settled": self.settled,
                "wins": self.wins, "alive": self.alive,
                "in_pos": bool(self.pos)}


# ------------------------------------------------------------------- window
class Window:
    def __init__(self, start_ts):
        self.start = start_ts
        self.end = start_ts + 300
        self.slug = f"btc-updown-5m-{start_ts}"
        self.token = {}
        self.open_price = None
        self.fee_rate = 0.07
        self.basis = None
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
            {"symbol": "BTC", "variant": "fiveminute", "eventStartTime": self.start}))
        if cp.get("openPrice"):
            self.open_price = float(cp["openPrice"])
        self.loaded = True
        return True

    def settlement(self):
        cp = http_json(f"{PM_WEB}/api/crypto/crypto-price?" + urllib.parse.urlencode(
            {"symbol": "BTC", "variant": "fiveminute", "eventStartTime": self.start}))
        if not cp.get("completed") or cp.get("closePrice") is None:
            return None
        winner = "Up" if float(cp["closePrice"]) >= float(cp["openPrice"]) else "Down"
        return winner, float(cp["openPrice"]), float(cp["closePrice"])


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
        if float(row.get("pnl", 0)) >= 0:
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
            if pnl >= 0:
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
        if start + 300 > now:
            restored[aid] = (slug, pos)  # window still live; hand back below
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
                if pnl >= 0:
                    a.wins += 1
                settled_keys.add((aid, slug))
                print(f"[recover] {aid} {slug} settled pnl={pnl:+.2f}", flush=True)
            else:
                restored[aid] = (slug, pos)  # settle later via pending queue
    for a in accounts:
        open_cost = 0.0
        for t in trades:
            if t.get("account") == a.id and (a.id, t.get("slug")) not in settled_keys \
                    and t.get("leg") in (1, 2):
                open_cost += float(t["cost"]) + float(t["fees"])
        a.cash = START_CASH + a.pnl - open_cost
    return restored


# ------------------------------------------------------------------- engine
def try_buy(a, win, side, price, size_avail, leg, ctx, shares_fixed=None, extra=None):
    shares = shares_fixed if shares_fixed else STAKE / price
    if size_avail < shares:
        return False
    cost = shares * price
    fees = fee_for(shares, price, win.fee_rate)
    if a.cash < cost + fees:
        return False
    a.cash -= cost + fees
    a.pos[side] = {"shares": shares, "cost": cost, "fees": fees, "price": price}
    a.trades += 1
    if leg == 1:
        a.entered = True
        a.entry_ts = ctx["now"]
    row = {"account": a.id, "family": a.cfg["family"],
           "ts": datetime.now(timezone.utc).isoformat(), "slug": win.slug,
           "leg": leg, "side": side, "price": price,
           "shares": round(shares, 3), "cost": round(cost, 4),
           "fees": round(fees, 4)}
    if extra:
        row.update(extra)
    append_jsonl("trades.jsonl", row)
    print(f"[trade] {a.id} {'BUY' if leg == 1 else 'PAIR'} {side} @ {price:.3f} "
          f"cash={a.cash:.2f} {win.slug}", flush=True)
    return True


def account_tick(a, win, ctx):
    cfg = a.cfg
    fam = cfg["family"]
    tau = ctx["tau"]
    books = ctx["books"]
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
        extra = {"gap": round(best_gap[0], 3), "fair": round(ctx["fairs"][side], 3)}
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
    try_buy(a, win, side, ask, asize, 1, ctx, extra=extra)


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
                try_buy(a, win, other, oask, osize, 2, ctx,
                        shares_fixed=a.pos[held]["shares"],
                        extra={"pair_cost": round(pair_cost, 4)})
    # exit rule: sell an unpaired leg-1 held long enough, at the best bid
    if (cfg["exit_after"] > 0 and len(a.pos) == 1 and not a.exited
            and a.entry_ts is not None and now - a.entry_ts >= cfg["exit_after"]):
        held = next(iter(a.pos))
        bid, _bsize = books[held][0]
        if bid is not None:
            p = a.pos[held]
            proceeds = p["shares"] * bid
            sfee = fee_for(p["shares"], bid, win.fee_rate)
            pnl = proceeds - sfee - p["cost"] - p["fees"]
            a.cash += proceeds - sfee
            append_jsonl("trades.jsonl",
                         {"account": a.id, "family": "SNIPE",
                          "ts": datetime.now(timezone.utc).isoformat(),
                          "slug": win.slug, "leg": "exit", "side": held,
                          "price": bid, "shares": round(p["shares"], 3),
                          "proceeds": round(proceeds, 4), "fees": round(sfee, 4)})
            a.trades += 1
            a.settled += 1
            a.pnl += pnl
            if pnl >= 0:
                a.wins += 1
            append_jsonl("settlements.jsonl",
                         {"account": a.id, "slug": win.slug, "winner": None,
                          "exited": True, "exit_price": bid, "pnl": round(pnl, 4),
                          "cash_after": round(a.cash, 2),
                          "settled_at": datetime.now(timezone.utc).isoformat()})
            print(f"[trade] {a.id} EXIT {held} @ {bid:.3f} pnl={pnl:+.2f} {win.slug}",
                  flush=True)
            a.pos = {}
            a.exited = True
    # leg 1: fair-gap + jump entry, once per window
    if a.pos or a.entered or not a.alive:
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
            if try_buy(a, win, side, ask, asize, 1, ctx,
                       extra={"gap": round(gap, 3), "jump20": round(ctx["jump20"], 1)}):
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
    win = None
    pending = []          # {account, slug, start, pos}
    winner_cache = {}     # slug -> (winner, open, close)
    last_summary = time.time()

    for aid, (slug, pos) in restored.items():
        a = by_id[aid]
        start = int(slug.rsplit("-", 1)[1])
        if start == int(time.time()) // 300 * 300:
            a.pos = pos
            a.entered = True
            print(f"[farm] {aid} live position restored in {slug}", flush=True)
        else:
            pending.append({"account": aid, "slug": slug, "start": start, "pos": pos})

    while True:
        if deadline and time.time() > deadline:
            print("[farm] time budget reached, stopping", flush=True)
            break
        try:
            now = time.time()
            wstart = int(now) // 300 * 300

            # settle the oldest pending slug when its winner is known
            if pending:
                slug0 = pending[0]["slug"]
                if slug0 not in winner_cache:
                    try:
                        s = Window(pending[0]["start"]).settlement()
                        if s:
                            winner_cache[slug0] = s
                    except Exception:
                        pass
                if slug0 in winner_cache:
                    winner, op, cl = winner_cache[slug0]
                    rest = []
                    for p in pending:
                        if p["slug"] != slug0:
                            rest.append(p)
                            continue
                        a = by_id[p["account"]]
                        payout = p["pos"].get(winner, {}).get("shares", 0.0)
                        pnl = payout - sum(x["cost"] + x["fees"] for x in p["pos"].values())
                        a.cash += payout
                        a.settled += 1
                        a.pnl += pnl
                        if pnl >= 0:
                            a.wins += 1
                        append_jsonl("settlements.jsonl",
                                     {"account": a.id, "slug": slug0, "winner": winner,
                                      "open": op, "close": cl,
                                      "paired": len(p["pos"]) == 2,
                                      "pnl": round(pnl, 4),
                                      "cash_after": round(a.cash, 2),
                                      "settled_at": datetime.now(timezone.utc).isoformat()})
                        print(f"[settle] {a.id} {slug0} winner={winner} "
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
            if win.basis is None and win.open_price:
                win.basis = spot - win.open_price
            basis = win.basis or 0.0
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
            for side in ("Up", "Down"):
                tok = win.token.get(side)
                if tok:
                    try:
                        bk = http_json(f"{CLOB}/book?token_id={tok}", timeout=8)
                        books[side] = best_levels(bk)
                    except Exception:
                        books[side] = ((None, 0.0), (None, 0.0))
                else:
                    books[side] = ((None, 0.0), (None, 0.0))

            moves = {}
            for L in (5, 10, 20, 30, 60):
                p0 = price_at(prices, now - L)
                moves[L] = (spot - p0) if p0 else None
            rho, vr, ac_dir = acvr_stats(prices)
            ctx = {"now": now, "tau": tau, "spot": spot,
                   "fairs": {"Up": fair_up, "Down": (1.0 - fair_up) if fair_up is not None else None},
                   "books": books, "moves": moves,
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
                           "window": win.slug,
                           "accounts": {a.id: a.snapshot() for a in accounts},
                           "pending": len(pending)}, f, indent=1)

            if now - last_summary > 3600:
                last_summary = now
                ranked = sorted(accounts, key=lambda a: -a.pnl)
                alive = sum(1 for a in accounts if a.alive)
                print(f"[summary] alive={alive}/60 top: " +
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
