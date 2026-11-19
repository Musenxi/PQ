#!/usr/bin/env python3
"""live_probe_1h.py -- LIVE execution probe for the FAIR 1h signal.

Authorized by lizi 2026-11-19 ~22:49 JST ("实盘测试一下") after he
reviewed the 1h paper line (9 windows, +$91.72 family sum, 95% CI
[-1.80, +24.91] -- includes zero; pre-fee-flip data, pipeline
validation only under the probe's own pre-registered read, which
needs >=100 settled post-flip windows and >=5 days post-flip).
Purpose, same as the 5m probe: measure execution reality on the
thin 1h book (fill rate, slippage, quote survival) with $1.50
orders capped at $5 -- NOT a strategy validation or deployment.

Signal: farm1h FAIR, config fair-05 (gap >= 0.06, tau_min 300,
band [0.15, 0.92] -- the family median gap), pre-open basis
averaged over <=8 prior windows, TWAP-aware fair, no entries in
the first 60 s of a window, at most one order per window.
Settlement ONLY from Gamma's official resolution (same code as
the patched 5m probe). Fee note: the 1h taker rate is 0.07 until
2026-11-21 08:59 JST, then 0.01; the window loader reads the
market's live feeSchedule either way.

Order machinery, caps, ARMED/STOP gates and ledger are inherited
unchanged from live_probe.py (5m). This probe lives in its own
directory (/root/polymarket-live1h) with its own data/ and gates;
the 5m probe (paused) is untouched.
"""
import ast
import json
import math
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

BINANCE = "https://data-api.binance.vision"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
PM_WEB = "https://polymarket.com"
UA = {"User-Agent": "Mozilla/5.0 (live-probe)"}

# ------------------------------------------------------------ hard caps
ORDER_USD = 1.50          # target size per order
MAX_ORDER_USD = 5.00      # hard per-order CAP (lizi clarified 2026-11-19
                          # ~16:23 JST: a cap, not a fixed $5 size).
                          # History: $2.00 at launch -> $2.50 (~16:13 JST)
                          # -> $5.00 cap (~16:20 JST), each step after
                          # the 5-share minimum blocked FAIR signals.
MAX_ORDERS_DAY = 1000000  # count cap removed at lizi instruction 2026-11-19; spend caps remain
MAX_SPEND_DAY = 1000000.0  # daily spend cap removed at lizi instruction 2026-11-19 ~18:59 JST; per-order $5 cap and the account balance remain the bounds
GAP_MIN = 0.06            # farm1h fair-05: the FAIR 1h family median gap
TAU_MIN = 300             # farm1h fair-05: entries only while tau >= 300 s
BAND = (0.15, 0.92)       # farm1h fair-05 band
ENTRY_DELAY_S = 60        # farm1h: no fair-anchored entries in the first 60 s
MAX_WINDOW_USD = 15.00    # per-window spend cap (lizi, 2026-11-19
                          # ~23:11 JST): filled cost summed over the
                          # window may not exceed $15
MIN_RETRY_S = 60          # per-window order count is UNLIMITED (lizi,
                          # 2026-11-19 ~23:03 JST); this cooldown only
                          # stops the loop machine-gunning while one
                          # signal persists. Per-order $5 cap and the
                          # balance bound are unchanged.
STALE_BOOK_MS = 1000
FUTURE_BOOK_MS = -2000


_HTTP = None


def _http():
    """One pooled httpx client for ALL of the probe's own HTTP (book
    polls, Gamma window loads, settlement checks): connections are
    reused across the 2 s loop instead of a fresh TCP+TLS handshake
    per request (urllib). Added 2026-11-19 at lizi's instruction."""
    global _HTTP
    if _HTTP is None:
        import httpx
        _HTTP = httpx.Client(
            timeout=12,
            limits=httpx.Limits(max_connections=16,
                                max_keepalive_connections=8,
                                keepalive_expiry=60),
        )
    return _HTTP


def http_json(url, timeout=12):
    r = _http().get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fee_for(shares, price, rate):
    return shares * rate * price * (1.0 - price)


def best_levels(book):
    bids = [(float(b["price"]), float(b["size"])) for b in book.get("bids", [])]
    asks = [(float(a["price"]), float(a["size"])) for a in book.get("asks", [])]
    best_bid = max(bids) if bids else (None, 0.0)
    best_ask = min(asks) if asks else (None, 0.0)
    return best_bid, best_ask


