#!/usr/bin/env python3
"""Backtest tail-end buying on Polymarket BTC 5m up/down markets.

Uses recorded snipe-collector ticks (best asks for both sides, tau = seconds
remaining). Rule under test: in the last T seconds of a window, buy $10 of
whichever side's best ask first enters [0.95, 0.99], hold to settlement,
taker fee 0.07. Winners come from settlements.jsonl where present, else from
the Polymarket crypto-price API (cached in /tmp) so windows the snipe never
traded are included too -- no selection bias toward snipe entries.

Usage: tail5m_backtest.py <data_dir>
"""
import json
import os
import sys
import urllib.request
from collections import defaultdict

FEE = 0.07
STAKE = 10.0


def fetch_winner(start):
    url = ("https://polymarket.com/api/crypto/crypto-price?symbol=BTC"
           f"&variant=fiveminute&eventStartTime={start}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "tail5m-bt/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
        if d.get("completed"):
            return "Up" if float(d["closePrice"]) >= float(d["openPrice"]) else "Down"
    except Exception:
        pass
    return None


def load_winners(data_dir, slugs):
    cache_path = os.path.join(
        "/tmp", "winners_" + data_dir.strip("/").replace("/", "_") + ".json")
    cache = {}
    if os.path.exists(cache_path):
        cache = json.load(open(cache_path))
    winners = {}
    sp = os.path.join(data_dir, "settlements.jsonl")
    if os.path.exists(sp):
        for line in open(sp):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("winner") in ("Up", "Down"):
                winners[r["slug"]] = r["winner"]
    missing = [s for s in slugs if s not in winners and s not in cache]
    for s in missing:
        w = fetch_winner(int(s.rsplit("-", 1)[1]))
        if w:
            cache[s] = w
    if missing:
        json.dump(cache, open(cache_path, "w"))
    for s, w in cache.items():
        winners.setdefault(s, w)
    return winners


def main():
    data_dir = sys.argv[1]
    ticks = defaultdict(list)
    for line in open(os.path.join(data_dir, "ticks.jsonl")):
        try:
            r = json.loads(line)
        except Exception:
            continue
        ticks[r["slug"]].append(r)
    winners = load_winners(data_dir, list(ticks.keys()))
    ticks = {s: sorted(rows, key=lambda x: x["ts"])
             for s, rows in ticks.items() if s in winners}
    print(f"== {data_dir}: {len(winners)} winners known, {len(ticks)} windows with ticks")
    for T in (120, 60, 30):
        for band_name, lo, hi in (("0.95-0.99", 0.95, 0.99),
                                  ("0.95-0.97", 0.95, 0.969),
                                  ("0.97-0.99", 0.97, 0.99)):
            n = wins = 0
            pnl = 0.0
            asks = []
            depth_known = depth_ok = 0
            skipped_depth = 0
            for slug, rows in ticks.items():
                ent = None
                for r in rows:
                    if r["tau"] > T:
                        continue
                    for side, ak, sk in (("Up", "up_ask", "up_ask_size"),
                                         ("Down", "down_ask", "down_ask_size")):
                        ask = r.get(ak)
                        if ask is not None and lo <= ask <= hi:
                            ent = (side, ask, r.get(sk))
                            break
                    if ent:
                        break
                if not ent:
                    continue
                side, ask, size = ent
                shares = STAKE / ask
                if size is not None:
                    depth_known += 1
                    if size >= shares:
                        depth_ok += 1
                    else:
                        skipped_depth += 1
                        continue
                fee = shares * FEE * ask * (1 - ask)
                win = winners[slug] == side
                pnl += (shares if win else 0.0) - STAKE - fee
                n += 1
                wins += win
                asks.append(ask)
            if n:
                extra = (f" depth_ok={depth_ok}/{depth_known} skipped_depth={skipped_depth}"
                         if depth_known else " (no size data)")
                print(f"  tau<={T:3d} band {band_name}: n={n:3d} win={wins:3d} "
                      f"fail={n - wins:2d} ({100.0 * (n - wins) / n:4.1f}%) "
                      f"avg_ask={sum(asks) / n:.3f} pnl={pnl:+8.2f} avg={pnl / n:+.3f}{extra}")
            else:
                print(f"  tau<={T:3d} band {band_name}: n=0")


if __name__ == "__main__":
    main()
