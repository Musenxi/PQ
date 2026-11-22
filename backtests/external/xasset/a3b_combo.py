"""Idea 3b: executable 'between' combo. 15m market and the 5m market that shares its end (last 5m).
Buy Up on the lower-strike market + Down on the higher-strike market (pays 1 + 1{Klow<=F<Khigh}).
Entry at t = 5m start + ENTRY: first taker BUY fill of each leg in (t, t+20]. One per window.
python -I a3b_combo.py"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import meta, Mkt, boot_ci, TD
M = meta()
def fee_rate(a, d, t):
    if d == "1h": return 0.01
    if a == "btc": return 0.05 if t >= 1795219140 else 0.07
    return 0.01
ex = lambda sl: os.path.exists(os.path.join(TD, sl + ".json.gz"))
for ENTRY in (30, 60, 120):
    print(f"== entry {ENTRY}s after 5m start")
    pool = []
    for a in ("btc", "eth", "sol", "xrp"):
        res = []
        for sl in sorted(k for k, v in M.items() if v["asset"] == a and v["dur"] == "15m" and ex(k) and v["k"]):
            u = M[sl]["start"]; ss = f"{a}-updown-5m-{u + 600}"
            if ss not in M or not ex(ss) or not M[ss]["k"]: continue
            L, S = Mkt(sl), Mkt(ss)
            if not (L.ok and S.ok): continue
            lowIsL = M[sl]["k"] < M[ss]["k"]
            low, high = (L, S) if lowIsL else (S, L)
            t = u + 600 + ENTRY
            pl, ph = low.last_up(t, 20), high.last_up(t, 20)
            fa = low.buy_fill(0, t, 20); fb = high.buy_fill(1, t, 20)
            if np.isnan(fa) or np.isnan(fb) or np.isnan(pl) or np.isnan(ph): continue
            dl, dh = ("15m", "5m") if lowIsL else ("5m", "15m")
            between = int(low.yes == 1 and high.yes == 0)
            pnl = 1 + between - fa - fb - fee_rate(a, dl, u) * fa * (1 - fa) - fee_rate(a, dh, u) * fb * (1 - fb)
            res.append((u, pnl, pl - ph, between, fa + fb - 1))
        r = np.array(res); pool += res
        half = np.median(r[:, 0])
        for nm, k in (("all", r[:, 2] > -9), ("impl>0.15", r[:, 2] > 0.15)):
            x = r[k]
            if len(x) < 30: continue
            m, lo, hi = boot_ci(x[:, 1], x[:, 0])
            print(f" {a} {nm}: n={len(x)} cost-1={x[:,4].mean():.3f} realised between={x[:,3].mean():.3f} pnl/combo={m:+.4f} [{lo:+.4f},{hi:+.4f}] H1={x[x[:,0]<half,1].mean():+.4f} H2={x[x[:,0]>=half,1].mean():+.4f}")
    r = np.array(pool); k = r[:, 2] > 0.15
    m, lo, hi = boot_ci(r[k, 1], r[k, 0])
    print(f" POOLED impl>0.15 (clustered by 15m start across assets): n={k.sum()} pnl={m:+.4f} [{lo:+.4f},{hi:+.4f}]")
