#!/usr/bin/env python3
"""Resimulation backtests for the paper snipe strategy.

Usage: python3 resim.py <data_dir>
Reads trades.jsonl / settlements.jsonl / ticks.jsonl from the data dir.
Analyses:
  A) pair-threshold sweep: replay pairing from recorded ticks at several
     total-cost thresholds (live rule: p1 + opp_ask + opp_fee/share < T).
  B) exit rule (only when ticks carry bids): sell an unpaired leg-1 at the
     best bid after a time trigger; paired trades keep their actual result.
  C) trend filter: partition ACTUAL results by the trailing 5-min spot move
     before each leg-1 entry; report kept-PnL for candidate filters.
All PnL uses the live fee formula fee/share = 0.07 * p * (1-p).
"""
import json, sys, bisect
from datetime import datetime

def load(d, name):
    try:
        return [json.loads(l) for l in open(f"{d}/{name}")]
    except FileNotFoundError:
        return []

def ts(s):
    return datetime.fromisoformat(s).timestamp()

def fee_ps(p):
    return 0.07 * p * (1 - p)

def main():
    d = sys.argv[1]
    trades = load(d, "trades.jsonl")
    settles = {r["slug"]: r for r in load(d, "settlements.jsonl")}
    ticks = load(d, "ticks.jsonl")
    ticks.sort(key=lambda t: t["ts"])
    by_slug = {}
    for t in ticks:
        by_slug.setdefault(t["slug"], []).append(t)
    tick_ts = [ts(t["ts"]) for t in ticks]
    tick_spot = [t["spot"] for t in ticks]
    has_bids = any(t.get("up_bid") is not None or t.get("down_bid") is not None for t in ticks)

    leg1 = {}
    leg2_ts = {}
    for tr in trades:
        if tr["leg"] == 1:
            leg1[tr["slug"]] = tr
        else:
            leg2_ts[tr["slug"]] = ts(tr["ts"])
    entries = [(s, tr) for s, tr in leg1.items() if s in settles]
    print(f"dataset: {d}  settled leg-1 entries: {len(entries)}  ticks: {len(ticks)}  bids: {has_bids}")

    def replay_pair(tr, T):
        """Return (paired, pair_tick_ask or None)."""
        side = tr["side"]; p1 = tr["price"]
        opp = "down_ask" if side == "Up" else "up_ask"
        e = ts(tr["ts"])
        for t in by_slug.get(tr["slug"], []):
            if ts(t["ts"]) <= e:
                continue
            a2 = t.get(opp)
            if a2 is None:
                continue
            if p1 + a2 + fee_ps(a2) < T:
                return True, a2
        return False, None

    def pnl(tr, paired, a2):
        sh = tr["shares"]; fee1 = tr["fees"]
        if paired:
            return sh - (tr["cost"] + fee1) - (sh * a2 + sh * fee_ps(a2))
        win = settles[tr["slug"]]["winner"] == tr["side"]
        return (sh if win else 0.0) - tr["cost"] - fee1

    actual_total = sum(settles[s]["pnl"] for s, _ in entries)
    print(f"\nactual total PnL: {actual_total:+.2f}")

    print("\n== A) pair-threshold sweep (tick replay) ==")
    for T in (0.95, 0.96, 0.97, 0.98, 0.99):
        np_ = nu = 0; pp = pu = 0.0
        for s, tr in entries:
            paired, a2 = replay_pair(tr, T)
            v = pnl(tr, paired, a2)
            if paired: np_ += 1; pp += v
            else: nu += 1; pu += v
        print(f"  T={T:.2f}: pairs {np_:3d} ({pp:+7.2f})  unpaired {nu:3d} ({pu:+7.2f})  total {pp+pu:+7.2f}")

    if has_bids:
        print("\n== B) exit rule: sell unpaired leg-1 at bid after trigger ==")
        for trig in (60, 90, 120):
            tot = 0.0; exited = 0; ex_pnl = 0.0; held = 0
            for s, tr in entries:
                e = ts(tr["ts"]); side = tr["side"]
                pair_at = leg2_ts.get(s)
                bidk = "up_bid" if side == "Up" else "down_bid"
                done = False
                for t in by_slug.get(s, []):
                    tt = ts(t["ts"])
                    if tt <= e + trig:
                        continue
                    if pair_at is not None and pair_at <= tt:
                        break  # paired before/at trigger: keep actual
                    b = t.get(bidk)
                    if b is None:
                        continue
                    sh = tr["shares"]
                    v = sh * b - sh * fee_ps(b) - tr["cost"] - tr["fees"]
                    tot += v; ex_pnl += v; exited += 1; done = True
                    break
                if not done:
                    tot += settles[s]["pnl"]; held += 1
            print(f"  trigger {trig:3d}s: total {tot:+7.2f}  (exits {exited}, exit PnL {ex_pnl:+.2f}, kept-actual {held})")

    print("\n== C) trend filter on ACTUAL results (trailing 300s spot move at entry) ==")
    rows = []
    for s, tr in entries:
        e = ts(tr["ts"])
        i = bisect.bisect_right(tick_ts, e - 300)
        j = bisect.bisect_right(tick_ts, e)
        if i >= len(ticks) or j == 0 or tick_ts[j - 1] - tick_ts[max(i - 1, 0)] < 120:
            rows.append((s, tr, None)); continue
        d300 = tick_spot[j - 1] - tick_spot[max(i - 1, 0)]
        rows.append((s, tr, d300))
    def bucket(dv):
        if dv is None: return "unknown"
        a = abs(dv)
        return "<75" if a < 75 else ("75-150" if a <= 150 else ">150")
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0, 0.0])
    for s, tr, dv in rows:
        b = bucket(dv); st = settles[s]
        agg[b][0] += 1; agg[b][1] += 1 if st["paired"] else 0; agg[b][2] += st["pnl"]
    for b in ("<75", "75-150", ">150", "unknown"):
        if b in agg:
            n, pr, v = agg[b]
            print(f"  |d300| {b:8s}: n={n:3d} pair-rate {pr}/{n}  actual PnL {v:+7.2f}")
    for name, keep in (
        ("drop |d300|>150", lambda dv: dv is None or abs(dv) <= 150),
        ("drop |d300|>100", lambda dv: dv is None or abs(dv) <= 100),
        ("drop trend-chase (d300 same dir as entry, |d300|>75)",
         lambda dv, tr=None: True),
    ):
        kept = [(s, tr, dv) for s, tr, dv in rows]
        if "chase" in name:
            kept = [(s, tr, dv) for s, tr, dv in rows
                    if not (dv is not None and abs(dv) > 75 and ((tr["side"] == "Up") == (dv > 0)))]
        else:
            kept = [(s, tr, dv) for s, tr, dv in rows if keep(dv)]
        v = sum(settles[s]["pnl"] for s, _, _ in kept)
        print(f"  filter [{name}]: kept {len(kept)}/{len(rows)}  PnL {v:+.2f} (vs actual {actual_total:+.2f})")

if __name__ == "__main__":
    main()
