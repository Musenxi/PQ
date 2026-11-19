#!/usr/bin/env python3
"""Deep market recorder (read-only; no keys, no orders).

Streams, all stamped with host receipt time (_recv; host is NTP-synced):
  rtds     Polymarket RTDS websocket: crypto_prices_chainlink,
           crypto_prices (Binance), crypto_prices_twap_sixty and
           crypto_prices_twap_thirty for btc/usd -- the twap_sixty
           series is the settlement feed of the BTC up/down markets.
           Batch payloads are expanded into per-point rows.
  clob     CLOB market websocket: full book for both tokens of the
           current and next btc-updown-5m windows, reconstructed in
           memory; one top-10 snapshot row per asset per second.
  trades   every last_trade_price event from the same socket.
  binance  Tokyo Binance aggTrade feed (TCP, AUTH token), raw prints.
  integrity  connect/disconnect events + a 60s heartbeat with
           per-stream message counts (gap accounting; RTDS has no
           history replay, so missed time is gone -- this log is how
           we know what we missed).

Output: data/<stream>-YYYY-MM-DD.jsonl (UTC), one JSON object per line.
Env: FEED_TOKEN (from /etc/paper-snipe.env). No other secrets.
"""
import asyncio
import json
import os
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone

import websockets

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
RTDS_URL = "wss://ws-live-data.polymarket.com"
CLOB_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
GAMMA = "https://gamma-api.polymarket.com/events?slug="
FEED_ADDRS = [("45.129.8.188", 8765), ("2a12:a304:4:533::a", 8765)]
FEED_TOKEN = os.environ.get("FEED_TOKEN", "")
WINDOW = 300

COUNTS = Counter()
QUEUE = asyncio.Queue(maxsize=200000)


def emit(stream, row):
    try:
        QUEUE.put_nowait((stream, row))
    except asyncio.QueueFull:
        COUNTS["dropped:" + stream] += 1


def integrity(event, **kw):
    row = {"ts": time.time(), "event": event}
    row.update(kw)
    emit("integrity", row)


# ---------------------------------------------------------------- writer
async def writer():
    files = {}

    def get_file(stream):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = (stream, day)
        f = files.get(key)
        if f is None:
            for k in [k for k in files if k[0] == stream]:
                files.pop(k).close()
            os.makedirs(DATA_DIR, exist_ok=True)
            f = open(os.path.join(DATA_DIR, "%s-%s.jsonl" % (stream, day)),
                     "a", buffering=1)
            files[key] = f
        return f

    while True:
        stream, row = await QUEUE.get()
        try:
            get_file(stream).write(json.dumps(row) + "\n")
        except Exception as e:
            print("writer error:", e, flush=True)


# ------------------------------------------------------------------ RTDS
RTDS_SUBS = [
    ("crypto_prices_chainlink", "btc/usd"),
    ("crypto_prices", "btcusdt"),
    ("crypto_prices_twap_sixty", "btc/usd"),
    ("crypto_prices_twap_thirty", "btc/usd"),
]


async def rtds_stream():
    backoff = 1
    while True:
        try:
            async with websockets.connect(RTDS_URL, ping_interval=None,
                                          max_size=2 ** 23) as ws:
                subs = [{"topic": t, "type": "update",
                         "filters": json.dumps({"symbol": s})}
                        for t, s in RTDS_SUBS]
                await ws.send(json.dumps({"action": "subscribe",
                                          "subscriptions": subs}))
                integrity("rtds_connect")
                backoff = 1

                async def heartbeat():
                    while True:
                        await asyncio.sleep(5)
                        await ws.send("PING")
                hb = asyncio.create_task(heartbeat())
                try:
                    while True:
                        # RTDS batches arrive ~1/min; >150s of silence
                        # means a half-dead socket -- reconnect (the
                        # on-subscribe history dump backfills the gap).
                        msg = await asyncio.wait_for(ws.recv(), timeout=150)
                        recv = time.time()
                        if msg == "PONG":
                            continue
                        try:
                            d = json.loads(msg)
                        except Exception:
                            COUNTS["rtds:unparsed"] += 1
                            continue
                        topic = d.get("topic", "?")
                        COUNTS["rtds:" + str(topic)] += 1
                        payload = d.get("payload") or {}
                        data = payload.get("data")
                        if isinstance(data, list):
                            for pt in data:
                                row = {"topic": topic,
                                       "ts": pt.get("timestamp"),
                                       "value": pt.get("value"),
                                       "_recv": recv}
                                if pt.get("full_accuracy_value") is not None:
                                    row["fav"] = pt["full_accuracy_value"]
                                emit("rtds", row)
                        else:
                            emit("rtds", {"topic": topic, "payload": payload,
                                          "_recv": recv})
                finally:
                    hb.cancel()
        except Exception as e:
            integrity("rtds_disconnect", error=str(e)[:200])
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


