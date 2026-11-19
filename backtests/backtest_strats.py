#!/usr/bin/env python3
"""Backtests for two candidate strategies on recorded Box snipe ticks,
graded on GAMMA official winners (not the crypto-price endpoint).

A) TWAP-LOCK: in the final 60 s the settlement TWAP is progressively
   realised. If the remaining prints would need an implausible move
   (margin in sigma units >= Z) to flip the TWAP across the open, the
   outcome is locked; buy the locked side when its ask <= 1 - delta.
B) JUMP-TWAP: only on extreme 20 s spot jumps (|jump20| >= J), buy the
   side the TWAP-aware fair model (replicated from farm.py) prices
   cheapest vs the ask by >= gap. Control: same rule, no jump gate.

Ticks: box_final_2026-11-18/data/ticks.jsonl (v0.3 format: spot, s_est,
open, tau, jump20, up_ask, down_ask at ~2 s cadence).
PnL: $6 stake filled at the tick ask, fee = shares*rate*p*(1-p).
"""
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict

DATA = os.path.expanduser("~/workspace/polymarket-paper/box_final_2026-11-18/data/ticks.jsonl")
CACHE = os.path.expanduser("~/workspace/polymarket-paper/gamma_winners_box.json")
STAKE = 6.0


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def gamma_winners(slugs):
    if os.path.exists(CACHE):
        return json.load(open(CACHE))
    out = {}
    slugs = sorted(slugs)
    for i, slug in enumerate(slugs):
        req = urllib.request.Request(
            "https://gamma-api.polymarket.com/events?slug=" + slug,
            headers={"User-Agent": "Mozilla/5.0"})
        try:
            ev = json.load(urllib.request.urlopen(req, timeout=20))
            m = ev[0]["markets"][0]
            prices = [float(x) for x in (json.loads(m["outcomePrices"]) if isinstance(m["outcomePrices"], str) else m["outcomePrices"])]
            outcomes = m["outcomes"]
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            if max(prices) >= 0.999:
                out[slug] = outcomes[prices.index(max(prices))]
        except Exception as e:
            print("gamma fail", slug, repr(e), file=sys.stderr)
        if i % 100 == 0:
            print("gamma", i, "/", len(slugs), file=sys.stderr)
    json.dump(out, open(CACHE, "w"))
    return out


def fee(shares, p, rate):
    return shares * rate * p * (1 - p)


def settle_pnl(side, ask, winner, rate):
    shares = STAKE / ask
    cost = STAKE + fee(shares, ask, rate)
    return (shares if winner == side else 0.0) - cost


