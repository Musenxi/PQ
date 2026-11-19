#!/usr/bin/env python3
"""Backtest the @crbpite8 tweet's recipe AS LITERALLY DESCRIBED, on Box
ticks, Gamma-graded. The tweet (about wallet viniangusso) claims:
  - enter ~2 min before settlement;
  - when BTC is within $10 of the open, buy the cheap side at 20-40c
    (claimed 44% win rate);
  - when one side is clearly ahead, buy the leader near 50c;
  - rarely above 70c; skips most opportunities.
Variants:
  A  literal: tau in [45,150], |s_est-open| <= 10, buy side with ask in
     [0.20,0.40] (first qualifying tick, one entry/window)
  A2 same but WITHOUT the $10 near-tie constraint (loose reading)
  B  leader: tau in [45,150], |move| >= 20 in the leader's direction,
     leader ask in [0.45,0.55]
Fills at the tick's best ask (optimistic, no depth data), $10 stake,
fees 0.07 and 0.05.
"""
import json
import os
from collections import defaultdict
from datetime import datetime

DATA = os.path.expanduser("~/workspace/polymarket-paper/box_final_2026-11-18/data/ticks.jsonl")
CACHE = os.path.expanduser("~/workspace/polymarket-paper/gamma_winners_box.json")
STAKE = 10.0


def pnl_of(side, ask, winner, rate):
    shares = STAKE / ask
    fee = shares * rate * ask * (1 - ask)
    return (shares if winner == side else 0.0) - STAKE - fee


def main():
    ticks = [json.loads(l) for l in open(DATA)]
    ticks.sort(key=lambda t: t["ts"])
    by_slug = defaultdict(list)
    for t in ticks:
        if t.get("open") is None or t.get("s_est") is None:
            continue
        by_slug[t["slug"]].append(t)
    winners = json.load(open(CACHE))
    print("windows:", len(by_slug))

    def run(name, picker):
        for rate in (0.07, 0.05):
            n = wins = 0
            pnl = 0.0
            for slug, wt in by_slug.items():
                if slug not in winners:
                    continue
                pick = picker(wt)
                if not pick:
                    continue
                side, ask = pick
                n += 1
                if winners[slug] == side:
                    wins += 1
                pnl += pnl_of(side, ask, winners[slug], rate)
            print("%s fee=%.2f | trades=%d wins=%d (%.1f%%) | pnl=%+.2f | per-trade=%+.3f"
                  % (name, rate, n, wins, (100 * wins / n if n else 0), pnl,
                     (pnl / n if n else 0)))

    def pick_a(wt, near_tie=True):
        for t in wt:
            if not (45 <= t["tau"] <= 150):
                continue
            if near_tie and abs(t["s_est"] - t["open"]) > 10:
                continue
            for side, ask in (("Up", t["up_ask"]), ("Down", t["down_ask"])):
                if ask is not None and 0.20 <= ask <= 0.40:
                    return side, ask
        return None

    def pick_b(wt):
        for t in wt:
            if not (45 <= t["tau"] <= 150):
                continue
            move = t["s_est"] - t["open"]
            if abs(move) < 20:
                continue
            side = "Up" if move > 0 else "Down"
            ask = t["up_ask"] if side == "Up" else t["down_ask"]
            if ask is not None and 0.45 <= ask <= 0.55:
                return side, ask
        return None

    run("A literal (|move|<=10, cheap 0.20-0.40, last ~2min)", lambda wt: pick_a(wt, True))
    run("A2 loose (no $10 constraint)", lambda wt: pick_a(wt, False))
    run("B leader near 0.50 (|move|>=20)", pick_b)


if __name__ == "__main__":
    main()
