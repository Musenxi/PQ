#!/usr/bin/env python3
"""tg_report.py -- Telegram reporter for the live execution probe.

Runs on the Azure box next to the probe. Tails the probe's
orders.jsonl / settlements.jsonl (read-only) and pushes one message
per live event to lizi's Telegram: order filled, FOK killed, other
submit errors, and settlements with a running tally. Answers /status
in the configured chat with the current tally + a live CLOB balance
read. Config (TG_BOT_TOKEN, TG_CHAT_ID) lives in /etc/tg-report.env
(mode 600), never in this file. If TG_CHAT_ID is unset the bot runs
in discovery mode: it logs the chat id of any incoming message to
the journal (so the operator can fill it in) and pushes nothing.
"""
import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
STATE = os.path.join(DATA, "tg_report_state.json")
JST = ZoneInfo("Asia/Tokyo")


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


ENV = load_env_file("/etc/tg-report.env")
TOKEN = ENV.get("TG_BOT_TOKEN") or os.environ.get("TG_BOT_TOKEN")
CHAT_ID = ENV.get("TG_CHAT_ID") or os.environ.get("TG_CHAT_ID")

import httpx  # noqa: E402

TG = httpx.Client(base_url=f"https://api.telegram.org/bot{TOKEN}",
                  timeout=httpx.Timeout(35))


def send(text):
    if not CHAT_ID:
        print(f"[tg] (discovery mode, not sent) {text}", flush=True)
        return False
    for attempt in range(3):
        try:
            r = TG.post("/sendMessage", json={
                "chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": True})
            if r.status_code == 200:
                return True
            print(f"[tg] send http {r.status_code}: {r.text[:120]}", flush=True)
        except Exception as e:
            print(f"[tg] send error: {e}", flush=True)
        time.sleep(2 * (attempt + 1))
    return False


