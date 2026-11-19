#!/usr/bin/env python3
"""fix_settlements_gamma.py -- post-hoc settlement correction.

Re-checks every settled window in a farm data dir against the
OFFICIAL Gamma resolution and repairs rows whose booked winner
(crypto-price close-print sign) disagrees: pnl and the cash_after
chain shift by the payout delta (shares on the true winner minus
shares on the booked winner; costs/fees are unchanged), and
state.json cash/pnl/wins are adjusted by the same deltas.
Backups: settlements.jsonl.bak-gammafix, state.json.bak-gammafix.
Usage: fix_settlements_gamma.py <data_dir> [<data_dir> ...]
"""
import ast
import json
import os
import shutil
import sys
import urllib.request
from collections import defaultdict


def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def gamma_winner(slug):
    try:
        ev = get("https://gamma-api.polymarket.com/events?slug=" + slug)
    except Exception:
        return None
    if not ev:
        return None
    m = ev[0]["markets"][0]
    if not m.get("closed") or not m.get("outcomePrices"):
        return None
    outs = ast.literal_eval(m["outcomes"])
    pr = [float(x) for x in ast.literal_eval(m["outcomePrices"])]
    if max(pr) >= 0.999 and sum(pr) <= 1.001:
        return outs[pr.index(max(pr))]
    return None  # split/unresolved: leave the booked winner alone


def fix_dir(data_dir):
    print("=====", data_dir)
    spath = os.path.join(data_dir, "settlements.jsonl")
    tpath = os.path.join(data_dir, "trades.jsonl")
    stpath = os.path.join(data_dir, "state.json")
    rows = [json.loads(l) for l in open(spath)]
    trades = [json.loads(l) for l in open(tpath)] if os.path.exists(tpath) else []
    shares = defaultdict(float)
    for t in trades:
        if t.get("shares", 0) < 0:
            print("  WARNING: negative-shares trade row:", t)
        shares[(t["account"], t["slug"], t["side"])] += t.get("shares", 0.0)
    booked = {}
    for r in rows:
        if r.get("winner"):
            booked.setdefault(r["slug"], r["winner"])
    flips = {}
    for slug, bw in booked.items():
        gw = gamma_winner(slug)
        if gw and gw != bw:
            flips[slug] = (bw, gw)
    print("distinct slugs:", len(booked), "| flips:", len(flips))
    for s, (bw, gw) in sorted(flips.items()):
        print("  flip", s, bw, "->", gw)
    if not flips:
        return
    shutil.copy(spath, spath + ".bak-gammafix")
    if os.path.exists(stpath):
        shutil.copy(stpath, stpath + ".bak-gammafix")
    shift = defaultdict(float)
    total_delta = defaultdict(float)
    win_delta = defaultdict(int)
    fam_delta = defaultdict(float)
    n_fixed = 0
    for r in rows:
        acc = r["account"]
        if r["slug"] in flips:
            bw, gw = flips[r["slug"]]
            d = shares[(acc, r["slug"], gw)] - shares[(acc, r["slug"], bw)]
            old_pnl = r["pnl"]
            r["pnl"] = round(old_pnl + d, 4)
            r["winner"] = gw
            r["corrected"] = "gamma-flip-2026-11-19"
            shift[acc] += d
            total_delta[acc] += d
            fam_delta[acc.split("-")[0].upper()] += d
            if (old_pnl > 0) != (r["pnl"] > 0):
                win_delta[acc] += 1 if r["pnl"] > 0 else -1
            n_fixed += 1
        if "cash_after" in r:
            r["cash_after"] = round(r["cash_after"] + shift[acc], 2)
    with open(spath, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print("rows corrected:", n_fixed)
    print("family pnl deltas:", {k: round(v, 2) for k, v in sorted(fam_delta.items())})
    print("grand delta:", round(sum(total_delta.values()), 2))
    if os.path.exists(stpath):
        st = json.load(open(stpath))
        for acc, d in total_delta.items():
            a = st["accounts"].get(acc)
            if a:
                a["cash"] = round(a["cash"] + d, 2)
                a["pnl"] = round(a["pnl"] + d, 2)
                a["wins"] = a.get("wins", 0) + win_delta[acc]
        with open(stpath, "w") as f:
            json.dump(st, f)
        print("state.json adjusted for", len(total_delta), "accounts")


if __name__ == "__main__":
    for d in sys.argv[1:]:
        fix_dir(d)
