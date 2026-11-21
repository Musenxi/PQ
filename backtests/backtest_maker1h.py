#!/usr/bin/env python3
"""1 h maker backtest (strategy B, lizi 2026-11-21) on Quant observer data.

Quotes both sides of BTC/ETH 1h updown markets around a
Chainlink-anchored random-walk fair (fair from the Binance index +
basis measured at the window open vs the official price_to_beat;
settlement = final-60s TWAP, variance sigma^2 * (3540 - offset + 20)).

Both quotes are bids (buy Up at fair-h, buy Down at 1-(fair+h)) --
the only way to "make" a binary book without shorting. Fills are
modelled from the 10 s top-5 snapshots under two assumptions:
  (O) touch:   a resting bid fills when a later snapshot's best ask
               on that token is <= our price (a seller crossed to us)
  (P) through: fills only when best ask <= our price - 0.01
Fill size = min(quote size, crossing level's ask size). Makers pay
no taker fee; no rebates counted. Quotes stop at tau = 180 s;
position cap 25 net shares per side. Grading from the observer's
own resolution records (official winner). Stdlib only.

v2: sigma precomputed in one pass per symbol; per-window frames
(fair per snapshot) built once and shared across all (h, variant)
configs -- same statistics and fill logic as v1, ~50x faster.
"""
import bisect
import glob
import json
import math
import os
from collections import deque

DATA = "/root/quant/data/polymarket"
QUOTE_SIZE = 5.0
POS_CAP = 25.0
STOP_OFFSET = 3420  # stop quoting 180 s before the close
HALF_SPREADS = (0.01, 0.02, 0.03)


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def load():
    books = {}   # slug -> [records]
    res = {}     # slug -> resolution record
    series = {}  # symbol -> [(t, index)]
    for path in sorted(glob.glob(os.path.join(DATA, "pm1h_*.jsonl"))):
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                if r["type"] == "book":
                    books.setdefault(r["slug"], []).append(r)
                    if r.get("ref") and r["ref"].get("index"):
                        series.setdefault(r["symbol"], []).append(
                            (float(r["t"]), float(r["ref"]["index"])))
                elif r["type"] == "resolution":
                    res[r["slug"]] = r
    for slug in books:
        books[slug].sort(key=lambda r: r["t"])
    for sym in series:
        series[sym].sort()
    return books, res, series


def sigma_series(series):
    """sigma_1s at every series point: trailing-900 s stdev of the
    consecutive-record log returns (population sd), / sqrt(10).
    Returns (times, sigmas) with None where <30 returns or idx < 40."""
    n = len(series)
    times = [x[0] for x in series]
    sig = [None] * n
    win = deque()  # (t_end, r)
    s1 = s2 = 0.0
    prev = None
    for i in range(n):
        t, px = series[i]
        if prev is not None and prev > 0 and px > 0:
            r = math.log(px / prev)
            win.append((t, r))
            s1 += r
            s2 += r * r
        prev = px
        while win and win[0][0] <= t - 900:
            _, r = win.popleft()
            s1 -= r
            s2 -= r * r
        if i >= 40 and len(win) >= 30:
            m = len(win)
            var = max(s2 / m - (s1 / m) ** 2, 0.0)
            sig[i] = math.sqrt(var) / math.sqrt(10.0)
    return times, sig


def build_frames(recs, res_rec, times, sig):
    """Per-snapshot frames for one window, or None if unusable.
    Frame: (offset, fair_up or None, up_asks, down_asks, spread or None)"""
    if not res_rec or res_rec.get("winner") not in ("Up", "Down"):
        return None
    ptb = float(res_rec["price_to_beat"])
    basis = None
    for r in recs:
        if r["offset"] >= 0 and r.get("ref") and r["ref"].get("index"):
            basis = ptb - float(r["ref"]["index"])
            break
    if basis is None:
        return None
    frames = []
    for r in recs:
        off = float(r["offset"])
        if off < 0:
            continue
        fair = None
        spread = None
        if r.get("ref") and r["ref"].get("index"):
            i = bisect.bisect_right(times, float(r["t"])) - 1
            s = sig[i] if 0 <= i < len(sig) else None
            if s is not None:
                spot_adj = float(r["ref"]["index"]) + basis
                sd = s * math.sqrt(max(3540.0 - off, 0.0) + 20.0)
                if sd > 0:
                    fair = phi(math.log(spot_adj / ptb) / sd)
        up = r["up"]
        if up.get("bids") and up.get("asks"):
            spread = float(up["asks"][0][0]) - float(up["bids"][0][0])
        frames.append((off, fair, up.get("asks") or [], r["down"].get("asks") or [],
                       spread))
    return frames


