"""Idea 4b: does the BTC 'cheap side rich / favourite fair' structure exist in ETH/SOL/XRP 5m (fee 0.01)?
For each window, asset, entry tau: first taker BUY fill (either side) after s+tau with price in band.
One obs per window per (asset, band, tau). python -I a5_favourite.py"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import meta, Mkt, boot_ci, TD
M = meta()
def fee_rate(a, t):
    if a == "btc": return 0.05 if t >= 1795219140 else 0.07
    return 0.01
BANDS = ((0.30, 0.50), (0.55, 0.75), (0.75, 0.90))
for a in ("btc", "eth", "sol", "xrp"):
    sl = sorted(k for k, v in M.items() if v["asset"] == a and v["dur"] == "5m" and os.path.exists(os.path.join(TD, k + ".json.gz")))
    ms = [Mkt(k) for k in sl]; ms = [m for m in ms if m.ok]
    half = np.median([m.m["start"] for m in ms])
    for tau in (60, 150, 240):
        for lo, hi in BANDS:
            pnl, cl, px = [], [], []
            for m in ms:
                s = m.m["start"]
                i = np.searchsorted(m.ts, s + tau, side="right")
                k = np.where((m.side[i:] == 1) & (m.px[i:] >= lo) & (m.px[i:] <= hi) & (m.ts[i:] <= s + tau + 30))[0]
                if not len(k): continue
                j = i + k[0]; p = m.px[j]; o = int(m.oi[j])
                win = m.yes if o == 0 else 1 - m.yes
                pnl.append(win - p - fee_rate(a, s) * p * (1 - p)); cl.append(s); px.append(p)
            if len(pnl) < 30: continue
            pnl, cl = np.array(pnl), np.array(cl)
            mm, l, h = boot_ci(pnl, cl)
            print(f"{a} tau={tau} band={lo:.2f}-{hi:.2f} n={len(pnl)} px={np.mean(px):.3f} pnl/sh={mm:+.4f} [{l:+.4f},{h:+.4f}] H1={pnl[cl<half].mean():+.4f} H2={pnl[cl>=half].mean():+.4f}")
