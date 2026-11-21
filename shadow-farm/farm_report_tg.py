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


def acct_stats(data_dir):
    """account -> (windows, total_pnl)."""
    rows = read_jsonl(os.path.join(data_dir, "settlements.jsonl"))
    win = defaultdict(float)
    for r in rows:
        win[(r["account"], r["slug"])] += float(r.get("pnl", 0))
    agg = defaultdict(lambda: [0, 0.0])
    for (aid, slug), v in win.items():
        agg[aid][0] += 1
        agg[aid][1] += v
    return agg


def farm_section(data_dir, order):
    """Family lines with EVERY configured account listed under its
    family (lizi, 2026-11-21: write out each account, including
    zero-activity ones, so idle families stay visible)."""
    agg = fam_stats(data_dir)
    accts = acct_stats(data_dir)
    try:
        st = json.load(open(os.path.join(data_dir, "state.json")))
        universe = sorted(st["accounts"].keys())
    except OSError:
        universe = sorted(accts.keys())
    out = []
    for fam in order:
        members = [a for a in universe
                   if a.split("-")[0].upper() == fam]
        if not members:
            continue
        w, tot = agg.get(fam, [0, 0.0])
        line = "· " + fam + "\uff1a" + str(w) + " \u7a97 \u00b7 \u5408\u8ba1 " + fmt(tot)
        if w:
            line += " \u00b7 \u5747\u503c " + fmt(tot / w) + "/\u7a97"
        out.append(line)
        for aid in members:
            aw, atot = accts.get(aid, [0, 0.0])
            out.append("\u3000\u00b7 " + aid + "\uff1a" + str(aw)
                       + " \u7a97 \u00b7 " + fmt(atot))
    return out


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
    lines = ["\U0001F4CA \u6a21\u62df\u76d8\u5341\u5206\u949f\u62a5\uff08" + now + " JST\uff09",
             "\u65b0\u519c\u573a\u00b7\u751c\u70b9\u5e260.60-0.75\uff08\u5b98\u65b9\u7ed3\u7b97\u53e3\u5f84\uff09\uff1a"]
    lines += farm_section(FARM, ["FAIR", "MVAL", "ACVR", "MOM",
                                 "OPENFADE", "REV", "SNIPE"])
    n, tot, locked, resid, pairs = mval_split()
    if n:
        lines.append("MVAL \u660e\u7ec6\uff1a\u5df2\u7ed3\u7b97 " + str(n)
                     + " \u7a97 \u00b7 \u9501\u5b9a\u5bf9\u5b50 " + fmt(locked)
                     + "\uff08" + str(pairs) + " \u7a97\u6210\u5bf9\uff09\u00b7 \u6b8b\u4f59\u65b9\u5411 "
                     + fmt(resid) + " \u00b7 \u5408\u8ba1 " + fmt(tot))
    lines.append("1h \u519c\u573a\uff08\u5b98\u65b9\u7ed3\u7b97\u53e3\u5f84\uff09\uff1a")
    lines += farm_section(FARM1H, ["FAIR", "BAND", "LATE"])
    try:
        st = json.load(open(os.path.join(FARM, "state.json")))
        alive = sum(1 for a in st["accounts"].values() if a.get("alive"))
        lines.append("\u5b58\u6d3b\u8d26\u6237 " + str(alive) + "/"
                     + str(len(st["accounts"])))
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
