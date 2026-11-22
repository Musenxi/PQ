"""Idea 2: PM-implied vol vs Deribit DVOL vs Coinbase realised vol (BTC, ETH 5m).
python -I a2_impliedvol.py"""
import os, sys, numpy as np
from scipy.stats import norm
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import meta, Mkt, boot_ci, TD
from common import RAW, load_gz
M = meta()
YEAR = 365 * 86400
def fee_rate(a, t):
    if a == "btc": return 0.05 if t >= 1795219140 else 0.07
    return 0.01
for asset, cur in (("btc", "BTC"), ("eth", "ETH"), ("sol", "SOL"), ("xrp", "XRP")):
    cb = np.array(load_gz(os.path.join(RAW, f"cb_{cur}_1m.json.gz")), float)
    cbt = {int(r[0]): r for r in cb}
    lr = np.diff(np.log(cb[:, 4])); lrt = cb[1:, 0]
    dv = None
    if cur in ("BTC", "ETH"):
        d = np.array(load_gz(os.path.join(RAW, f"dvol_{cur}.json.gz")), float); dv = {int(r[0] // 1000): r[4] for r in d}
    def rv(t, mins):
        i = np.searchsorted(lrt, t); x = lr[max(0, i - mins):i]
        return np.sqrt(np.mean(x ** 2) / 60) if len(x) > mins * 0.8 else np.nan
    slugs = sorted(k for k, v in M.items() if v["asset"] == asset and v["dur"] == "5m" and os.path.exists(os.path.join(TD, k + ".json.gz")) and v["k"])
    rows = []
    for sl in slugs:
        v = M[sl]; s = v["start"]; m = Mkt(sl)
        c0 = cbt.get(s - 60)
        if c0 is None: continue
        k0 = (c0[3] + c0[4]) / 2
        sig = {"rv60": rv(s, 60), "rv1d": rv(s, 1440), "dvol": (dv.get(s - 60, np.nan) / 100 / np.sqrt(YEAR)) if dv else np.nan}
        for tau in (60, 120, 180, 240):
            c = cbt.get(s + tau - 60)
            p = m.last_up(s + tau, 15)
            if c is None or np.isnan(p): continue
            x = np.log(c[4] / k0); T = 300 - tau - 40
            rows.append(dict(s=s, tau=tau, p=p, x=x, T=T, y=m.yes, **sig, m=m))
    if len(rows) < 300:
        print(asset, "rows", len(rows)); continue
    S = np.array([r["s"] for r in rows]); half = np.median(np.unique(S))
    P = np.array([r["p"] for r in rows]); X = np.array([r["x"] for r in rows]); T = np.array([r["T"] for r in rows]); Y = np.array([r["y"] for r in rows])
    z = X / np.sqrt(T)
    # PM-implied sigma per day: regress probit(p) on z through origin (only informative |z| region)
    pr = norm.ppf(np.clip(P, 0.03, 0.97))
    print(f"\n=== {asset} rows={len(rows)} windows={len(np.unique(S))}")
    print(" day  sigPM(ann%)  DVOL  RV60med  RV1d   (ann %)")
    day = (S // 86400)
    for dd in np.unique(day):
        k = (day == dd) & (np.abs(pr) < 1.8)
        if k.sum() < 50: continue
        b = (pr[k] * z[k]).sum() / (z[k] ** 2).sum()
        f = lambda key: np.nanmedian([rows[i][key] for i in np.where(day == dd)[0]]) * np.sqrt(YEAR) * 100
        print(f" {int(dd)%1000:4d} {100*np.sqrt(YEAR)/b:8.1f} {f('dvol'):6.1f} {f('rv60'):7.1f} {f('rv1d'):6.1f}")
    def ll(q): q = np.clip(q, 0.005, 0.995); return -np.mean(Y * np.log(q) + (1 - Y) * np.log(1 - q))
    print(f" logloss PM={ll(np.clip(P,0.005,0.995)):.4f}")
    for key in ("rv60", "rv1d", "dvol"):
        sg = np.array([r[key] for r in rows]); ok = ~np.isnan(sg)
        if ok.sum() < 300: continue
        for mult in (1.0,):
            q = norm.cdf(z / (sg * mult))
            # calibrate scale on first half only (1-parameter), test on 2nd
            h1 = ok & (S < half); h2 = ok & (S >= half)
            best = min(np.arange(0.5, 2.51, 0.05), key=lambda c: (lambda qq: -np.mean(Y[h1]*np.log(qq)+(1-Y[h1])*np.log(1-qq)))(np.clip(norm.cdf(z[h1]/(sg[h1]*c)),0.005,0.995)))
            q2 = np.clip(norm.cdf(z / (sg * best)), 0.005, 0.995)
            llq = lambda k: -np.mean(Y[k] * np.log(q2[k]) + (1 - Y[k]) * np.log(1 - q2[k]))
            llp = lambda k: -np.mean(Y[k] * np.log(np.clip(P[k], .005, .995)) + (1 - Y[k]) * np.log(1 - np.clip(P[k], .005, .995)))
            print(f" model {key}: scale(fit H1)={best:.2f}  H2 logloss model={llq(h2):.4f} PM={llp(h2):.4f}")
            # rule: model vs PM disagreement > D -> buy model side at next taker BUY fill, one per window (first tau)
            for D in (0.08, 0.15):
                pnl, cl = [], []
                seen = set()
                for i, r in enumerate(rows):
                    if not ok[i] or r["s"] in seen or r["s"] < half: continue
                    dq = q2[i] - r["p"]
                    if abs(dq) < D: continue
                    side = 0 if dq > 0 else 1
                    f = r["m"].buy_fill(side, r["s"] + r["tau"], 20)
                    if np.isnan(f): continue
                    seen.add(r["s"])
                    win = (r["y"] == 1) if side == 0 else (r["y"] == 0)
                    pnl.append(win - f - fee_rate(asset, r["s"]) * f * (1 - f)); cl.append(r["s"])
                if len(pnl) >= 20:
                    mm, lo, hi = boot_ci(pnl, cl)
                    print(f"   rule D={D} (H2 only, OOS) n={len(pnl)} pnl/sh={mm:+.4f} [{lo:+.4f},{hi:+.4f}]")
    # incremental: is the PM over/under-reacting to z conditional on vol regime? logistic y ~ probit(p) by DVOL/RV tercile
    sg = np.array([r["rv60"] for r in rows]); dvv = np.array([r["dvol"] for r in rows])
    ratio = sg / dvv if not np.all(np.isnan(dvv)) else sg / np.nanmedian(sg)
    okr = ~np.isnan(ratio)
    qs = np.nanpercentile(ratio[okr], [33, 67])
    print(" calibration slope of y on logit(p_PM), by RV60/DVOL tercile (slope>1 => PM under-confident):")
    for lo_, hi_, nm in ((-1, qs[0], "lowRV"), (qs[0], qs[1], "mid"), (qs[1], 99, "highRV")):
        k = okr & (ratio > lo_) & (ratio <= hi_)
        Xk = np.column_stack([np.ones(k.sum()), np.log(np.clip(P[k],.02,.98)/(1-np.clip(P[k],.02,.98)))]); b = np.zeros(2)
        for _ in range(30):
            pp = 1 / (1 + np.exp(-Xk @ b)); W = pp * (1 - pp); b += np.linalg.solve(Xk.T @ (Xk * W[:, None]), Xk.T @ (Y[k] - pp))
        print(f"   {nm}: n={k.sum()} slope={b[1]:.2f} (fair=1; >1 => PM under-confident)")