# ------------------------------------------------------------------ tally
def read_jsonl(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    out = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def tally():
    orders = [o for o in read_jsonl("orders.jsonl")
              if o.get("disposition") == "submit"]
    fills = [o for o in orders if o.get("filled")]
    kills = [o for o in orders
             if "fully filled" in (o.get("error") or "")]
    others = [o for o in orders if not o.get("filled")
              and "fully filled" not in (o.get("error") or "")]
    settles = read_jsonl("settlements.jsonl")
    pnl = sum(s.get("pnl", 0.0) for s in settles)
    wins = sum(1 for s in settles if s.get("pnl", 0) > 0)
    return {"submits": len(orders), "fills": len(fills), "kills": len(kills),
            "others": len(others),
            "settled": len(settles), "wins": wins, "pnl": pnl}


def positions_value():
    """Mark-to-market value of open/unredeemed positions (public API)."""
    try:
        env = load_env_file("/etc/polymarket-live.env")
        addr = env.get("POLY_FUNDER", "")
        if not addr:
            return None
        r = httpx.get("https://data-api.polymarket.com/v2/value",
                      params={"user": addr}, timeout=15)
        return float(r.json()["data"]["value"])
    except Exception as e:
        print(f"[tg] positions value failed: {e}", flush=True)
        return None


def live_balance():
    """One-off CLOB balance read with the probe's creds (SDK)."""
    try:
        env = load_env_file("/etc/paper-snipe.env")
        env.update(load_env_file("/etc/polymarket-live.env"))
        from polymarket import SecureClient
        from polymarket.auth import RelayerApiKey
        rk = RelayerApiKey(key=env["RELAYER_API_KEY"],
                           address=env["RELAYER_API_KEY_ADDRESS"])
        c = SecureClient.create(private_key=env["POLY_PK"],
                                wallet=env["POLY_FUNDER"], api_key=rk)
        bal = c.get_balance_allowance(asset_type="COLLATERAL")
        c.close()
        v = bal.balance if hasattr(bal, "balance") else bal
        return int(v) / 1e6
    except Exception as e:
        print(f"[tg] balance read failed: {e}", flush=True)
        return None


def status_text():
    t = tally()
    cash = live_balance()
    pos = positions_value()
    if cash is not None and pos is not None:
        bal_s = (f"现金 ${cash:.2f} · 持仓 ${pos:.2f} · "
                 f"总权益 <b>${cash + pos:.2f}</b>")
    elif cash is not None:
        bal_s = f"现金 <b>${cash:.2f}</b>（持仓读取失败）"
    else:
        bal_s = "读取失败"
    return (f"📊 <b>实盘探针状态</b>\n"
            f"{bal_s}\n"
            f"累计：提交 {t['submits']} · 成交 {t['fills']} · 被杀 {t['kills']}"
            f" · 未达交易所 {t['others']}\n"
            f"已结算 {t['settled']} 笔（{t['wins']} 胜）· 账本净盈亏 "
            f"<b>{t['pnl']:+.2f}</b>")


# ------------------------------------------------------------------ events
def win_hhmm(slug):
    try:
        ts = int(slug.rsplit("-", 1)[1])
        return datetime.fromtimestamp(ts, tz=JST).strftime("%H:%M")
    except Exception:
        return slug


def fmt_order(o):
    hhmm = win_hhmm(o["slug"])
    side = o.get("side")
    ask = o.get("ask")
    usd = o.get("usd")
    lat = o.get("post_latency_ms")
    lat_s = f" · 提交 {lat:.0f}ms" if lat else ""
    if o.get("filled"):
        fs = o.get("filled_shares") or 0
        fc = o.get("filled_cost") or 0
        px = fc / fs if fs else ask
        slip = o.get("slippage")
        slip_s = f"（滑点 {slip:+.2f}）" if slip is not None else ""
        return (f"✅ <b>成交</b> {hhmm} 窗 · {side} @{px:.2f}"
                f"（报价 {ask}）{slip_s}\n"
                f"${fc:.2f} · {fs:.2f} 股{lat_s}")
    err = o.get("error") or ""
    if "fully filled" in err:
        return (f"❌ <b>FOK 被杀</b> {hhmm} 窗 · {side} @{ask} · ${usd:.2f}\n"
                f"报价未存活到成交{lat_s}")
    if o.get("disposition") == "submit":
        return (f"⚠️ <b>提交失败</b> {hhmm} 窗 · {side} @{ask} · ${usd:.2f}\n"
                f"{err[:80]}{lat_s}")
    return None


def fmt_settle(s, upto=None):
    """Cumulative line counts settlements up to and including this one
    (file order), so a catch-up batch after a restart stays truthful."""
    settles = read_jsonl("settlements.jsonl")
    if upto is None:
        upto = len(settles)
    sub = settles[:upto]
    pnl = sum(x.get("pnl", 0.0) for x in sub)
    return (f"🏁 <b>结算</b> {win_hhmm(s['slug'])} 窗 · {s.get('side')} "
            f"{'赢' if s.get('winner') == s.get('side') else '输'} "
            f"<b>{s.get('pnl', 0):+.2f}</b>\n"
            f"累计已结算 {len(sub)} 笔 · 净 {pnl:+.2f}")


# ------------------------------------------------------------------ tailing
def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:
            pass
    # first run: start from current EOF, do not replay history
    st = {}
    for name in ("orders.jsonl", "settlements.jsonl"):
        p = os.path.join(DATA, name)
        st[name] = os.path.getsize(p) if os.path.exists(p) else 0
    return st


def save_state(st):
    with open(STATE, "w") as f:
        json.dump(st, f)


def drain_new(st, name):
    """Return new complete rows appended since the saved byte offset."""
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    off = st.get(name, 0)
    size = os.path.getsize(p)
    if size < off:  # file rotated/truncated: restart from 0
        off = 0
    if size == off:
        return []
    with open(p, "rb") as f:
        f.seek(off)
        chunk = f.read()
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return []
    st[name] = off + last_nl + 1
    rows = []
    for line in chunk[:last_nl].decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


# ------------------------------------------------------------------ /status
def poll_updates():
    """Long-poll getUpdates; answer /status from the configured chat.
    In discovery mode, log any sender's chat id to the journal."""
    offset = None
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            r = TG.get("/getUpdates", params=params)
            if r.status_code != 200:
                time.sleep(5)
                continue
            for upd in r.json().get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat = (msg.get("chat") or {}).get("id")
                text = (msg.get("text") or "").strip()
                if chat is None:
                    continue
                if not CHAT_ID:
                    print(f"[tg] discovery: message from chat_id={chat} "
                          f"text={text[:30]!r}", flush=True)
                    continue
                if str(chat) != str(CHAT_ID):
                    continue
                if text.startswith("/status") or text == "状态":
                    send(status_text())
        except Exception as e:
            print(f"[tg] poll error: {e}", flush=True)
            time.sleep(5)


def main():
    if not TOKEN:
        print("[tg] no TG_BOT_TOKEN configured; exiting", flush=True)
        return
    import threading
    threading.Thread(target=poll_updates, daemon=True).start()
    st = load_state()
    save_state(st)
    print(f"[tg] reporter up; chat={'set' if CHAT_ID else 'DISCOVERY'}",
          flush=True)
    send("🟢 <b>实盘播报已上线</b>（Azure 都柏林）\n" + status_text())
    while True:
        try:
            for o in drain_new(st, "orders.jsonl"):
                m = fmt_order(o)
                if m:
                    send(m)
            new_settles = drain_new(st, "settlements.jsonl")
            if new_settles:
                total = len(read_jsonl("settlements.jsonl"))
                first_idx = total - len(new_settles) + 1
                for i, s in enumerate(new_settles):
                    send(fmt_settle(s, upto=first_idx + i))
            save_state(st)
        except Exception as e:
            print(f"[tg] tail error: {e}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    main()