def would_reject_age(age_ms):
    return age_ms is None or age_ms > STALE_BOOK_MS or age_ms < FUTURE_BOOK_MS


def append_jsonl(name, row):
    with open(os.path.join(DATA, name), "a") as f:
        f.write(json.dumps(row) + "\n")


def read_jsonl(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]


def load_env_file(path):
    out = {}
    if path and os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    return out


# ------------------------------------------------------------------ window
class Window:
    def __init__(self, start_ts):
        self.start = start_ts
        self.end = start_ts + 3600
        self.slug = f"btc-updown-1h-{start_ts}"
        self.token = {}
        self.open_price = None
        self.fee_rate = 0.07
        self.min_size = 5.0
        self.tick = "0.01"
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
        if m.get("orderMinSize"):
            self.min_size = float(m["orderMinSize"])
        if m.get("orderPriceMinTickSize"):
            self.tick = str(m["orderPriceMinTickSize"])
        cp = http_json(f"{PM_WEB}/api/crypto/crypto-price?" + urllib.parse.urlencode(
            {"symbol": "BTC", "variant": "hourly", "eventStartTime": self.start}))
        if cp.get("openPrice"):
            self.open_price = float(cp["openPrice"])
        self.loaded = self.open_price is not None
        return self.loaded

    def settlement(self):
        # Settle ONLY on the official resolution: Gamma's
        # outcomePrices are what the CLOB actually pays on. The
        # crypto-price endpoint's close print disagreed with the
        # official resolution on the near-tie window 1795084200
        # (2026-11-19: close-open = +$5.87 said Up, the market
        # resolved Down) and the probe booked a phantom +$1.43 win;
        # lizi caught it from his app. Returning None keeps the
        # position pending until Gamma marks the market closed with
        # a decisive price pair.
        try:
            ev = http_json(f"{GAMMA}/events?slug={self.slug}")
            if ev:
                m = ev[0]["markets"][0]
                _st = m.get("umaResolutionStatus")
                if _st and _st != "resolved":
                    return None  # prices still provisional (UMA proposal)
                if m.get("closed") and m.get("outcomePrices"):
                    outs = ast.literal_eval(m["outcomes"])
                    prices = [float(x) for x in
                              ast.literal_eval(m["outcomePrices"])]
                    if max(prices) >= 0.999 and sum(prices) <= 1.001:
                        return outs[prices.index(max(prices))], None, None
        except Exception:
            pass
        return None


# -------------------------------------------------------------------- feed
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


