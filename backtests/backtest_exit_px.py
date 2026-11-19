#!/usr/bin/env python3
"""Price-triggered exits (companion to backtest_exit.py): same FAIR
entries, but exit when the implied bid hits a price rule --
take-profit relative (+0.05..+0.20 over entry ask) or absolute
(0.75/0.85/0.95), stop-loss relative (-0.10/-0.15/-0.20) or absolute
(bid <= 0.10), TP+SL brackets, and sell-at-fair (bid >= model fair).
Unhit rules hold to Gamma settlement. Sell at implied bid
1 - opposite_ask minus 0.01 haircut; both legs pay taker fees.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_mval import load

STAKE = 6.0
HAIRCUT = 0.01


def bid_proxy(t, side):
    opp = t["down_ask"] if side == "Up" else t["up_ask"]
    if opp is None:
        return None
    return 1.0 - opp - HAIRCUT


def entries_for(by_slug, winners, gap_min):
    out = []
    for slug, wt in by_slug.items():
        if slug not in winners:
            continue
        start = int(slug.rsplit("-", 1)[1])
        for i, t in enumerate(wt):
            if t["_ts"] - start < 15 or t["tau"] < 60:
                continue
            best = None
            for side in ("Up", "Down"):
                ask = t["up_ask"] if side == "Up" else t["down_ask"]
                if ask is None or not (0.15 <= ask <= 0.92):
                    continue
                fair = t["_fair"] if side == "Up" else 1.0 - t["_fair"]
                g = fair - ask
                if g >= gap_min and (best is None or g > best[0]):
                    best = (side, ask, i)
            if best:
                out.append((slug, wt, best[0], best[1], best[2]))
                break
    return out


RULES = {
    "TP+0.05": lambda bp, ask, fair: bp >= ask + 0.05,
    "TP+0.10": lambda bp, ask, fair: bp >= ask + 0.10,
    "TP+0.15": lambda bp, ask, fair: bp >= ask + 0.15,
    "TP+0.20": lambda bp, ask, fair: bp >= ask + 0.20,
    "TP@0.75": lambda bp, ask, fair: bp >= 0.75,
    "TP@0.85": lambda bp, ask, fair: bp >= 0.85,
    "TP@0.95": lambda bp, ask, fair: bp >= 0.95,
    "SL-0.10": lambda bp, ask, fair: bp <= ask - 0.10,
    "SL-0.15": lambda bp, ask, fair: bp <= ask - 0.15,
    "SL-0.20": lambda bp, ask, fair: bp <= ask - 0.20,
    "SL@0.10": lambda bp, ask, fair: bp <= 0.10,
    "TP+0.15/SL-0.15": lambda bp, ask, fair: bp >= ask + 0.15 or bp <= ask - 0.15,
    "TP+0.10/SL-0.10": lambda bp, ask, fair: bp >= ask + 0.10 or bp <= ask - 0.10,
    "SELL@FAIR": lambda bp, ask, fair: bp >= fair,
}


def run(entries, winners, rate):
    tot = {k: 0.0 for k in RULES}
    hit = {k: 0 for k in RULES}
    hold = 0.0
    for slug, wt, side, ask, i0 in entries:
        shares = STAKE / ask
        fee_buy = shares * rate * ask * (1 - ask)
        settle = (shares if winners[slug] == side else 0.0) - STAKE - fee_buy
        hold += settle
        pending = set(RULES)
        for j in range(i0 + 1, len(wt)):
            if not pending:
                break
            t = wt[j]
            bp = bid_proxy(t, side)
            if bp is None or bp <= 0:
                continue
            fair = t["_fair"] if side == "Up" else 1.0 - t["_fair"]
            for name in list(pending):
                if RULES[name](bp, ask, fair):
                    fee_sell = shares * rate * bp * (1 - bp)
                    tot[name] += shares * bp - fee_sell - STAKE - fee_buy
                    hit[name] += 1
                    pending.discard(name)
        for name in pending:
            tot[name] += settle
    return hold, tot, hit


def main():
    by_slug, winners = load()
    for gap_min in (0.08, 0.05):
        entries = entries_for(by_slug, winners, gap_min)
        for rate in (0.07, 0.05):
            hold, tot, hit = run(entries, winners, rate)
            print("\ngap>=%.2f fee=%.2f haircut=0.01 entries=%d | HOLD pnl=%+.2f" % (
                gap_min, rate, len(entries), hold))
            for name in RULES:
                print("  %-16s pnl=%+8.2f per-trade=%+.3f triggered=%d/%d" % (
                    name, tot[name], tot[name] / len(entries), hit[name], len(entries)))


if __name__ == "__main__":
    main()
