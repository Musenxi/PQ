#!/usr/bin/env python3
"""Maker-style replication of viniangusso's recipe: resting bids at
fair - delta on BOTH sides, refreshed every tick; a bid fills when a
LATER tick's best ask trades down to it, at the BID price, maker fee
0 (Polymarket charges takers only). This is the one mechanism matching
his fingerprints that the taker model (MVAL) does not capture: dip-
selected fills, spread capture, no taker fees, burst fills.

Approximations: Box ticks are ~2s best-ask snapshots -- intra-tick
dips are missed (understates fills) and queue position is unknown
(overstates fill share). Fills use the PREVIOUS tick's fair (no
look-ahead). Gamma settlement; locked/residual decomposition as in
the MVAL backtest. A taker-fee sensitivity row is printed too.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_mval import load, STAKE, ENTRY_DELAY_S, TAU_MIN


def run(by_slug, winners, delta, band, max_entries, fee_rate):
    tot_pnl = tot_locked = 0.0
    n_windows = n_entries = 0
    for slug, wt in by_slug.items():
        if slug not in winners:
            continue
        start = int(slug.rsplit("-", 1)[1])
        pos = {"Up": [0.0, 0.0, 0.0], "Down": [0.0, 0.0, 0.0]}
        entries = 0
        for i in range(1, len(wt)):
            if entries >= max_entries:
                break
            prev, t = wt[i - 1], wt[i]
            if t["_ts"] - start < ENTRY_DELAY_S or t["tau"] < TAU_MIN:
                continue
            for side in ("Up", "Down"):
                if entries >= max_entries:
                    break
                fair = prev["_fair"] if side == "Up" else 1.0 - prev["_fair"]
                bid = fair - delta
                if not (band[0] <= bid <= band[1]):
                    continue
                ask = t["up_ask"] if side == "Up" else t["down_ask"]
                if ask is None or ask > bid:
                    continue
                shares = STAKE / bid
                fees = shares * fee_rate * bid * (1 - bid)
                cell = pos[side]
                cell[0] += shares
                cell[1] += STAKE
                cell[2] += fees
                entries += 1
        if entries == 0:
            continue
        n_windows += 1
        n_entries += entries
        w = winners[slug]
        pnl = pos[w][0] - sum(c[1] + c[2] for c in pos.values())
        u, d = pos["Up"], pos["Down"]
        pair = min(u[0], d[0])
        locked = 0.0
        if pair > 0 and u[0] > 0 and d[0] > 0:
            locked = pair - pair * (u[1] / u[0] + d[1] / d[0]) - pair * (u[2] / u[0] + d[2] / d[0])
        tot_pnl += pnl
        tot_locked += locked
    return n_windows, n_entries, tot_pnl, tot_locked, tot_pnl - tot_locked


def main():
    by_slug, winners = load()
    print("windows:", len(by_slug))
    for fee_rate, label in ((0.0, "maker fee 0"), (0.07, "taker-fee sensitivity")):
        print("\n== %s ==" % label)
        for delta in (0.02, 0.03, 0.05):
            for max_entries in (4, 8):
                nw, ne, pnl, locked, resid = run(by_slug, winners, delta, (0.10, 0.95), max_entries, fee_rate)
                print("delta=%.2f max=%d | windows=%d fills=%d | pnl=%+.2f locked=%+.2f residual=%+.2f | per-window=%+.2f"
                      % (delta, max_entries, nw, ne, pnl, locked, resid, pnl / max(nw, 1)))


if __name__ == "__main__":
    main()
