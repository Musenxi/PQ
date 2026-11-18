#!/usr/bin/env python3
"""
Polymarket BTC 5m — PAPER TRADING, AC/VR signal variant (based on snipe_paper.py v0.6)

v0.6 changes (2026-11-17, from the optimisation backtests in
goals/polymarket-btc-5m-paper-trading-run/files/backtest-optimization-2026-11-17.md):
  - Optional exit rule (--exit-after N, default 0 = off): a leg-1 that is
    still unpaired N seconds after entry is SOLD at the best bid instead
    of riding to settlement. Backtest on the VPS v0.5 data (12 windows):
    a 60s trigger improved total PnL from -21.41 to -7.40 (avg exit
    ~-2.07 vs ~-6.20 for a held unpaired loss). The exit writes its
    settlement row immediately (exited=true, winner=null) and the window
    cannot re-enter afterwards. Pair-threshold loosening and a trend
    filter were backtested the same evening and rejected / deferred.

v0.5 changes (2026-11-17):
  - Optional Tokyo price relay: with --feed <host>:<port> the Binance
    spot series is consumed from binance_feed.py running next to
    Binance (WebSocket-fast there; one-way relay to Amsterdam ~115ms)
    instead of a ~0.93s fresh-TLS REST poll per loop. REST polling
    remains as an automatic fallback whenever the feed is silent for
    >2.5s, and every tick records which source priced it ("src") plus
    the feed lag in ms. Without --feed, behaviour is exactly v0.4.

v0.4 changes (2026-11-17, from the external strategy review and its
verification against the v0.3 24h data):
  - Fair value now matches the settlement definition. Settlement is the
    average price over the final 60s (TWAP-60), not the terminal price,
    so the old sigma*sqrt(tau) overstated the outcome spread (by ~10-17%
    at typical entry tau, more near the end). v0.4 uses the TWAP variance:
    sigma*sqrt(tau-40) for tau>=60, and for tau<60 a partially-realised
    TWAP mean with variance sigma^2 * tau^3/(3*60^2).
  - Open-price reconciliation, revised after testing: the crypto-price
    endpoint's openPrice (the settlement anchor, used by the model) and
    Gamma's priceToBeat differed by a median of $8.4 (max $37.5) across
    10 sampled windows. BUT Gamma only publishes priceToBeat inside
    eventMetadata after the window closes, so it cannot filter live
    entries — and model and settlement already share the operative
    endpoint open. v0.4 therefore records priceToBeat and the diff in
    each settlement row for later analysis instead of trading on it.
  - Ticks now also record best bids and best ask/bid sizes for both
    sides, so mirror consistency (up_ask + down_bid ~ 1) and exit rules
    can be backtested later. v0.3 ticks carried asks only.

v0.3 changes (2026-11-17, after the first 24h attempt):
  - Startup recovery: windows that were traded but never settled (process
    died before the window ended) are settled on startup via
    recover_orphans(). v0.2's seed_summary() silently dropped them from the
    books — that bug hid 5 windows / -$17.00 in the first 24h attempt.
  - Leg-1 entries now require >=60s remaining (was >20s): every unpaired
    loss in the data came from a late-window entry that reverted before
    the TWAP-60s settlement.

What it does (no real orders, no wallet, no keys):
  - Polls Binance spot BTCUSDT (data-api.binance.vision, the main api.binance.com
    is geo-blocked from this VM) ~ every 1.5s as the *leading* signal.
  - Finds the current Polymarket BTC Up/Down 5m market from its deterministic
    slug  btc-updown-5m-<window_start_unix>  via the Gamma API.
  - Gets the Chainlink "price to beat" (openPrice) for the window from
    Polymarket's crypto-price endpoint (variant=fiveminute). Settlement for
    these markets is Chainlink TWAP-60s (see market cryptoMarketConfig:
    btc-5m-twap-60), NOT a spot snapshot — the model below is an approximation.
  - Reads the live CLOB order book for the Up and Down tokens.
  - Fair-price model (v0.4, TWAP-aware):  P(Up) = Phi( ln(E[TWAP] / S_open) / (sigma * sqrt(V)) )
      E[TWAP] = expected average price over the settlement window's final
               60s: S_est while tau>=60; once inside the final 60s, the
               realised average so far blended with S_est for the rest.
      V      = tau - 40 for tau>=60; tau^3/(3*60^2) for tau<60.
      S_est  = Binance price now, adjusted by the Binance-vs-Chainlink basis
               measured at the window open.
      sigma  = realised vol / sqrt(second) from the Binance series we collect.
      tau    = seconds remaining until the window ends.
  - PAPER BUY leg 1 when: fair - ask >= GAP (default 0.08), the Binance move
    over the last ~20s points the same way, ask is in [0.15, 0.92], enough
    size sits at the best ask, and >=60s remain. Fixed $6 stake (as in the
    post that inspired this). Fee simulated with the market's own fee
    schedule (crypto_fees_v2, rate 0.07, taker only):
      fee = shares * rate * price * (1 - price)
  - PAPER BUY leg 2 (pair) when we hold one side and
    leg1_price + opposite_ask (+fees/share) < PAIR_MAX (default 0.95):
    buy the same number of shares of the other side -> locked pair.
  - Holds to settlement. Winner from crypto-price closePrice vs openPrice
    (completed=true). PnL = winning_shares - total_cost - total_fees.

Logs (JSONL) under data/:
  ticks.jsonl       every poll: prices, book, fair, gap, action considered
  trades.jsonl      paper fills (leg1 / leg2)
  settlements.jsonl one row per finished window
  state.json        rolling summary for the dashboard generator

Usage:
  python3 snipe_paper.py                 # run forever (Ctrl-C to stop)
  python3 snipe_paper.py --minutes 12    # run ~12 minutes then stop
"""
import argparse, ast, json, math, os, socket, sys, threading, time, urllib.error, urllib.parse, urllib.request
from collections import deque
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

