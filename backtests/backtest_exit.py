#!/usr/bin/env python3
"""Early-exit backtest: does selling before settlement rescue a
FAIR-style entry? Box ticks carry asks only, so the sell price is the
implied bid proxy 1 - opposite_ask, reported with haircuts of
0 / 0.01 / 0.02 to bracket the real spread. Entries: first tick per
window with model gap >= G (G = 0.05 / 0.08), ask in [0.15, 0.92],
offset >= 15s, tau >= 60, $6 taker buy. Exit variants: HOLD to
Gamma settlement; sell after +30/+60/+120s; sell when the gap has
closed (<= 0.01); sell when bid proxy >= entry ask + 0.10 (TP).
Both legs pay taker fees (rate 0.07 headline, 0.05 sensitivity).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_mval import load

STAKE = 6.0


def bid_proxy(t, side, haircut):
    opp = t["down_ask"] if side == "Up" else t["up_ask"]
    if opp is None:
        return None
    return 1.0 - opp - haircut


def run(by_slug, winners, gap_min, rate, haircut):
    variants = ["HOLD", "T30", "T60", "T120", "CONV", "TP"]
    tot = {v: 0.0 for v in variants}
    cnt = {v: 0 for v in variants}
    exited = {v: 0 for v in variants}
    for slug, wt in by_slug.items():
        if slug not in winners:
            continue
        start = int(slug.rsplit("-", 1)[1])
        entry = None
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
                    best = (g, side, ask, i)
            if best:
                entry = best
                break
        if not entry:
            continue
        _, side, ask, i0 = entry
        t0 = wt[i0]
        shares = STAKE / ask
        fee_buy = shares * rate * ask * (1 - ask)
        settle_pnl = (shares if winners[slug] == side else 0.0) - STAKE - fee_buy
        tot["HOLD"] += settle_pnl
        cnt["HOLD"] += 1
        exit_at = {}
        for j in range(i0 + 1, len(wt)):
            t = wt[j]
            dt = t["_ts"] - t0["_ts"]
            bp = bid_proxy(t, side, haircut)
            if bp is None or bp <= 0:
                continue
            for v, cond in (("T30", dt >= 30), ("T60", dt >= 60), ("T120", dt >= 120)):
                if v not in exit_at and cond and t["tau"] >= 10:
                    exit_at[v] = bp
            if "CONV" not in exit_at:
                fair = t["_fair"] if side == "Up" else 1.0 - t["_fair"]
                cur_ask = t["up_ask"] if side == "Up" else t["down_ask"]
                if cur_ask is not None and fair - cur_ask <= 0.01:
                    exit_at["CONV"] = bp
            if "TP" not in exit_at and bp >= ask + 0.10:
                exit_at["TP"] = bp
        for v in ("T30", "T60", "T120", "CONV", "TP"):
            if v in exit_at:
                sp = exit_at[v]
                fee_sell = shares * rate * sp * (1 - sp)
                tot[v] += shares * sp - fee_sell - STAKE - fee_buy
                exited[v] += 1
            else:
                tot[v] += settle_pnl
            cnt[v] += 1
    return tot, cnt, exited


def main():
    by_slug, winners = load()
    print("windows:", len(by_slug))
    for gap_min in (0.05, 0.08):
        for rate, haircut in ((0.07, 0.01), (0.07, 0.0), (0.07, 0.02), (0.05, 0.01)):
            tot, cnt, exited = run(by_slug, winners, gap_min, rate, haircut)
            print("\ngap>=%.2f fee=%.2f haircut=%.2f (entries=%d)" % (gap_min, rate, haircut, cnt["HOLD"]))
            for v in ("HOLD", "T30", "T60", "T120", "CONV", "TP"):
                print("  %-4s pnl=%+8.2f per-trade=%+.3f exited=%d/%d" % (
                    v, tot[v], tot[v] / max(cnt[v], 1), exited.get(v, 0), cnt[v]))


if __name__ == "__main__":
    main()
