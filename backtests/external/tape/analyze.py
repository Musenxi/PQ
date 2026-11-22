"""Hypothesis tests on the taker tape. Usage: python -I analyze.py <kind> <tbldir> [csv_out_dir]
Entry = taker BUY fill at price p on its outcome. ret/$ = (win - p - f)/(p + f), f = rate*p*(1-p).
Split by window start: first half (A, explore) / second half (B, confirm). CIs: window-clustered
Poisson bootstrap (2000 reps), 95% percentile.
"""
import sys, warnings
import numpy as np, pandas as pd
import statsmodels.api as sm
warnings.filterwarnings("ignore")
STEP = {"5m": 300, "15m": 900, "1h": 3600}
rng = np.random.default_rng(7)
NV = [0]


def boot(d, col="ret", reps=2000):
    if len(d) == 0:
        return (np.nan, np.nan, np.nan, 0, 0)
    g = d.groupby("start")[col].agg(["sum", "count"])
    S, N = g["sum"].values, g["count"].values
    k = rng.poisson(1.0, (reps, len(S)))
    bs = (k @ S) / np.maximum(k @ N, 1)
    return (S.sum() / N.sum(), *np.percentile(bs, [2.5, 97.5]), int(N.sum()), len(S))


def fmt(r, pct=True):
    m, lo, hi, n, w = r
    if n == 0:
        return "n=0"
    s = 100 if pct else 1
    return f"{m*s:+.1f}% [{lo*s:+.1f},{hi*s:+.1f}] n={n} w={w}"


def both(f, mask, label, first=False, col="ret"):
    NV[0] += 1
    out = [label]
    for h in ("A", "B"):
        d = f[mask & (f.half == h)]
        if first:
            d = d.sort_values(["start", "t"]).groupby("start").head(1)
        out.append(fmt(boot(d, col)))
    print(" | ".join(out))


