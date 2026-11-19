#!/usr/bin/env python3
"""Approximate MVAL backtest on recorded Box snipe ticks, Gamma-graded.

Replicates the farm's MVAL family (two-sided value accumulation):
throughout the window, buy $5 of the side whose ask is furthest below
its TWAP-aware fair, whenever that gap >= config gap and the ask is in
band; at most one entry per tick and max_entries per window; paired
shares settle at exactly $1.

Approximations (both optimistic vs the farm's v2 execution model):
ticks carry only best asks (no depth), so fills are at best ask with
no depth check. Two fill timings are reported: instant (signal tick's
ask -- upper bound) and next-tick (the following tick's ask for that
side, band re-checked -- closer to the farm's one-tick delay).

Decomposition matches farm_report_tg.py: locked = pair_shares
- pair_cost - pair_fees; residual = total pnl - locked.
Fees at 0.07 (data era) and 0.05 (post-2026-11-21 flip).
"""
import json
import math
import os
from collections import defaultdict, deque
from datetime import datetime

DATA = os.path.expanduser("~/workspace/polymarket-paper/box_final_2026-11-18/data/ticks.jsonl")
CACHE = os.path.expanduser("~/workspace/polymarket-paper/gamma_winners_box.json")
STAKE = 5.0
ENTRY_DELAY_S = 15
TAU_MIN = 20


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def load():
    ticks = [json.loads(l) for l in open(DATA)]
    ticks.sort(key=lambda t: t["ts"])
    for t in ticks:
        t["_ts"] = datetime.fromisoformat(t["ts"]).timestamp()
    by_slug = defaultdict(list)
    for t in ticks:
        if t.get("open") is None or t.get("s_est") is None:
            continue
        by_slug[t["slug"]].append(t)
    winners = json.load(open(CACHE))
    # one-pass rolling sigma (per-second), farm-style
    win = deque()
    rets = deque()
    s1 = s2 = 0.0
    for t in ticks:
        ts_now, spot = t["_ts"], t["spot"]
        if win:
            r = math.log(spot / win[-1][1])
            rets.append((ts_now, r))
            s1 += r
            s2 += r * r
        win.append((ts_now, spot))
        while win and win[0][0] < ts_now - 900:
            win.popleft()
        while rets and rets[0][0] < ts_now - 900:
            _, r0 = rets.popleft()
            s1 -= r0
            s2 -= r0 * r0
        if len(rets) > 10:
            mean = s1 / len(rets)
            var = max(s2 / len(rets) - mean * mean, 0.0)
            step = max((win[-1][0] - win[0][0]) / max(len(win) - 1, 1), 0.1)
            t["_sigma"] = max(math.sqrt(var) / math.sqrt(step), 1e-5)
        else:
            t["_sigma"] = 0.00012
    # farm fair per tick
    for slug, wt in by_slug.items():
        for t in wt:
            tau = t["tau"]
            s_est = t["s_est"]
            sig = t["_sigma"]
            if tau >= 60:
                exp_twap = s_est
                var_f = tau - 40.0
            else:
                elapsed = 60.0 - tau
                tw = [x["s_est"] for x in wt
                      if x["_ts"] >= t["_ts"] - elapsed - 3 and x["_ts"] <= t["_ts"]]
                realised = sum(tw) / len(tw) if tw else s_est
                exp_twap = (realised * elapsed + s_est * tau) / 60.0
                var_f = tau ** 3 / (3.0 * 60.0 * 60.0)
            z = math.log(exp_twap / t["open"]) / (sig * math.sqrt(max(var_f, 1e-6)))
            t["_fair"] = min(max(norm_cdf(z), 0.001), 0.999)
    return by_slug, winners


def run_config(by_slug, winners, gap_min, band, max_entries, rate, timing):
    tot_pnl = tot_locked = 0.0
    n_windows = n_entries = 0
    win_pnls = []
    for slug, wt in by_slug.items():
        if slug not in winners:
            continue
        start = int(slug.rsplit("-", 1)[1])
        pos = {"Up": [0.0, 0.0, 0.0], "Down": [0.0, 0.0, 0.0]}  # shares, cost, fees
        entries = 0
        for i, t in enumerate(wt):
            if entries >= max_entries:
                break
            if t["_ts"] - start < ENTRY_DELAY_S or t["tau"] < TAU_MIN:
                continue
            best = None
            for s in ("Up", "Down"):
                ask = t["up_ask"] if s == "Up" else t["down_ask"]
                if ask is None or not (band[0] <= ask <= band[1]):
                    continue
                fair = t["_fair"] if s == "Up" else 1.0 - t["_fair"]
                g = fair - ask
                if g >= gap_min and (best is None or g > best[0]):
                    best = (g, s)
            if not best:
                continue
            side = best[1]
            if timing == "next":
                if i + 1 >= len(wt):
                    continue
                nt = wt[i + 1]
                ask = nt["up_ask"] if side == "Up" else nt["down_ask"]
                if ask is None or not (band[0] <= ask <= band[1]):
                    continue
            else:
                ask = t["up_ask"] if side == "Up" else t["down_ask"]
            shares = STAKE / ask
            fees = shares * rate * ask * (1 - ask)
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
        payout = pos[w][0]
        pnl = payout - sum(c[1] + c[2] for c in pos.values())
        u, d = pos["Up"], pos["Down"]
        pair = min(u[0], d[0])
        locked = 0.0
        if pair > 0 and u[0] > 0 and d[0] > 0:
            locked = pair - pair * (u[1] / u[0] + d[1] / d[0]) - pair * (u[2] / u[0] + d[2] / d[0])
        tot_pnl += pnl
        tot_locked += locked
        win_pnls.append(pnl)
    return n_windows, n_entries, tot_pnl, tot_locked, tot_pnl - tot_locked, win_pnls


def main():
    by_slug, winners = load()
    print("windows:", len(by_slug))
    configs = []
    n = 0
    for gap in (0.02, 0.03, 0.05):
        for band in ((0.10, 0.95), (0.20, 0.90)):
            for max_entries in (4, 8):
                n += 1
                configs.append((f"mval-{n:02d}", gap, band, max_entries))
    for timing in ("instant", "next"):
        for rate in (0.07, 0.05):
            print("\n== timing=%s fee=%.2f ==" % (timing, rate))
            for cid, gap, band, me in configs:
                nw, ne, pnl, locked, resid, _ = run_config(by_slug, winners, gap, band, me, rate, timing)
                print("%s gap=%.2f band=%s max=%d | windows=%d entries=%d | pnl=%+.2f locked=%+.2f residual=%+.2f"
                      % (cid, gap, band, me, nw, ne, pnl, locked, resid))


if __name__ == "__main__":
    main()
