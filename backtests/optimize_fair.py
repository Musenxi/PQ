#!/usr/bin/env python3
"""Fair-model optimisation study, walk-forward honest.

Question: can a better P(Up) model be extracted from our recorded
features? Candidates vs the farm's TWAP-normal baseline (M0):
  M1  vol rescale: z' = z / m, m picked on train by log-loss
  M2  logistic recalibration on [z, tau, |z|]
  M3  logistic on [z, tau, |z|, ret20_z, ret60_z, spread]
Fitted on train windows only, evaluated on test windows only:
  - per-tick log-loss / Brier (calibration)
  - his metric: for first-per-window buys with model-ask gap >= 0.03,
    win share minus average price, by price band
  - simulated single-entry PnL at gap >= 0.05, $6, taker fee 0.07
Two folds: A = train first 60% / test last 40%; B = reverse (still
out-of-sample). A variant counts only if it helps in BOTH folds.
"""
import math
import os
import sys
from collections import defaultdict
from statistics import NormalDist

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_mval import load

ND = NormalDist()
EPS = 1e-6


def add_features(by_slug):
    all_ticks = []
    for wt in by_slug.values():
        all_ticks.extend(wt)
    all_ticks.sort(key=lambda t: t["_ts"])
    # lagged spot via pointer walk
    import bisect
    times = [t["_ts"] for t in all_ticks]
    spots = [t["spot"] for t in all_ticks]
    for t in all_ticks:
        t["_z"] = ND.inv_cdf(min(max(t["_fair"], 0.001), 0.999))
        for lag, key in ((20, "_r20"), (60, "_r60")):
            j = bisect.bisect_right(times, t["_ts"] - lag) - 1
            if j >= 0 and spots[j] > 0:
                t[key] = math.log(t["spot"] / spots[j]) / (t["_sigma"] * math.sqrt(lag))
            else:
                t[key] = 0.0
        ua, da = t.get("up_ask"), t.get("down_ask")
        t["_spread"] = (ua + da - 1.0) if (ua is not None and da is not None) else 0.02


def feats(t, kind):
    z = t["_z"]
    base = [1.0, z]
    if kind == "M2":
        return base + [t["tau"] / 300.0, abs(z)]
    if kind == "M3":
        return base + [t["tau"] / 300.0, abs(z), t["_r20"], t["_r60"], t["_spread"] * 10.0]
    return base


def fit_logistic(X, y, l2=1e-3, iters=300, lr=0.2):
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-X @ w))
        g = X.T @ (p - y) / len(y) + l2 * w * np.array([0] + [1] * (len(w) - 1))
        w -= lr * g
    return w


def predict(w, X):
    return 1.0 / (1.0 + np.exp(-(X @ w)))


def logloss(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def evaluate(model_fair, by_slug, winners, slugs):
    """model_fair(t) -> P(Up). Returns calibration + trading stats."""
    ys, ps = [], []
    trades = []  # (side, ask, won) first qualifying per window, gap>=0.03
    pnl = 0.0
    n_tr = 0
    for slug in slugs:
        wt = by_slug[slug]
        w = winners[slug]
        y = 1.0 if w == "Up" else 0.0
        picked = None
        picked5 = None
        start = int(slug.rsplit("-", 1)[1])
        for t in wt:
            f = model_fair(t)
            ys.append(y)
            ps.append(f)
            if t["_ts"] - start < 15 or t["tau"] < 20:
                continue
            for side, ask, fs in (("Up", t["up_ask"], f), ("Down", t["down_ask"], 1 - f)):
                if ask is None:
                    continue
                gap = fs - ask
                if picked is None and gap >= 0.03:
                    picked = (side, ask, w == side)
                if picked5 is None and gap >= 0.05:
                    picked5 = (side, ask, w == side)
        if picked:
            trades.append(picked)
        if picked5:
            side, ask, won = picked5
            shares = 6.0 / ask
            fee = shares * 0.07 * ask * (1 - ask)
            pnl += (shares if won else 0.0) - 6.0 - fee
            n_tr += 1
    ys, ps = np.array(ys), np.array(ps)
    bands = [(0.0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]
    band_lines = []
    for lo, hi in bands:
        sub = [tr for tr in trades if lo <= tr[1] < hi]
        if len(sub) >= 8:
            wr = sum(1 for tr in sub if tr[2]) / len(sub)
            ap = sum(tr[1] for tr in sub) / len(sub)
            band_lines.append("%.1f-%.1f: n=%d edge=%+.3f" % (lo, hi, len(sub), wr - ap))
    return {
        "ll": logloss(ps, ys),
        "brier": float(np.mean((ps - ys) ** 2)),
        "trades": len(trades),
        "bands": band_lines,
        "pnl5": pnl,
        "n5": n_tr,
    }


def run_fold(by_slug, winners, train_slugs, test_slugs, label):
    print("\n===== FOLD %s: train %d windows, test %d windows =====" % (label, len(train_slugs), len(test_slugs)))
    Xtr = {k: np.array([feats(t, k) for s in train_slugs for t in by_slug[s]]) for k in ("M2", "M3")}
    ytr = np.array([1.0 if winners[s] == "Up" else 0.0 for s in train_slugs for t in by_slug[s]])
    ws = {k: fit_logistic(Xtr[k], ytr) for k in ("M2", "M3")}
    # M1 vol scale picked on train log-loss
    ztr = np.array([t["_z"] for s in train_slugs for t in by_slug[s]])
    best_m, best_ll = 1.0, 1e9
    for m in (0.75, 0.85, 0.925, 1.0, 1.1, 1.2, 1.35):
        p = np.array([ND.cdf(z / m) for z in ztr])
        ll = logloss(p, ytr)
        if ll < best_ll:
            best_ll, best_m = ll, m
    print("M1 picked vol multiplier m=%.3f (train ll %.4f)" % (best_m, best_ll))
    models = {
        "M0 baseline": lambda t: t["_fair"],
        "M1 volscale": lambda t: ND.cdf(t["_z"] / best_m),
        "M2 logrecal": lambda t: float(predict(ws["M2"], np.array([feats(t, "M2")]))[0]),
        "M3 +flow": lambda t: float(predict(ws["M3"], np.array([feats(t, "M3")]))[0]),
    }
    for name, fn in models.items():
        r = evaluate(fn, by_slug, winners, test_slugs)
        print("%s | ll=%.4f brier=%.4f | gap.03 trades=%d bands[%s] | gap.05 pnl=%+.2f on %d trades"
              % (name, r["ll"], r["brier"], r["trades"], "; ".join(r["bands"]), r["pnl5"], r["n5"]))


def main():
    by_slug, winners = load()
    add_features(by_slug)
    slugs = sorted((s for s in by_slug if s in winners), key=lambda s: int(s.rsplit("-", 1)[1]))
    print("windows:", len(slugs))
    cut = int(0.6 * len(slugs))
    run_fold(by_slug, winners, slugs[:cut], slugs[cut:], "A (early->late)")
    run_fold(by_slug, winners, slugs[cut:], slugs[:cut], "B (late->early)")


if __name__ == "__main__":
    main()