def main():
    kind, tbl = sys.argv[1], sys.argv[2]
    T = STEP[kind]
    f = pd.read_pickle(f"{tbl}/{kind}_fills.pkl")
    w = pd.read_pickle(f"{tbl}/{kind}_win.pkl")
    starts = np.sort(f.start.unique())
    cut = starts[len(starts) // 2]
    f["half"] = np.where(f.start < cut, "A", "B")
    w["half"] = np.where(w.start < cut, "A", "B")
    fee = f.rate * f.p * (1 - f.p)
    f["ret"] = (f.win - f.p - fee) / (f.p + fee)
    f["edge"] = f.win - f.p
    f = f[(f.p > 0.01) & (f.p < 0.99)].copy()
    ts = pd.to_datetime(f.start, unit="s", utc=True)
    print(f"== {kind}: windows {len(starts)} (A {np.sum(starts<cut)}, B {np.sum(starts>=cut)}), "
          f"{pd.to_datetime(starts[0],unit='s')} .. {pd.to_datetime(starts[-1],unit='s')}, "
          f"taker BUY fills {len(f)}; Up win rate {w.groupby('start').upwin.first().mean():.3f}")

    # (a) calibration
    print("-- (a) calibration: edge=win-p (pp), all taker BUY fills, by price x time-third")
    f["pb"] = (f.p * 10).astype(int) / 10
    f["tb"] = np.minimum(f.t * 3 // T, 2)
    for h in ("A", "B"):
        tab = f[f.half == h].pivot_table(index="pb", columns="tb", values="edge", aggfunc="mean") * 100
        print(h, "\n", tab.round(1).to_string())
    for h in ("A", "B"):
        d = f[(f.half == h)]
        X = sm.add_constant(np.log(d.p / (1 - d.p)))
        r = sm.GLM(d.win, X, family=sm.families.Binomial()).fit(cov_type="cluster", cov_kwds={"groups": d.start})
        print(f"logit slope {h}: {r.params.iloc[1]:.3f} ± {1.96*r.bse.iloc[1]:.3f} (const {r.params.iloc[0]:+.3f})")
    print("-- ROI/$ by price band (all t)")
    for lo, hi in [(0.05, 0.3), (0.3, 0.5), (0.5, 0.55), (0.55, 0.75), (0.75, 0.9), (0.9, 0.99)]:
        both(f, (f.p >= lo) & (f.p < hi), f"p[{lo},{hi}) all-fills")
    # (b)/(c) band + chop
    print("-- (b,c) band & chop (t>=30s); all fills | first qualifying fill per window")
    t30 = f.t >= 30
    band = (f.p >= 0.55) & (f.p <= 0.75)
    cheap = (f.p >= 0.25) & (f.p <= 0.45)
    for nm, bm in (("band.55-.75", band), ("cheap.25-.45", cheap)):
        both(f, bm & t30, f"{nm} t>=30 all")
        both(f, bm & t30 & ~f.crossed, f"{nm} NOT crossed")
        both(f, bm & t30 & f.crossed, f"{nm} crossed")
        both(f, bm & t30 & ~f.crossed, f"{nm} NOT crossed first/win", first=True)
        both(f, bm & t30 & f.crossed, f"{nm} crossed first/win", first=True)
    if kind == "1h":
        print("-- 1h early vs later, band .55-.75")
        both(f, band & (f.t < 300), "band first5min all")
        both(f, band & (f.t < 300), "band first5min first/win", first=True)
        both(f, band & (f.t >= 300), "band later all")
        both(f, cheap & (f.t < 300), "cheap first5min all")
    # (d) structure
    print("-- (d) band .55-.75 by UTC hour block")
    hr = ts.dt.hour // 4
    for b in range(6):
        both(f, band & (hr == b), f"band h{b*4:02d}-{b*4+4:02d}")
    print("-- (d) band by weekday-vs-weekend")
    we = ts.dt.weekday >= 5
    both(f, band & we, "band weekend"); both(f, band & ~we, "band weekday")
    print("-- (d) by fill size (shares) quintile, band and cheap")
    qs = f["size"].quantile([0.2, 0.4, 0.6, 0.8]).values
    sq = np.searchsorted(qs, f["size"].values)
    for q in range(5):
        both(f, band & (sq == q), f"band sizeQ{q+1}")
    for q in range(5):
        both(f, cheap & (sq == q), f"cheap sizeQ{q+1}")
    print("-- (d) last 20% of window, by price band")
    late = f.t >= 0.8 * T
    for lo, hi in [(0.05, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 0.99)]:
        both(f, late & (f.p >= lo) & (f.p < hi), f"late p[{lo},{hi})")
    # 4. flow
    print("-- (4) flow: upwin ~ logit(mid) + imb/vol at checkpoints; fit A, OOS logloss on B")
    w = w.dropna(subset=["mid"])
    w = w[(w.vol > 0)]
    w["lm"] = np.log(w.mid.clip(0.01, 0.99) / (1 - w.mid.clip(0.01, 0.99)))
    w["fi"] = w.imb / w.vol
    for cp in sorted(w.cp.unique()):
        a, b = w[(w.cp == cp) & (w.half == "A")], w[(w.cp == cp) & (w.half == "B")]
        res = []
        for d in (a, b):
            r = sm.GLM(d.upwin, sm.add_constant(d[["lm", "fi"]]), family=sm.families.Binomial()).fit()
            res.append(f"fi={r.params['fi']:+.2f}±{1.96*r.bse['fi']:.2f} lm={r.params['lm']:.2f}")
        r0 = sm.GLM(a.upwin, sm.add_constant(a[["lm"]]), family=sm.families.Binomial()).fit()
        r1 = sm.GLM(a.upwin, sm.add_constant(a[["lm", "fi"]]), family=sm.families.Binomial()).fit()
        def ll(r, X):
            p = np.clip(r.predict(sm.add_constant(X, has_constant="add")), 1e-6, 1 - 1e-6)
            return -np.mean(b.upwin * np.log(p) + (1 - b.upwin) * np.log(1 - p))
        print(f"t={cp}s A:{res[0]} | B:{res[1]} | OOS logloss mid-only {ll(r0, b[['lm']]):.4f} +flow {ll(r1, b[['lm','fi']]):.4f}")
        NV[0] += 1
    print("-- (4) large taker BUY fills (top1% size, threshold from A): edge win-p and ROI")
    thr = f[f.half == "A"]["size"].quantile(0.99)
    big = f["size"] >= thr
    print(f"top1% threshold {thr:.0f} shares")
    both(f, big, "big fills edge(pp)", col="edge")
    both(f, ~big, "other fills edge(pp)", col="edge")
    both(f, big, "big fills ROI")
    both(f, big & (f.p >= 0.3) & (f.p <= 0.7), "big fills p.3-.7 edge", col="edge")
    print(f"variants printed: {NV[0]}")


if __name__ == "__main__":
    main()
