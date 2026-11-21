#!/usr/bin/env python3
"""farm_report_tg.py -- half-hourly paper-farm scorecard to Telegram.

Runs on the VPS next to the farm data. Every 10 minutes it aggregates
the shadow farm (family x window, Gamma-corrected ledger) plus the
BTC 1h probe and pushes one compact Chinese scorecard to the same
Telegram chat the live-probe bot reports to. Config (TG_BOT_TOKEN,
TG_CHAT_ID) is read from /etc/tg-report.env (mode 600) -- the same
bot, a second sender. Read-only against the farm's data files.
"""
import json
import os
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta

ENV = {}
try:
    for line in open("/etc/tg-report.env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            ENV[k.strip()] = v.strip()
except OSError:
    pass
TOKEN = ENV.get("TG_BOT_TOKEN") or os.environ.get("TG_BOT_TOKEN")
CHAT = ENV.get("TG_CHAT_ID") or os.environ.get("TG_CHAT_ID")

FARM = "/root/polymarket-farm2/data"  # band farm (farm2) since 2026-11-21; the old
# farm is no longer reported (lizi instruction)
FARM1H = "/root/polymarket-farm1h/data"
JST = timezone(timedelta(hours=9))
INTERVAL_S = 600


def read_jsonl(path):
    out = []
    try:
        for line in open(path):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def fam_stats(data_dir):
    """family -> (windows, total_pnl) with family x window aggregation."""
    rows = read_jsonl(os.path.join(data_dir, "settlements.jsonl"))
    win = defaultdict(float)
    for r in rows:
        fam = r["account"].split("-")[0].upper()
        win[(fam, r["slug"])] += float(r.get("pnl", 0))
    agg = defaultdict(lambda: [0, 0.0])
    for (fam, slug), v in win.items():
        agg[fam][0] += 1
        agg[fam][1] += v
    return agg


def mval_split():
    """MVAL decomposition: locked-pair pnl vs residual directional pnl,
    over settled (account, window) pairs. Pairs are worth exactly $1
    at settlement, so locked = pair_shares - pair_cost - pair_fees."""
    trades = read_jsonl(os.path.join(FARM, "trades.jsonl"))
    setts = read_jsonl(os.path.join(FARM, "settlements.jsonl"))
    settled = {(r["account"], r["slug"]): float(r.get("pnl", 0))
               for r in setts if r["account"].startswith("mval")}
    per = defaultdict(lambda: {"Up": [0.0, 0.0, 0.0], "Down": [0.0, 0.0, 0.0]})
    for t in trades:
        if not t["account"].startswith("mval") or t.get("leg") != 1:
            continue
        key = (t["account"], t["slug"])
        if key not in settled:
            continue
        cell = per[key][t["side"]]
        cell[0] += float(t["shares"])
        cell[1] += float(t["cost"])
        cell[2] += float(t["fees"])
    locked = 0.0
    total = 0.0
    pairs = 0
    for key, pnl in settled.items():
        total += pnl
        sides = per.get(key)
        if not sides:
            continue
        u, d = sides["Up"], sides["Down"]
        pair = min(u[0], d[0])
        if pair > 0 and u[0] > 0 and d[0] > 0:
            pair_cost = pair * (u[1] / u[0] + d[1] / d[0])
            pair_fees = pair * (u[2] / u[0] + d[2] / d[0])
            locked += pair - pair_cost - pair_fees
            pairs += 1
    return len(settled), total, locked, total - locked, pairs


def fmt(x):
    return ("+" if x >= 0 else "-") + format(abs(x), ",.2f")


def build_report():
    now = datetime.now(JST).strftime("%m-%d %H:%M")
    agg = fam_stats(FARM)
    order = ["FAIR", "MVAL", "ACVR", "MOM", "OPENFADE", "REV", "SNIPE"]
    lines = ["📊 模拟盘十分钟报（" + now + " JST）", "新农场·甜点带0.60-0.75（官方结算口径）："]
    for fam in order:
        if fam in agg:
            w, tot = agg[fam]
            lines.append("· " + fam + "：" + str(w) + " 窗 · 合计 " + fmt(tot)
                         + " · 均值 " + fmt(tot / w) + "/窗")
    n, tot, locked, resid, pairs = mval_split()
    if n:
        lines.append("MVAL 明细：已结算 " + str(n) + " 窗 · 锁定对子 " + fmt(locked)
                     + "（" + str(pairs) + " 窗成对）· 残余方向 " + fmt(resid)
                     + " · 合计 " + fmt(tot))
    agg1 = fam_stats(FARM1H)
    if "BAND" in agg1:
        w, tot = agg1["BAND"]
        lines.append("1h 甜点带克隆 band-01：" + str(w) + " 窗 · 合计 "
                     + fmt(tot))
    if "FAIR" in agg1:
        w, tot = agg1["FAIR"]
        lines.append("1h 探针：FAIR " + str(w) + " 窗 · 合计 " + fmt(tot))
    try:
        st = json.load(open(os.path.join(FARM, "state.json")))
        alive = sum(1 for a in st["accounts"].values() if a.get("alive"))
        lines.append("存活账户 " + str(alive) + "/" + str(len(st["accounts"])))
    except OSError:
        pass
    return "\n".join(lines)


def send(text):
    body = json.dumps({"chat_id": CHAT, "text": text}).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
        data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("ok", False)


def main():
    if not TOKEN or not CHAT:
        print("[farm-tg] TG_BOT_TOKEN / TG_CHAT_ID not configured; exiting", flush=True)
        return
    print("[farm-tg] reporter up; every " + str(INTERVAL_S) + "s", flush=True)
    while True:
        try:
            ok = send(build_report())
            print("[farm-tg] sent ok=" + str(ok), flush=True)
        except Exception as e:
            print("[farm-tg] send failed: " + repr(e), flush=True)
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
