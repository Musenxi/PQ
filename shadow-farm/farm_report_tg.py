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
    agg = defaultdict(lambda: [0, 0.0, 0])
    for (fam, slug), v in win.items():
        agg[fam][0] += 1
        agg[fam][1] += v
        if v > 0:
            agg[fam][2] += 1
    return agg


def acct_stats(data_dir):
    """account -> (windows, total_pnl)."""
    rows = read_jsonl(os.path.join(data_dir, "settlements.jsonl"))
    win = defaultdict(float)
    for r in rows:
        win[(r["account"], r["slug"])] += float(r.get("pnl", 0))
    agg = defaultdict(lambda: [0, 0.0, 0])
    for (aid, slug), v in win.items():
        agg[aid][0] += 1
        agg[aid][1] += v
        if v > 0:
            agg[aid][2] += 1
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




PREV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "tg_prev.json")


def load_prev():
    try:
        return json.load(open(PREV_PATH))
    except (OSError, ValueError):
        return {}


def farm_section(data_dir, order, prev):
    """Family lines with EVERY configured account listed under its
    family (lizi, 2026-11-21: write out each account, including
    zero-activity ones, so idle families stay visible). Lines carry
    a delta vs the previous report (lizi, 2026-11-21). Returns
    (lines, current fam stats, current acct stats)."""
    agg = fam_stats(data_dir)
    accts = acct_stats(data_dir)
    pfam = prev.get("fam", {}).get(data_dir, {})
    pacct = prev.get("acct", {}).get(data_dir, {})
    try:
        st = json.load(open(os.path.join(data_dir, "state.json")))
        universe = sorted(st["accounts"].keys())
    except OSError:
        universe = sorted(accts.keys())

    def delta(w, tot, pw, ptot):
        dw = w - pw
        dp = round(tot - ptot, 2)
        if dw == 0 and dp == 0:
            return ""
        return " · \u0394 " + format(dw, "+d") + "\u7a97 " + fmt(dp)

    out = []
    for fam in order:
        members = [a for a in universe
                   if a.split("-")[0].upper() == fam]
        if not members:
            continue
        w, tot, wins = agg.get(fam, [0, 0.0, 0])
        pw, ptot = pfam.get(fam, [0, 0.0])
        line = "· " + fam + "：" + str(w) + " 窗 · 合计 " + fmt(tot)
        if w:
            line += " · 均值 " + fmt(tot / w) + "/窗"
            line += " · 胜率 " + format(wins / w, ".0%")
        line += delta(w, tot, pw, ptot)
        out.append(line)
        for aid in members:
            aw, atot, awins = accts.get(aid, [0, 0.0, 0])
            paw, patot = pacct.get(aid, [0, 0.0])
            aline = "　· " + aid + "：" + str(aw) + " 窗 · " + fmt(atot)
            if aw:
                aline += " · 胜率 " + format(awins / aw, ".0%")
            aline += delta(aw, atot, paw, patot)
            out.append(aline)
    cur = {"fam": {k: list(v[:2]) for k, v in agg.items()},
           "acct": {k: list(v[:2]) for k, v in accts.items()}}
    return out, cur


def build_report(update_prev=True):
    now = datetime.now(JST).strftime("%m-%d %H:%M")
    prev = load_prev()
    lines = ["📊 模拟盘十分钟报（" + now + " JST）",
             "新农场·甜点带0.60-0.75（官方结算口径）："]
    sec, cur2 = farm_section(FARM, ["FAIR", "MVAL", "ACVR", "MOM",
                                    "OPENFADE", "REV", "SNIPE"], prev)
    lines += sec
    n, tot, locked, resid, pairs = mval_split()
    if n:
        lines.append("MVAL 明细：已结算 " + str(n) + " 窗 · 锁定对子 "
                     + fmt(locked) + "（" + str(pairs) + " 窗成对）· 残余方向 "
                     + fmt(resid) + " · 合计 " + fmt(tot))
    lines.append("1h 农场（官方结算口径）：")
    sec, cur1 = farm_section(FARM1H, ["FAIR", "BAND", "LATE"], prev)
    lines += sec
    bnc = read_jsonl("/root/polymarket-farm1h/data/fair07_binance.jsonl")
    bset = [r for r in bnc if r.get("type") == "settle"]
    if bset:
        bw = sum(1 for r in bset if r["win"])
        bu = sum(r["units"] for r in bset)
        lines.append("fair-07→币安1h点对点: " + str(len(bset)) + " 单 胜率 "
                     + f"{bw / len(bset):.0%}" + " 按85%赔率期望 "
                     + f"{bu / len(bset):+.2f}" + "/注")
    try:
        st = json.load(open(os.path.join(FARM, "state.json")))
        alive = sum(1 for a in st["accounts"].values() if a.get("alive"))
        lines.append("存活账户 " + str(alive) + "/"
                     + str(len(st["accounts"])))
    except OSError:
        pass
    if update_prev:
        nxt = {"fam": {FARM: cur2["fam"], FARM1H: cur1["fam"]},
               "acct": {FARM: cur2["acct"], FARM1H: cur1["acct"]}}
        try:
            with open(PREV_PATH, "w") as f:
                json.dump(nxt, f)
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