def sim(frames, winner, h, variant):
    pos = {"Up": 0.0, "Down": 0.0}
    cost = {"Up": 0.0, "Down": 0.0}
    fills = 0
    quotes = {"Up": None, "Down": None}
    spreads = []
    for off, fair, up_asks, down_asks, spread in frames:
        asks = {"Up": up_asks, "Down": down_asks}
        for side in ("Up", "Down"):
            q = quotes[side]
            if q is None or not asks[side]:
                continue
            ba, bs = float(asks[side][0][0]), float(asks[side][0][1])
            thresh = q if variant == "O" else q - 0.01
            if ba <= thresh + 1e-9:
                size = min(QUOTE_SIZE, bs)
                if size > 0:
                    pos[side] += size
                    cost[side] += size * q
                    fills += 1
                    quotes[side] = None
        if off > STOP_OFFSET:
            quotes = {"Up": None, "Down": None}
            continue
        if fair is None:
            continue
        if spread is not None:
            spreads.append(spread)
        targets = {
            "Up": math.floor((fair - h) * 100) / 100.0,
            "Down": math.floor(((1.0 - fair) - h) * 100) / 100.0,
        }
        for side in ("Up", "Down"):
            tgt = targets[side]
            net_other = pos["Down" if side == "Up" else "Up"]
            if tgt < 0.01 or tgt > 0.99 or pos[side] - net_other >= POS_CAP:
                quotes[side] = None
            else:
                quotes[side] = tgt
    payout = pos["Up"] * (1.0 if winner == "Up" else 0.0) + \
        pos["Down"] * (1.0 if winner == "Down" else 0.0)
    total_cost = cost["Up"] + cost["Down"]
    paired = min(pos["Up"], pos["Down"])
    pair_pnl = 0.0
    if paired > 0:
        cu = cost["Up"] / pos["Up"] if pos["Up"] else 0.0
        cd = cost["Down"] / pos["Down"] if pos["Down"] else 0.0
        pair_pnl = paired - paired * (cu + cd)
    pnl = payout - total_cost
    return {"pnl": pnl, "fills": fills, "pair_pnl": pair_pnl,
            "resid_pnl": pnl - pair_pnl,
            "med_spread": sorted(spreads)[len(spreads) // 2] if spreads else None}


def main():
    books, res, series = load()
    print(f"windows with books: {len(books)}, resolutions: {len(res)}", flush=True)
    sigtab = {sym: sigma_series(s) for sym, s in series.items()}
    for sym in ("btc", "eth"):
        slugs = [s for s in books if s.startswith(sym + "-")]
        times, sig = sigtab.get(sym, ([], []))
        built = []
        for slug in slugs:
            fr = build_frames(books[slug], res.get(slug), times, sig)
            if fr:
                built.append((fr, res[slug]["winner"]))
        for h in HALF_SPREADS:
            for variant in ("O", "P"):
                rows = [sim(fr, w, h, variant) for fr, w in built]
                if not rows:
                    continue
                nf = sum(r["fills"] for r in rows)
                pnl = sum(r["pnl"] for r in rows)
                pp = sum(r["pair_pnl"] for r in rows)
                rp = sum(r["resid_pnl"] for r in rows)
                sp = [r["med_spread"] for r in rows if r["med_spread"] is not None]
                print(f"{sym} h={h:.2f} var={variant}: windows={len(rows)} "
                      f"fills={nf} pnl=${pnl:+.2f} (paired ${pp:+.2f}, "
                      f"residual ${rp:+.2f}) med_market_spread="
                      f"{(sorted(sp)[len(sp)//2] if sp else float('nan')):.3f}",
                      flush=True)


if __name__ == "__main__":
    main()