# ------------------------------------------------------------------ CLOB
class Book:
    __slots__ = ("slug", "outcome", "bids", "asks", "last_trade")

    def __init__(self, slug, outcome):
        self.slug = slug
        self.outcome = outcome
        self.bids = {}
        self.asks = {}
        self.last_trade = None


def gamma_tokens(slug):
    req = urllib.request.Request(GAMMA + slug,
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        ev = json.load(r)
    toks = ev[0]["markets"][0]["clobTokenIds"]
    if isinstance(toks, str):
        toks = json.loads(toks)
    return toks


class ClobRecorder:
    def __init__(self):
        self.books = {}          # asset_id -> Book
        self.known_slugs = {}    # slug -> (up_id, down_id)
        self.ws = None

    def window_start(self, t=None):
        t = int(t or time.time())
        return t - (t % WINDOW)

    async def ensure_windows(self):
        cur = self.window_start()
        for start in (cur, cur + WINDOW):
            slug = "btc-updown-5m-%d" % start
            if slug in self.known_slugs:
                continue
            try:
                toks = await asyncio.to_thread(gamma_tokens, slug)
            except Exception as e:
                integrity("gamma_fail", slug=slug, error=str(e)[:120])
                continue
            self.known_slugs[slug] = (toks[0], toks[1])
            for aid, outcome in ((toks[0], "Up"), (toks[1], "Down")):
                if aid not in self.books:
                    self.books[aid] = Book(slug, outcome)
            if self.ws is not None:
                try:
                    await self.ws.send(json.dumps(
                        {"operation": "subscribe", "assets_ids": list(toks)}))
                except Exception:
                    pass
            integrity("window_known", slug=slug)

    def prune(self):
        cutoff = self.window_start() - WINDOW  # keep last window's book
        dead = []
        for slug, toks in list(self.known_slugs.items()):
            if int(slug.rsplit("-", 1)[1]) < cutoff:
                dead.append((slug, toks))
        return dead

    async def snapshot_loop(self):
        while True:
            await asyncio.sleep(1.0)
            recv = time.time()
            for aid, b in self.books.items():
                if not b.bids and not b.asks:
                    continue
                bids = sorted(((float(p), float(s)) for p, s in b.bids.items()),
                              reverse=True)[:10]
                asks = sorted(((float(p), float(s)) for p, s in b.asks.items()))[:10]
                emit("clob", {
                    "slug": b.slug, "asset": aid, "outcome": b.outcome,
                    "_recv": recv,
                    "bid": bids[0][0] if bids else None,
                    "ask": asks[0][0] if asks else None,
                    "bids": bids, "asks": asks, "lt": b.last_trade,
                })

    async def run(self):
        backoff = 1
        asyncio.create_task(self.snapshot_loop())
        while True:
            try:
                await self.ensure_windows()
                ids = [aid for pair in self.known_slugs.values() for aid in pair]
                async with websockets.connect(CLOB_URL, ping_interval=None,
                                              max_size=2 ** 25) as ws:
                    self.ws = ws
                    await ws.send(json.dumps({"assets_ids": ids,
                                              "type": "market",
                                              "initial_dump": True}))
                    integrity("clob_connect", assets=len(ids))
                    backoff = 1

                    async def heartbeat():
                        while True:
                            await asyncio.sleep(10)
                            await ws.send("PING")
                    hb = asyncio.create_task(heartbeat())

                    async def housekeeping():
                        while True:
                            await asyncio.sleep(15)
                            await self.ensure_windows()
                            for slug, toks in self.prune():
                                try:
                                    await ws.send(json.dumps(
                                        {"operation": "unsubscribe",
                                         "assets_ids": list(toks)}))
                                except Exception:
                                    pass
                                for aid in toks:
                                    self.books.pop(aid, None)
                                self.known_slugs.pop(slug, None)
                                integrity("window_pruned", slug=slug)
                    hk = asyncio.create_task(housekeeping())
                    try:
                        while True:
                            msg = await asyncio.wait_for(ws.recv(), timeout=30)
                            recv = time.time()
                            if msg == "PONG":
                                continue
                            try:
                                d = json.loads(msg)
                            except Exception:
                                COUNTS["clob:unparsed"] += 1
                                continue
                            for it in (d if isinstance(d, list) else [d]):
                                self.handle(it, recv)
                    finally:
                        hb.cancel()
                        hk.cancel()
                        self.ws = None
            except Exception as e:
                integrity("clob_disconnect", error=str(e)[:200])
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def handle(self, it, recv):
        if "price_changes" in it:
            COUNTS["clob:price_change"] += 1
            for ch in it["price_changes"]:
                b = self.books.get(ch.get("asset_id"))
                if b is None:
                    continue
                book = b.bids if ch.get("side") == "BUY" else b.asks
                size = float(ch.get("size") or 0)
                if size <= 0:
                    book.pop(ch.get("price"), None)
                else:
                    book[ch.get("price")] = ch.get("size")
        elif "bids" in it and "asks" in it:
            COUNTS["clob:book"] += 1
            b = self.books.get(it.get("asset_id"))
            if b is None:
                return
            b.bids = {x["price"]: x["size"] for x in it["bids"]}
            b.asks = {x["price"]: x["size"] for x in it["asks"]}
        elif it.get("event_type") == "last_trade_price":
            COUNTS["clob:trade"] += 1
            b = self.books.get(it.get("asset_id"))
            row = dict(it)
            row["_recv"] = recv
            if b is not None:
                b.last_trade = float(it["price"])
                row["slug"] = b.slug
                row["outcome"] = b.outcome
            emit("trades", row)


# --------------------------------------------------------------- binance
async def binance_stream():
    backoff = 1
    while True:
        writer_ = reader = None
        try:
            for host, port in FEED_ADDRS:
                try:
                    reader, writer_ = await asyncio.wait_for(
                        asyncio.open_connection(host, port), timeout=8)
                    break
                except Exception:
                    continue
            if writer_ is None:
                raise ConnectionError("feed unreachable")
            if FEED_TOKEN:
                writer_.write(("AUTH " + FEED_TOKEN + "\n").encode())
                await writer_.drain()
            integrity("binance_connect")
            backoff = 1
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=30)
                if not line:
                    raise ConnectionError("feed closed")
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if "p" not in d:
                    continue
                COUNTS["binance"] += 1
                emit("binance", {"p": d["p"], "ts": d.get("ts"),
                                 "_recv": time.time()})
        except Exception as e:
            integrity("binance_disconnect", error=str(e)[:200])
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
        finally:
            if writer_ is not None:
                try:
                    writer_.close()
                except Exception:
                    pass


# -------------------------------------------------------------- heartbeat
async def heartbeat():
    last = Counter()
    while True:
        await asyncio.sleep(60)
        delta = {k: COUNTS[k] - last.get(k, 0) for k in COUNTS}
        last = Counter(COUNTS)
        integrity("heartbeat", counts={k: v for k, v in delta.items() if v},
                  queue=QUEUE.qsize())


async def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    integrity("recorder_start")
    await asyncio.gather(writer(), rtds_stream(), ClobRecorder().run(),
                         binance_stream(), heartbeat())


if __name__ == "__main__":
    asyncio.run(main())
