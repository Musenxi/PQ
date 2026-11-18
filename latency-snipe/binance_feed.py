#!/usr/bin/env python3
"""
Binance spot price feed / relay — runs on the Tokyo node (v0.5).

Purpose: the paper-snipe collector sits in Amsterdam, ~2ms from
Polymarket but ~235ms RTT from Binance (whose public data service is
served from the Tokyo direction; a REST poll with a fresh TLS
connection costs ~0.93s from Amsterdam). This feed sits next to
Binance instead:

  - subscribes to Binance aggTrade over a persistent WebSocket
    (data-stream.binance.vision), falling back to REST polls of
    data-api.binance.vision whenever the socket is stale;
  - republishes every price on a local TCP port as newline-delimited
    JSON: {"p": 64123.45, "ts": 1794912000.123, "src": "ws", "seq": 42}
    where ts is the feed node's own clock at publish time;
  - the Amsterdam collector connects with --feed <host>:<port> and
    consumes the stream (one-way Tokyo->Amsterdam ~115ms), keeping its
    REST polling as an automatic fallback if the feed goes silent.

Pure Python stdlib (the WebSocket client below is hand-rolled: no
extensions, handles ping/pong, fragmentation and reconnects).

Security: if the env var FEED_TOKEN is set, clients must send
"AUTH <token>" as their first line. Even with a token, restrict the
port in the security group to the collector server's IP — the token
is a seatbelt, not a wall.

Usage:
  FEED_TOKEN=... python3 binance_feed.py [--port 8765] [--bind 0.0.0.0]
"""
import argparse, base64, hashlib, json, os, socket, ssl, struct, sys, threading, time
import urllib.request

REST = "https://data-api.binance.vision"
UA = {"User-Agent": "Mozilla/5.0 (paper-feed)"}


# ---------------------------------------------------------------- state
class FeedState:
    def __init__(self):
        self.cond = threading.Condition()
        self.price = None
        self.ts = 0.0
        self.src = None
        self.seq = 0

    def publish(self, price, src):
        with self.cond:
            self.price = price
            self.ts = time.time()
            self.src = src
            self.seq += 1
            self.cond.notify_all()

    def snapshot(self):
        with self.cond:
            return self.price, self.ts, self.src, self.seq


STATE = FeedState()


# ------------------------------------------------------- minimal WS client
class WSClient:
    """Just enough RFC 6455 for Binance public streams: text/binary
    messages, fragmentation, ping->pong (masked, as clients must),
    close. No extensions."""

    def __init__(self, host, path):
        self.host = host
        self.path = path
        self.sock = None
        self.buf = b""

    def connect(self):
        raw = socket.create_connection((self.host, 443), timeout=15)
        ctx = ssl.create_default_context()
        self.sock = ctx.wrap_socket(raw, server_hostname=self.host)
        self.sock.settimeout(30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {self.path} HTTP/1.1\r\nHost: {self.host}\r\n"
               f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        resp = self._read_until(b"\r\n\r\n").decode("latin1")
        if "101" not in resp.split("\r\n", 1)[0]:
            raise ConnectionError(f"WS handshake failed: {resp.splitlines()[0] if resp else 'empty'}")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if accept not in resp:
            raise ConnectionError("WS handshake: bad Sec-WebSocket-Accept")

    def _read_until(self, marker):
        while marker not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("socket closed during handshake")
            self.buf += chunk
        head, self.buf = self.buf.split(marker, 1)
        return head + marker

    def _read_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        ln = len(payload)
        if ln < 126:
            header += bytes([0x80 | ln])
        elif ln < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", ln)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", ln)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def messages(self):
        """Yield complete message payloads (str) until the socket dies."""
        frags = []
        while True:
            b0, b1 = self._read_exact(2)
            fin = b0 & 0x80
            opcode = b0 & 0x0F
            masked = b1 & 0x80
            ln = b1 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._read_exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else None
            payload = self._read_exact(ln)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 9:            # ping -> pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 8:            # close
                raise ConnectionError("WS closed by server")
            if opcode in (1, 2):       # text / binary
                frags.append(payload)
                if fin:
                    yield b"".join(frags).decode("utf-8", "replace")
                    frags = []
            # opcode 0 (continuation) is handled by the frags accumulation


def ws_producer(symbol, ws_host):
    path = f"/ws/{symbol.lower()}@aggTrade"
    backoff = 1.0
    while True:
        try:
            ws = WSClient(ws_host, path)
            ws.connect()
            print(f"[feed] WS connected {ws_host}{path}", flush=True)
            backoff = 1.0
            for msg in ws.messages():
                try:
                    d = json.loads(msg)
                    price = float(d["p"])
                except Exception:
                    continue
                STATE.publish(price, "ws")
        except Exception as e:
            print(f"[feed] WS error: {e}; reconnect in {backoff:.0f}s", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


def rest_producer(symbol, stale_after=2.0, interval=0.25):
    url = f"{REST}/api/v3/ticker/price?symbol={symbol}"
    while True:
        _, ts, _, _ = STATE.snapshot()
        if time.time() - ts > stale_after:
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=5) as r:
                    price = float(json.loads(r.read())["price"])
                STATE.publish(price, "rest")
            except Exception as e:
                print(f"[feed] REST fallback error: {e}", flush=True)
        time.sleep(interval)


# ---------------------------------------------------------------- server
def client_thread(conn, addr, token):
    try:
        if token:
            conn.settimeout(10)
            line = b""
            while not line.endswith(b"\n"):
                chunk = conn.recv(1024)
                if not chunk:
                    return
                line += chunk
            if line.strip() != f"AUTH {token}".encode():
                conn.sendall(b'{"error":"auth"}\n')
                return
        conn.settimeout(None)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        last_seq = 0
        while True:
            with STATE.cond:
                while STATE.seq == last_seq:
                    if not STATE.cond.wait(timeout=15):
                        break  # heartbeat below even without updates
                price, ts, src, seq = STATE.price, STATE.ts, STATE.src, STATE.seq
            if price is not None and seq != last_seq:
                conn.sendall((json.dumps({"p": price, "ts": ts, "src": src, "seq": seq}) + "\n").encode())
                last_seq = seq
            else:
                conn.sendall(b'{"hb":1}\n')  # heartbeat: proves the link is alive
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--ws-host", default="data-stream.binance.vision")
    args = ap.parse_args()

    token = os.environ.get("FEED_TOKEN") or None
    threading.Thread(target=ws_producer, args=(args.symbol, args.ws_host), daemon=True).start()
    threading.Thread(target=rest_producer, args=(args.symbol,), daemon=True).start()

    def accept_loop(srv):
        while True:
            conn, addr = srv.accept()
            print(f"[feed] client {addr}", flush=True)
            threading.Thread(target=client_thread, args=(conn, addr, token), daemon=True).start()

    # IPv6 listener (Amsterdam<->Tokyo measured ~11ms faster over IPv6;
    # the collector prefers it and falls back to IPv4).
    try:
        srv6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        srv6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        except Exception:
            pass
        srv6.bind(("::", args.port))
        srv6.listen(16)
        threading.Thread(target=accept_loop, args=(srv6,), daemon=True).start()
        print(f"[feed] IPv6 listening on [::]:{args.port}", flush=True)
    except Exception as e:
        print(f"[feed] IPv6 listener unavailable: {e}", flush=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.bind, args.port))
    srv.listen(16)
    print(f"[feed] serving {args.symbol} on {args.bind}:{args.port} (auth {'on' if token else 'off'})", flush=True)
    accept_loop(srv)


if __name__ == "__main__":
    main()