def main():
    ticks = [json.loads(l) for l in open(DATA)]
    ticks.sort(key=lambda t: t["ts"])
    from datetime import datetime
    for t in ticks:
        t["_ts"] = datetime.fromisoformat(t["ts"]).timestamp()
    by_slug = defaultdict(list)
    for t in ticks:
        if t.get("open") is None or t.get("s_est") is None:
            continue
        by_slug[t["slug"]].append(t)
    winners = gamma_winners(by_slug.keys())
    print("windows with gamma winner:", len(winners), "of", len(by_slug))

    # rolling sigma (per-second) exactly like farm.py: log returns of the
    # spot series over the trailing 900 s of ticks (all slugs share one
    # underlying series; ticks are ~2 s apart).
    allts = [t["_ts"] for t in ticks]
    allspot = [t["spot"] for t in ticks]

    def sigma_at(ts_now):
        pts = [(allts[i], allspot[i]) for i in range(len(allts))
               if ts_now - 900 <= allts[i] <= ts_now]
        if len(pts) <= 30:
            return 0.00012
        rets = [math.log(pts[i][1] / pts[i - 1][1]) for i in range(1, len(pts))]
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        step = max((pts[-1][0] - pts[0][0]) / max(len(pts) - 1, 1), 0.1)
        return max(math.sqrt(var) / math.sqrt(step), 1e-5)

    def farm_fair(t, window_ticks):
        """Replicate farm.py fair_up from a tick (uses s_est series)."""
        tau = t["tau"]
        openp = t["open"]
        s_est = t["s_est"]
        sig = sigma_at(t["_ts"])
        if tau >= 60:
            exp_twap = s_est
            var_f = tau - 40.0
        else:
            elapsed = 60.0 - tau
            tw = [x["s_est"] for x in window_ticks
                  if x["_ts"] >= t["_ts"] - elapsed - 3 and x["_ts"] <= t["_ts"]]
            realised = sum(tw) / len(tw) if tw else s_est
            exp_twap = (realised * elapsed + s_est * tau) / 60.0
            var_f = tau ** 3 / (3.0 * 60.0 * 60.0)
        z = math.log(exp_twap / openp) / (sig * math.sqrt(max(var_f, 1e-6)))
        return min(max(norm_cdf(z), 0.001), 0.999), sig

    # ---- precompute per-tick sigma (one pass) and farm fair ONCE ----
    from collections import deque
    _win = deque()
    _rets = deque()
    _s1 = 0.0
    _s2 = 0.0
    for t in ticks:
        ts_now, spot = t["_ts"], t["spot"]
        if _win:
            r = math.log(spot / _win[-1][1])
            _rets.append((ts_now, r))
            _s1 += r
            _s2 += r * r
        _win.append((ts_now, spot))
        while _win and _win[0][0] < ts_now - 900:
            _win.popleft()
        while _rets and _rets[0][0] < ts_now - 900:
            _, r0 = _rets.popleft()
            _s1 -= r0
            _s2 -= r0 * r0
        if len(_rets) > 10:
            mean = _s1 / len(_rets)
            var = max(_s2 / len(_rets) - mean * mean, 0.0)
            step = max((_win[-1][0] - _win[0][0]) / max(len(_win) - 1, 1), 0.1)
            t["_sigma"] = max(math.sqrt(var) / math.sqrt(step), 1e-5)
        else:
            t["_sigma"] = 0.00012
    def fair_of(t, window_ticks):
        tau = t["tau"]
        openp = t["open"]
        s_est = t["s_est"]
        sig = t["_sigma"]
        if tau >= 60:
            exp_twap = s_est
            var_f = tau - 40.0
        else:
            elapsed = 60.0 - tau
            tw = [x["s_est"] for x in window_ticks
                  if x["_ts"] >= t["_ts"] - elapsed - 3 and x["_ts"] <= t["_ts"]]
            realised = sum(tw) / len(tw) if tw else s_est
            exp_twap = (realised * elapsed + s_est * tau) / 60.0
            var_f = tau ** 3 / (3.0 * 60.0 * 60.0)
        z = math.log(exp_twap / openp) / (sig * math.sqrt(max(var_f, 1e-6)))
        return min(max(norm_cdf(z), 0.001), 0.999)
    for slug, wt in by_slug.items():
        for t in wt:
            t["_fair"] = fair_of(t, wt)

    # ---------------- A) TWAP-LOCK ----------------
    print("\n== A) TWAP-LOCK (stake $6, fee 0.07 / 0.05) ==")
    for Z in (2.0, 3.0, 4.0):
        for delta in (0.01, 0.02, 0.03, 0.05):
            n = wins = 0
            pnl7 = pnl5 = 0.0
            locked_windows = set()
            for slug, wt in by_slug.items():
                if slug not in winners:
                    continue
                traded = False
                for t in wt:
                    tau = t["tau"]
                    if tau <= 0 or tau > 60:
                        continue
                    openp = t["open"]
                    s_est = t["s_est"]
                    elapsed = 60.0 - tau
                    tw = [x["s_est"] for x in wt
                          if x["_ts"] >= t["_ts"] - elapsed - 3 and x["_ts"] <= t["_ts"]]
                    realised = sum(tw) / len(tw) if tw else s_est
                    # remaining prints must average A_break to flip the TWAP
                    a_break = (60.0 * openp - realised * elapsed) / tau
                    sig = t["_sigma"]
                    # stdev of the average of a random walk over tau seconds
                    sd_avg = sig * s_est * math.sqrt(tau / 3.0)
                    if sd_avg <= 0:
                        continue
                    margin_up = (s_est - a_break) / sd_avg     # >0: Up locked-ish
                    margin_dn = (a_break - s_est) / sd_avg
                    side = None
                    if margin_up >= Z:
                        side, ask = "Up", t["up_ask"]
                    elif margin_dn >= Z:
                        side, ask = "Down", t["down_ask"]
                    if side is None:
                        continue
                    locked_windows.add(slug)
                    if traded or ask is None or ask > 1 - delta or ask < 0.5:
                        continue
                    traded = True
                    n += 1
                    if winners[slug] == side:
                        wins += 1
                    pnl7 += settle_pnl(side, ask, winners[slug], 0.07)
                    pnl5 += settle_pnl(side, ask, winners[slug], 0.05)
            print("Z=%.0f delta=%.2f | locked windows=%d | trades=%d wins=%d (%.0f%%) | pnl@.07=%+.2f pnl@.05=%+.2f"
                  % (Z, delta, len(locked_windows), n, wins,
                     (100 * wins / n if n else 0), pnl7, pnl5))

    # ---------------- B) JUMP-TWAP ----------------
    print("\n== B) JUMP-TWAP (stake $6, fee 0.07) ==")
    for J in (100.0, 150.0, 200.0, None):
        for gap in (0.03, 0.05, 0.08):
            n = wins = 0
            pnl = 0.0
            for slug, wt in by_slug.items():
                if slug not in winners:
                    continue
                for t in wt:
                    if J is not None and abs(t.get("jump20") or 0) < J:
                        continue
                    if t["tau"] < 20:
                        continue
                    fair_up = t["_fair"]
                    cands = []
                    if t["up_ask"]:
                        cands.append((fair_up - t["up_ask"], "Up", t["up_ask"]))
                    if t["down_ask"]:
                        cands.append(((1 - fair_up) - t["down_ask"], "Down", t["down_ask"]))
                    cands.sort(reverse=True)
                    if not cands or cands[0][0] < gap:
                        continue
                    _, side, ask = cands[0]
                    n += 1
                    if winners[slug] == side:
                        wins += 1
                    pnl += settle_pnl(side, ask, winners[slug], 0.07)
                    break
            tag = ("J>=%.0f" % J) if J is not None else "control (no jump gate)"
            print("%s gap=%.2f | trades=%d wins=%d (%.0f%%) | pnl=%+.2f"
                  % (tag, gap, n, wins, (100 * wins / n if n else 0), pnl))


if __name__ == "__main__":
    main()
