"""Idea 1: cross-asset consistency / lead-lag among btc/eth/sol/xrp 5m PM markets.
python -I a1_crossasset.py"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import meta, Mkt, boot_ci, TD
from common import RAW
A = ["btc", "eth", "sol", "xrp"]
M = meta()
def fee_rate(a, t):
    if a == "btc":
        return 0.05 if t >= 1795219140 else 0.07   # 2026-11-20 23:59 UTC
    return 0.01
def lg(p):
    p = np.clip(p, 0.01, 0.99); return np.log(p / (1 - p))

# --- (a) outcome correlation from official results (all meta) ---
starts = sorted({v["start"] for v in M.values() if v["dur"] == "5m"})
Y = {a: [] for a in A}; S = []
for s in starts:
    r = [M.get(f"{a}-updown-5m-{s}") for a in A]
    if all(x and x["res"][0] in ("0", "1") and x["res"][0] != x["res"][1] for x in r):
        S.append(s)
        for a, x in zip(A, r):
            Y[a].append(int(x["res"][0] == "1"))
Yarr = np.array([Y[a] for a in A]); print("windows with all 4 results:", len(S))
print("outcome corr:\n", np.round(np.corrcoef(Yarr), 3))
R = {}
for a in A:
    R[a] = np.array([(M[f"{a}-updown-5m-{s}"]["f"] or np.nan) / (M[f"{a}-updown-5m-{s}"]["k"] or np.nan) - 1 for s in S])
print("TWAP-return corr:\n", np.round(np.corrcoef(np.array([R[a] for a in A])), 3))
print("P(eth agrees btc)=%.3f sol %.3f xrp %.3f" % tuple((Yarr[i] == Yarr[0]).mean() for i in (1, 2, 3)))

# --- load windows with trades for all 4 ---
have = [s for s in S if all(os.path.exists(os.path.join(TD, f"{a}-updown-5m-{s}.json.gz")) for a in A)]
print("windows with trades for all 4:", len(have))
taus = [30, 60, 90, 120, 150, 180, 210, 240, 270]
rows = []  # (s, tau, p[4], y[4], mk)
mk = {}
for s in have:
    ms = [Mkt(f"{a}-updown-5m-{s}") for a in A]
    mk[s] = ms
    for tau in taus:
        rows.append((s, tau, [m.last_up(s + tau, 20) for m in ms], [m.yes for m in ms]))
half = np.median(have) if have else 0

# --- (b) does leader's price add info to laggard's own price? logistic regression ---
def logit_fit(X, y):
    X = np.column_stack([np.ones(len(X)), X]); b = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ b)); W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + 1e-6 * np.eye(len(b)); b += np.linalg.solve(H, X.T @ (y - p))
    return b
rng = np.random.default_rng(1)
print("\n(b) logit(y_x) ~ logit(p_x) + logit(p_lead): coef on leader (95% window-bootstrap CI)")
for tau in [60, 120, 180, 240]:
    for xi in (1, 2, 3):
        for li in (0,):
            d = [(r[2][xi], r[2][li], r[3][xi], r[0]) for r in rows if r[1] == tau and not np.isnan(r[2][xi]) and not np.isnan(r[2][li])]
            if len(d) < 200: continue
            d = np.array(d); X = np.column_stack([lg(d[:, 0]), lg(d[:, 1])]); y = d[:, 2]
            b = logit_fit(X, y)
            bs = [logit_fit(X[i], y[i])[2] for i in (rng.integers(0, len(y), (200, len(y))))]
            print(f" tau={tau} {A[xi]}<-{A[li]} n={len(y)} own={b[1]:.2f} lead={b[2]:.2f} [{np.percentile(bs,2.5):.2f},{np.percentile(bs,97.5):.2f}]")
    # reverse: does alt price add to btc?
    d = [(r[2][0], np.nanmean(r[2][1:]), r[3][0]) for r in rows if r[1] == tau and not np.isnan(r[2][0]) and not np.all(np.isnan(r[2][1:]))]
    if len(d) > 200:
        d = np.array(d); X = np.column_stack([lg(d[:, 0]), lg(d[:, 1])]); b = logit_fit(X, d[:, 2])
        bs = [logit_fit(X[i], d[i, 2])[2] for i in rng.integers(0, len(d), (200, len(d)))]
        print(f" tau={tau} btc<-altmean n={len(d)} own={b[1]:.2f} alt={b[2]:.2f} [{np.percentile(bs,2.5):.2f},{np.percentile(bs,97.5):.2f}]")

# --- (c) laggard rule ---
print("\n(c) rule: leader |p-0.5|>=TH, laggard |p-0.5|<=0.08 -> buy laggard side in leader direction at next taker BUY fill (<=20s)")
for lead in (0, "alts"):
    for TH in (0.15, 0.25):
        for xi in ((1, 2, 3) if lead == 0 else (0,)):
            pnl, cl, ts_ = [], [], []
            for s in have:
                ms = mk[s]
                for tau in taus[:-1]:
                    ps = [m.last_up(s + tau, 20) for m in ms]
                    if lead == 0:
                        pl = ps[0]
                    else:
                        alt = [p for p in ps[1:] if not np.isnan(p)]
                        pl = np.mean(alt) if len(alt) >= 2 else np.nan
                    px = ps[xi]
                    if np.isnan(pl) or np.isnan(px): continue
                    if abs(pl - 0.5) >= TH and abs(px - 0.5) <= 0.08:
                        side = 0 if pl > 0.5 else 1
                        f = ms[xi].buy_fill(side, s + tau, 20)
                        if np.isnan(f): break
                        win = (ms[xi].yes == 1) if side == 0 else (ms[xi].yes == 0)
                        fr = fee_rate(A[xi], s)
                        pnl.append(win - f - fr * f * (1 - f)); cl.append(s); ts_.append(f)
                        break
            if len(pnl) < 20:
                print(f" lead={lead} TH={TH} x={A[xi]} n={len(pnl)}"); continue
            pnl = np.array(pnl); cl = np.array(cl)
            m, lo, hi = boot_ci(pnl, cl)
            h1 = pnl[cl < half].mean() if (cl < half).any() else np.nan; h2 = pnl[cl >= half].mean() if (cl >= half).any() else np.nan
            print(f" lead={lead} TH={TH} x={A[xi]} n={len(pnl)} avgpx={np.mean(ts_):.3f} pnl/sh={m:+.4f} [{lo:+.4f},{hi:+.4f}] H1={h1:+.4f} H2={h2:+.4f}")

# --- (d) lead-lag of 5s-binned Up-price changes ---
print("\n(d) lead-lag: corr(dP_btc(t), dP_x(t+lag)), 10s bins, pooled within windows")
for xi in (1, 2, 3):
    out = {}
    for lag in (-30, -20, -10, 0, 10, 20, 30):
        a_, b_ = [], []
        for s in have:
            ms = mk[s]
            g = np.arange(s + 10, s + 290, 10)
            pb = np.array([ms[0].last_up(t, 10) for t in g]); px = np.array([ms[xi].last_up(t, 10) for t in g])
            db = np.diff(pb); dx = np.diff(px)
            k = lag // 10
            if k >= 0:
                u, v = db[:len(db) - k], dx[k:]
            else:
                u, v = db[-k:], dx[:len(dx) + k]
            ok = ~np.isnan(u) & ~np.isnan(v)
            a_ += list(u[ok]); b_ += list(v[ok])
        out[lag] = (np.corrcoef(a_, b_)[0, 1] if len(a_) > 50 else np.nan, len(a_))
    print(" ", A[xi], " ".join(f"{l:+d}:{c:.3f}" for l, (c, n) in out.items()), "n~", out[0][1])