# ------------------------------------------------------------- daily ledger
class Ledger:
    """Persisted daily caps + per-window traded set + open positions."""

    def __init__(self):
        self.path = os.path.join(DATA, "probe_state.json")
        self.day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.orders_today = 0
        self.spent_today = 0.0
        self.traded_windows = set()
        self.open_orders = []      # order rows awaiting settlement
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                s = json.load(open(self.path))
                if s.get("day") == self.day:
                    self.orders_today = s.get("orders_today", 0)
                    self.spent_today = s.get("spent_today", 0.0)
                self.traded_windows = set(s.get("traded_windows", []))
                self.open_orders = s.get("open_orders", [])
            except Exception:
                pass

    def save(self):
        with open(self.path, "w") as f:
            json.dump({"day": self.day, "orders_today": self.orders_today,
                       "spent_today": round(self.spent_today, 4),
                       "traded_windows": sorted(self.traded_windows),
                       "open_orders": self.open_orders}, f, indent=1)

    def roll_day(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self.day:
            self.day = today
            self.orders_today = 0
            self.spent_today = 0.0
            self.save()


# ------------------------------------------------------------------- client
def build_client(env):
    """Unified V2 SDK (polymarket-client). The V1 py-clob-client is
    archived and its orders are rejected by CLOB V2."""
    pk = env.get("POLY_PK") or os.environ.get("POLY_PK")
    if not pk:
        return None
    from polymarket import SecureClient
    from polymarket.auth import RelayerApiKey
    api_key = None
    if env.get("RELAYER_API_KEY"):
        api_key = RelayerApiKey(key=env["RELAYER_API_KEY"],
                                address=env["RELAYER_API_KEY_ADDRESS"])
    return SecureClient.create(private_key=pk,
                               wallet=env.get("POLY_FUNDER") or None,
                               api_key=api_key)


def _dump(obj):
    try:
        return obj.model_dump(mode="json")
    except Exception:
        return {"repr": repr(obj)}


def post_fok_buy(client, token_id, price, shares, tick=None):
    """FOK market buy capped at the quoted ask: fills in full at an
    average price <= ask, or is rejected -- the quote-survival test.

    The V2 SDK denominates BUY market orders by `amount` (pUSD spend),
    not shares: passing shares= raises 'amount is required for BUY
    market orders' client-side, which killed the first two live
    attempts (2026-11-19 16:15/16:25 JST) before anything reached the
    exchange. amount = shares x price reproduces the intended spend.
    """
    t0 = time.time()
    resp = client.place_market_order(token_id=token_id, side="BUY",
                                     amount=round(shares * price, 2),
                                     max_price=price, order_type="FOK")
    return resp, (time.time() - t0) * 1000.0


# --------------------------------------------------------------------- main
def main():
    feed_spec = "[2a12:a304:4:533::a]:8765,45.129.8.188:8765"
    env = load_env_file("/etc/paper-snipe.env")
    env.update(load_env_file("/etc/polymarket-live.env"))
    if "--feed" in sys.argv:
        feed_spec = sys.argv[sys.argv.index("--feed") + 1]
    feed = FeedClient(feed_spec, token=env.get("FEED_TOKEN") or os.environ.get("FEED_TOKEN"))
    feed.start()

    client = None
    try:
        client = build_client(env)
    except Exception as e:
        print(f"[live] client build failed: {e}", flush=True)
    armed = client is not None and os.path.exists(os.path.join(HERE, "ARMED"))
    print(f"[live] probe up: client={'yes' if client else 'DRY'} armed={armed}", flush=True)

    ledger = Ledger()
    prices = deque()
    basis_samples = deque(maxlen=8)
    win = None
    warmed_slug = None
    last_hb = 0.0
    last_try = 0.0
    window_spent = 0.0      # filled cost in the current window
    pending_settle = {(o.get("key") or o["slug"]): o for o in ledger.open_orders}

    while True:
        try:
            now = time.time()
            ledger.roll_day()

            # settle any finished positions
            for k in list(pending_settle):
                o = pending_settle[k]
                slug = o["slug"]
                if now < o["end"] + 20:
                    continue
                try:
                    w = Window(int(slug.rsplit("-", 1)[1]))
                    st = w.settlement()
                except Exception:
                    st = None
                if st:
                    winner = st[0]
                    won = winner == o["side"]
                    payout = o["filled_shares"] if won else 0.0
                    pnl = payout - o["filled_cost"] - o["fee_est"]
                    row = {"slug": slug, "side": o["side"], "winner": winner,
                           "filled_shares": o["filled_shares"],
                           "filled_cost": o["filled_cost"], "fee_est": o["fee_est"],
                           "pnl": round(pnl, 4),
                           "settled_at": datetime.now(timezone.utc).isoformat()}
                    append_jsonl("settlements.jsonl", row)
                    print(f"[settle] {slug} {o['side']} winner={winner} pnl={pnl:+.2f}", flush=True)
                    del pending_settle[k]
                    ledger.open_orders = [x for x in ledger.open_orders
                                          if (x.get("key") or x["slug"]) != k]
                    ledger.save()

            wstart = int(now // 3600) * 3600
            if win is None or win.start != wstart:
                win = Window(wstart)
                last_try = 0.0
                window_spent = sum(o["filled_cost"] for o in ledger.open_orders
                                     if o["slug"] == win.slug)
                try:
                    win.load()
                    print(f"[window] {win.slug} open={win.open_price} min_size={win.min_size} tick={win.tick}", flush=True)
                except Exception as e:
                    print(f"[window] load failed {e}", flush=True)
            if win is not None and not win.loaded:
                try:
                    win.load()
                except Exception:
                    pass
            # Pre-warm the SDK's order-metadata cache for this window's
            # tokens (condition + market info, ~60 ms of GETs) so a
            # signal later in the window does not pay it inside the
            # place flow. The POST /order itself (~190 ms) is exchange
            # matching time and cannot be cached away. 2026-11-19.
            if client is not None and win is not None and win.loaded \
                    and win.slug != warmed_slug:
                try:
                    for tok in win.token.values():
                        client._ctx.order_metadata.resolve_market(
                            client._ctx, token_id=tok)
                    warmed_slug = win.slug
                except Exception:
                    pass

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

            if win.open_price and not win.basis_sampled:
                pre = [p for t, p in prices if win.start - 15 <= t < win.start - 1]
                if pre:
                    basis_samples.append(sum(pre) / len(pre) - win.open_price)
                    win.basis_sampled = True
            if basis_samples:
                win.basis = sum(basis_samples) / len(basis_samples)
            if win.basis is None or not win.loaded:
                if now - last_hb > 30:
                    last_hb = now
                    print(f"[hb-gate] {win.slug} loaded={win.loaded} basis={win.basis} "
                          f"sampled={win.basis_sampled} prices={len(prices)} spot={spot}", flush=True)
                time.sleep(2)
                continue
            s_est = spot - win.basis

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
            if tau >= 60:
                exp_twap = s_est
                var_f = tau - 40.0
            else:
                elapsed = 60.0 - tau
                tw = [p - win.basis for t, p in prices if t >= win.end - 60]
                realised = sum(tw) / len(tw) if tw else s_est
                exp_twap = (realised * elapsed + s_est * tau) / 60.0
                var_f = tau ** 3 / (3.0 * 60.0 * 60.0)
            z = math.log(exp_twap / win.open_price) / (sigma * math.sqrt(max(var_f, 1e-6)))
            fair_up = min(max(norm_cdf(z), 0.001), 0.999)
            fairs = {"Up": fair_up, "Down": 1.0 - fair_up}

            # fetch both books with receipt-age (farm v2.0.1 method)
            books, meta = {}, {}
            for side in ("Up", "Down"):
                tok = win.token.get(side)
                if not tok:
                    continue
                try:
                    bk = http_json(f"{CLOB}/book?token_id={tok}", timeout=8)
                    ts_ms = int(bk.get("timestamp") or 0)
                    age_ms = int(time.time() * 1000) - ts_ms if ts_ms else None
                    books[side] = best_levels(bk)
                    meta[side] = {"age_ms": age_ms, "hash": bk.get("hash"),
                                  "stale": would_reject_age(age_ms)}
                except Exception:
                    books[side] = ((None, 0.0), (None, 0.0))
                    meta[side] = {"age_ms": None, "hash": None, "stale": True}

            if now - last_hb > 30:
                last_hb = now
                g_up = round(fairs["Up"] - books["Up"][1][0], 3) if books.get("Up") and books["Up"][1][0] else None
                g_dn = round(fairs["Down"] - books["Down"][1][0], 3) if books.get("Down") and books["Down"][1][0] else None
                print(f"[hb] {win.slug} basis={win.basis:.1f} spot={spot:.1f} fair_up={fair_up:.3f} "
                      f"gap_up={g_up} gap_dn={g_dn} tau={tau:.0f}", flush=True)

            # FAIR decision (fair-05); entries per window unlimited
            # (lizi, 2026-11-19 ~23:03 JST) with a 60 s cooldown
            if now - win.start >= ENTRY_DELAY_S and tau >= TAU_MIN \
                    and now - last_try >= MIN_RETRY_S:
                best = None
                for s in ("Up", "Down"):
                    if s not in books:
                        continue
                    ask = books[s][1][0]
                    if ask is None or not (BAND[0] <= ask <= BAND[1]):
                        continue
                    gap = fairs[s] - ask
                    if best is None or gap > best[0]:
                        best = (gap, s, ask)
                if best and best[0] >= GAP_MIN:
                    gap, side, ask = best
                    sig_row = {"ts": datetime.now(timezone.utc).isoformat(),
                               "slug": win.slug, "side": side,
                               "fair": round(fairs[side], 3), "gap": round(gap, 3),
                               "ask": ask, "book_age_ms": meta[side]["age_ms"],
                               "book_stale": meta[side]["stale"],
                               "basis": round(win.basis, 1),
                               "offset_s": round(now - win.start, 1), "tau": round(tau)}
                    shares = round(ORDER_USD / ask, 2)
                    bumped = False
                    if shares < win.min_size:
                        shares = win.min_size
                        bumped = True
                    usd = round(shares * ask, 4)
                    sig_row.update({"shares": shares, "usd": usd, "min_bumped": bumped})
                    stopped = os.path.exists(os.path.join(HERE, "STOP"))
                    if stopped:
                        sig_row["disposition"] = "stopped"
                    elif usd > MAX_ORDER_USD:
                        sig_row["disposition"] = "skipped_min_size"
                    elif window_spent + usd > MAX_WINDOW_USD:
                        sig_row["disposition"] = "skipped_window_cap"
                    elif ledger.orders_today >= MAX_ORDERS_DAY or \
                            ledger.spent_today + usd > MAX_SPEND_DAY:
                        sig_row["disposition"] = "skipped_cap"
                    elif client is None or not armed:
                        sig_row["disposition"] = "dry"
                    else:
                        sig_row["disposition"] = "submit"
                        orow = dict(sig_row)
                        try:
                            resp, lat_ms = post_fok_buy(client, win.token[side], ask, shares)
                            orow["post_latency_ms"] = round(lat_ms, 1)
                            d = _dump(resp)
                            orow["resp"] = d
                            accepted = type(resp).__name__ == "AcceptedOrder"
                            orow["accepted"] = accepted
                            oid = d.get("order_id") or d.get("orderID") or d.get("id")
                            orow["order_id"] = oid
                            orow["filled"] = False
                            if accepted:
                                # FOK accepted == filled in full at <= max_price.
                                # AcceptedOrder carries making_amount (pUSD
                                # spent) and taking_amount (shares received).
                                fshares, fprice = shares, None
                                if d.get("taking_amount"):
                                    fshares = float(d["taking_amount"])
                                if d.get("making_amount") and fshares:
                                    orow["filled_cost"] = round(float(d["making_amount"]), 4)
                                    fprice = orow["filled_cost"] / fshares
                                if fprice is None:
                                    for _try in range(3):
                                        try:
                                            od = _dump(client.get_order(oid)) if oid else {}
                                            orow["order_detail"] = od
                                            if od.get("size_matched"):
                                                fshares = float(od["size_matched"])
                                            if od.get("price"):
                                                fprice = float(od["price"])
                                            if fprice:
                                                break
                                        except Exception as e:
                                            orow["order_detail_error"] = str(e)
                                        time.sleep(2)
                                orow["filled"] = fshares > 0
                                if fshares > 0:
                                    window_spent += orow["filled_cost"]
                                orow["filled_shares"] = fshares
                                if fprice:
                                    orow["filled_cost"] = round(fshares * fprice, 4)
                                    orow["slippage"] = round(fprice - ask, 4)
                                else:
                                    # upper-bound placeholder until trades reconcile
                                    orow["filled_cost"] = round(fshares * ask, 4)
                                    orow["cost_is_upper_bound"] = True
                                orow["fee_est"] = round(fee_for(fshares, fprice or ask, win.fee_rate), 4)
                                orow["end"] = win.end
                                ledger.spent_today += orow["filled_cost"]
                                orow["key"] = f"{win.slug}#{int(now * 1000)}"
                                ledger.open_orders.append(
                                    {kk: orow[kk] for kk in ("key", "slug", "side", "filled_shares",
                                                             "filled_cost", "fee_est", "end")})
                                pending_settle[orow["key"]] = orow
                                print(f"[order] ACCEPTED {win.slug} {side} {fshares} sh "
                                      f"price={fprice} (ask {ask})", flush=True)
                            else:
                                print(f"[order] REJECTED {win.slug} {side} resp={d}", flush=True)
                            ledger.orders_today += 1
                        except Exception as e:
                            orow["error"] = str(e)
                            ledger.orders_today += 1
                            print(f"[order] ERROR {win.slug} {side}: {e}", flush=True)
                        append_jsonl("orders.jsonl", orow)
                        ledger.save()
                    append_jsonl("signals.jsonl", sig_row)
                    # every disposition starts the cooldown; after
                    # MIN_RETRY_S a fresh signal in the same window
                    # may fire again (unlimited entries per window)
                    last_try = now
                    ledger.save()
            time.sleep(2)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[warn] loop error: {e}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    main()