BINANCE = "https://data-api.binance.vision"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
PM_WEB = "https://polymarket.com"
UA = {"User-Agent": "Mozilla/5.0 (paper-prototype)"}


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


# --- AC/VR experiment (2026-11-17): the signal from the Dan1ro0 X post ---
# Lag-1 autocorrelation + Lo-MacKinlay variance ratio on 1-second BTC log
# returns, computed on the same (ts, price) series the snipe collector
# keeps. The post specified only the momentum branch; the reversion
# branch is its symmetric counterpart. One $6 paper entry per 5m window,
# first signal at tau<=150s, ask band [0.15, 0.92], hold to settlement.
def acvr_signal(prices, lookback=180):
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
    direction = "Up" if last_move > 0 else "Down"
    if rho > 0.02 and vr > 1.0:
        return rho, vr, direction
    if rho < -0.02 and vr < 1.0:
        return rho, vr, ("Down" if direction == "Up" else "Up")
    return rho, vr, None


class Window:
    def __init__(self, start_ts):
        self.start = start_ts
        self.end = start_ts + 300
        self.slug = f"btc-updown-5m-{start_ts}"
        self.token = {}          # "Up"/"Down" -> token id
        self.open_price = None   # settlement open (crypto-price endpoint)
        self.price_to_beat = None  # Gamma eventMetadata priceToBeat (post-close)
        self.basis = None        # Binance - Chainlink at open
        self.fee_rate = 0.07
        self.pos = {}            # side -> {shares, cost, fees, price}
        self.entry_ts = None     # time.time() of the leg-1 fill (v0.6 exit rule)
        self.entered = False     # a leg-1 was filled this window (one per window)
        self.exited = False      # position closed by the v0.6 exit rule
        self.settled = False
        self.skipped_late = 0
        self.loaded = False

    def note_ptb(self, ev0):
        """Record Gamma's priceToBeat from an events payload. Gamma only
        attaches eventMetadata after the window closes, so during live
        trading this normally finds nothing."""
        meta = ev0.get("eventMetadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = None
        if meta and meta.get("priceToBeat") is not None:
            self.price_to_beat = float(meta["priceToBeat"])

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
        self.note_ptb(ev[0])
        self.loaded = True
        return True

    def fetch_ptb(self):
        """Post-close only: Gamma's priceToBeat for the settlement row."""
        try:
            ev = http_json(f"{GAMMA}/events?slug={self.slug}")
            if ev:
                self.note_ptb(ev[0])
        except Exception:
            pass
        return self.price_to_beat

    def settlement(self):
        cp = http_json(f"{PM_WEB}/api/crypto/crypto-price?" + urllib.parse.urlencode(
            {"symbol": "BTC", "variant": "fiveminute", "eventStartTime": self.start}))
        if not cp.get("completed") or cp.get("closePrice") is None:
            return None
        winner = "Up" if float(cp["closePrice"]) >= float(cp["openPrice"]) else "Down"
        return winner, float(cp["openPrice"]), float(cp["closePrice"])


def parse_endpoint(spec):
    """'host:port' or '[ipv6]:port' -> (host, port)."""
    spec = spec.strip()
    if spec.startswith("["):
        host, _, rest = spec[1:].partition("]")
        return host, int(rest.lstrip(":") or 8765)
    host, _, port = spec.partition(":")
    return host, int(port or 8765)


class FeedClient:
    """Consumes binance_feed.py over TCP. Samples are stored with their
    local receipt time, so the vol/jump series stays honest about when
    *we* knew the price; the feed's own publish timestamp is kept only
    to report the relay lag.

    The --feed spec may list several endpoints separated by commas;
    they are tried in order on every (re)connect (IPv6 first, IPv4 as
    fallback — Amsterdam<->Tokyo measured ~11ms faster over IPv6)."""

    def __init__(self, spec, token=None):
        self.addrs = [parse_endpoint(s) for s in spec.split(",") if s.strip()]
        self.token = token
        self.lock = threading.Lock()
        self.pending = []        # (recv_ts, price)
        self.latest = None       # (recv_ts, price, feed_ts)

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
                                continue  # heartbeat / auth error
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


def append_jsonl(name, row):
    with open(os.path.join(DATA, name), "a") as f:
        f.write(json.dumps(row) + "\n")


def read_jsonl(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def seed_summary():
    """Rebuild counters from existing logs so a restart keeps cumulative stats."""
    s = {"windows": 0, "wins": 0, "losses": 0, "pairs": 0, "skips": 0, "pnl": 0.0, "trades": 0}
    for row in read_jsonl("settlements.jsonl"):
        s["windows"] += 1
        s["pnl"] += float(row.get("pnl", 0))
        s["pairs"] += 1 if row.get("paired") else 0
        if float(row.get("pnl", 0)) >= 0: s["wins"] += 1
        else: s["losses"] += 1
    s["trades"] = len(read_jsonl("trades.jsonl"))
    return s


def record_settlement(win, summary, recovered=False):
    """Try to settle one window once. Returns True if settled now."""
    s = win.settlement()
    if not s:
        return False
    winner, op, cl = s
    win_shares = win.pos.get(winner, {}).get("shares", 0.0)
    cost = sum(p["cost"] + p["fees"] for p in win.pos.values())
    pnl = win_shares - cost
    paired = len(win.pos) == 2
    summary["windows"] += 1
    summary["pnl"] += pnl
    summary["pairs"] += 1 if paired else 0
    if pnl >= 0: summary["wins"] += 1
    else: summary["losses"] += 1
    ptb = win.fetch_ptb()
    row = {"slug": win.slug, "winner": winner, "open": op, "close": cl,
           "paired": paired, "pnl": round(pnl, 4), "pos": win.pos,
           "open_ptb": ptb,
           "open_diff": round(ptb - op, 2) if ptb is not None else None,
           "settled_at": datetime.now(timezone.utc).isoformat()}
    if recovered:
        row["recovered"] = True
    append_jsonl("settlements.jsonl", row)
    print(f"[settle] {win.slug} winner={winner} pnl={pnl:+.2f} (open {op:.1f} close {cl:.1f})"
          f"{' [recovered]' if recovered else ''}", flush=True)
    win.settled = True
    return True


def recover_orphans(summary):
    """Settle windows present in trades.jsonl but missing from
    settlements.jsonl (the process died before the window ended).
    Returns the number of windows recovered."""
    settled = {r["slug"] for r in read_jsonl("settlements.jsonl")}
    by_slug = {}
    for t in read_jsonl("trades.jsonl"):
        by_slug.setdefault(t["slug"], []).append(t)
    recovered = 0
    for slug, rows in sorted(by_slug.items()):
        if slug in settled:
            continue
        try:
            start = int(slug.rsplit("-", 1)[1])
        except Exception:
            continue
        if start + 300 > time.time():
            continue  # window not over yet; live loop / next startup handles it
        exits = [t for t in rows if t.get("leg") == "exit"]
        if exits:
            # v0.6: position was closed by the exit rule but its settlement
            # row was lost (crash between the two writes) — rebuild it from
            # the trade rows instead of settling the leg as held.
            e, b = exits[0], rows[0]
            pnl = float(e["proceeds"]) - float(e["fees"]) - float(b["cost"]) - float(b["fees"])
            summary["windows"] += 1
            summary["pnl"] += pnl
            if pnl >= 0: summary["wins"] += 1
            else: summary["losses"] += 1
            append_jsonl("settlements.jsonl",
                         {"slug": slug, "winner": None, "open": None, "close": None,
                          "paired": False, "exited": True, "recovered": True,
                          "exit_price": float(e["price"]), "pnl": round(pnl, 4),
                          "pos": {b["side"]: {"shares": float(b["shares"]), "cost": float(b["cost"]),
                                              "fees": float(b["fees"]), "price": float(b["price"])}},
                          "settled_at": datetime.now(timezone.utc).isoformat()})
            print(f"[recover] {slug} rebuilt exited settlement pnl={pnl:+.2f}", flush=True)
            recovered += 1
            continue
        win = Window(start)
        for t in rows:
            win.pos[t["side"]] = {"shares": float(t["shares"]), "cost": float(t["cost"]),
                                  "fees": float(t["fees"]), "price": float(t["price"])}
        try:
            if record_settlement(win, summary, recovered=True):
                recovered += 1
        except Exception as e:
            print(f"[recover] {slug} failed: {e}", flush=True)
    if recovered:
        print(f"[recover] settled {recovered} orphan window(s) from trades.jsonl", flush=True)
    return recovered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0, help="stop after N minutes (0 = forever)")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--stake", type=float, default=6.0, help="paper stake per leg-1, USD")
    ap.add_argument("--gap", type=float, default=0.08, help="min fair-minus-ask edge to buy")
    ap.add_argument("--pair-max", type=float, default=0.95)
    ap.add_argument("--jump-window", type=int, default=20, help="seconds for jump detection")
    ap.add_argument("--min-jump", type=float, default=20.0, help="min USD move over jump window, same direction")
    ap.add_argument("--min-tau", type=float, default=60.0, help="min seconds remaining for a leg-1 entry (v0.3: raised from 20)")
    ap.add_argument("--exit-after", type=float, default=0, help="v0.6 exit rule: sell an unpaired leg-1 at the best bid once it has been held this many seconds (0 = off, hold to settlement)")
    ap.add_argument("--feed", default=None, help="comma-separated host:port endpoints of binance_feed.py, tried in order; use [ipv6]:port for IPv6 (v0.5)")
    ap.add_argument("--feed-token", default=None, help="feed auth token (or FEED_TOKEN env)")
    args = ap.parse_args()

    deadline = time.time() + args.minutes * 60 if args.minutes else None
    prices = deque()  # (ts, binance_price)
    win = None
    pending = []  # windows with positions waiting for Chainlink close (non-blocking)
    summary = seed_summary()
    recover_orphans(summary)
    if summary["windows"] or summary["trades"]:
        print(f"[paper] resumed from logs: {summary}", flush=True)

    feed = None
    if args.feed:
        feed = FeedClient(args.feed, args.feed_token or os.environ.get("FEED_TOKEN"))
        feed.start()
        print(f"[paper] price feed {args.feed} enabled (REST fallback on silence)", flush=True)

    print(f"[paper] AC/VR variant: stake=${args.stake}, signal=rho+VR(5) on 1s returns, enter tau<=150s", flush=True)
    while True:
        if deadline and time.time() > deadline:
            print("[paper] time budget reached, stopping", flush=True)
            break
        try:
            now = time.time()
            wstart = int(now) // 300 * 300

            # --- pending settlements: one non-blocking attempt per loop ---
            if pending:
                try:
                    if record_settlement(pending[0], summary):
                        pending.pop(0)
                except Exception:
                    pass  # try again next loop; never block ticking

            # --- window rollover: queue previous window for settlement ---
            if win is None or win.start != wstart:
                if win is not None and not win.settled and win.pos:
                    pending.append(win)
                win = Window(wstart)
                try:
                    win.load()
                    print(f"[window] {win.slug} openPrice={win.open_price} tokens ok={win.loaded}", flush=True)
                except Exception as e:
                    print(f"[window] load failed {e}", flush=True)

            # --- retry window load until it succeeds (Gamma can time out) ---
            if win is not None and not win.loaded:
                try:
                    win.load()
                    print(f"[window] {win.slug} openPrice={win.open_price} tokens ok={win.loaded}", flush=True)
                except Exception as e:
                    print(f"[window] load retry failed {e}", flush=True)

            # --- Binance spot (leading signal): Tokyo feed first, REST fallback ---
            spot = None
            src_used = "rest"
            feed_lag_ms = None
            if feed is not None:
                for recv_ts, p in feed.drain():
                    prices.append((recv_ts, p))
                lat = feed.fresh_latest()
                if lat is not None:
                    spot = lat[1]
                    src_used = "feed"
                    feed_lag_ms = round((now - lat[2]) * 1000)
            if spot is None:
                b = http_json(f"{BINANCE}/api/v3/ticker/price?symbol=BTCUSDT", timeout=8)
                spot = float(b["price"])
                prices.append((now, spot))
            while prices and prices[0][0] < now - 600:
                prices.popleft()
            if win.basis is None and win.open_price:
                win.basis = spot - win.open_price
            basis = win.basis or 0.0
            s_est = spot - basis  # Chainlink-spot estimate

            # realised vol per second from last ~120s of 1-step returns
            sigma = 0.00012  # fallback ~ $8/s at 65k
            pts = [p for _, p in prices]
            if len(pts) > 30:
                rets = [math.log(pts[i] / pts[i - 1]) for i in range(1, len(pts))]
                if len(rets) > 10:
                    mean = sum(rets) / len(rets)
                    var = sum((r - mean) ** 2 for r in rets) / len(rets)
                    step = max((prices[-1][0] - prices[0][0]) / max(len(pts) - 1, 1), 0.1)
                    sigma = max(math.sqrt(var) / math.sqrt(step), 1e-5)

            # jump over the lookback window
            past = [p for t, p in prices if t <= now - args.jump_window]
            jump = spot - past[-1] if past else 0.0

            tau = max(win.end - now, 0)
            fair_up = None
            if win.open_price:
                # v0.4 TWAP-aware fair value: settlement is the mean price
                # over the final 60s, not the terminal price.
                if tau >= 60:
                    exp_twap = s_est
                    var_f = tau - 40.0  # (tau-60) unaveraged + 60/3 averaged
                else:
                    elapsed = 60.0 - tau
                    tw = [p - basis for t, p in prices if t >= win.end - 60]
                    realised = sum(tw) / len(tw) if tw else s_est
                    exp_twap = (realised * elapsed + s_est * tau) / 60.0
                    var_f = tau ** 3 / (3.0 * 60.0 * 60.0)
                z = math.log(exp_twap / win.open_price) / (sigma * math.sqrt(max(var_f, 1e-6)))
                fair_up = min(max(norm_cdf(z), 0.001), 0.999)

            # --- Polymarket books ---
            books = {}
            for side in ("Up", "Down"):
                tok = win.token.get(side)
                if tok:
                    try:
                        bk = http_json(f"{CLOB}/book?token_id={tok}", timeout=8)
                        books[side] = best_levels(bk)
                    except Exception:
                        books[side] = ((None, 0.0), (None, 0.0))

            _empty = ((None, 0.0), (None, 0.0))
            _ub, _db = books.get("Up", _empty), books.get("Down", _empty)
            tick = {"ts": datetime.now(timezone.utc).isoformat(), "slug": win.slug,
                    "spot": spot, "s_est": round(s_est, 1), "open": win.open_price,
                    "open_ptb": win.price_to_beat,
                    "open_diff": round(win.price_to_beat - win.open_price, 2)
                                 if (win.price_to_beat is not None and win.open_price) else None,
                    "tau": round(tau), "jump20": round(jump, 1),
                    "src": src_used, "feed_lag_ms": feed_lag_ms,
                    "fair_up": round(fair_up, 3) if fair_up else None,
                    "up_ask": _ub[1][0], "up_ask_size": _ub[1][1],
                    "up_bid": _ub[0][0], "up_bid_size": _ub[0][1],
                    "down_ask": _db[1][0], "down_ask_size": _db[1][1],
                    "down_bid": _db[0][0], "down_bid_size": _db[0][1],
                    "action": "hold"}

            # --- AC/VR signal strategy (paper A/B of the X-post method) ---
            rho, vr, ac_side = acvr_signal(prices)
            tick["ac_rho"] = round(rho, 3) if rho is not None else None
            tick["ac_vr"] = round(vr, 3) if vr is not None else None
            tick["ac_signal"] = ac_side
            if (ac_side is not None and not win.entered and not win.pos
                    and tau <= 150 and tau >= 30):
                ask, asize = books[ac_side][1]
                if ask is not None and 0.15 <= ask <= 0.92:
                    shares = args.stake / ask
                    if asize >= shares:
                        fees = fee_for(shares, ask, win.fee_rate)
                        win.pos[ac_side] = {"shares": shares, "cost": args.stake, "fees": fees, "price": ask}
                        win.entry_ts = now
                        win.entered = True
                        summary["trades"] += 1
                        tick["action"] = f"BUY {ac_side} @ {ask:.3f} rho={rho:.2f} vr={vr:.2f}"
                        append_jsonl("trades.jsonl", {"ts": tick["ts"], "slug": win.slug, "leg": 1,
                                     "side": ac_side, "price": ask, "shares": round(shares, 3),
                                     "cost": args.stake, "fees": round(fees, 4),
                                     "rho": round(rho, 3), "vr": round(vr, 3), "spot": spot})
                        print(f"[trade] BUY {ac_side} @ {ask:.3f} rho={rho:.2f} vr={vr:.2f} "
                              f"tau={tau:.0f}s {win.slug}", flush=True)

            append_jsonl("ticks.jsonl", tick)
            with open(os.path.join(DATA, "state.json"), "w") as f:
                json.dump({"summary": summary, "last_tick": tick,
                           "open_positions": {win.slug: win.pos} if win.pos else {},
                           "updated": tick["ts"]}, f, indent=1)
        except KeyboardInterrupt:
            print("[paper] stopped by user", flush=True)
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("[warn] HTTP 429 rate limited, backing off 15s", flush=True)
                time.sleep(15)
            else:
                print(f"[warn] loop error: HTTP {e.code}", flush=True)
        except Exception as e:
            print(f"[warn] loop error: {e}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
