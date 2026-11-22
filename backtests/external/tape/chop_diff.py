"""Paired window-bootstrap CI of (NOT crossed - crossed) ROI difference, band & cheap, t>=30s.
Also writes a small summary CSV. Usage: python -I chop_diff.py <kind> <tbldir> <csvdir>"""
import sys
import numpy as np, pandas as pd
rng = np.random.default_rng(11)


def diff_ci(d, m1, m2, reps=2000):
    g = d.assign(a=np.where(m1, d.ret, 0), na=m1.astype(int), b=np.where(m2, d.ret, 0), nb=m2.astype(int)) \
        .groupby("start")[["a", "na", "b", "nb"]].sum()
    A, NA, B, NB = (g[c].values for c in ("a", "na", "b", "nb"))
    k = rng.poisson(1, (reps, len(g)))
    bs = (k @ A) / np.maximum(k @ NA, 1) - (k @ B) / np.maximum(k @ NB, 1)
    return A.sum() / NA.sum() - B.sum() / NB.sum(), *np.percentile(bs, [2.5, 97.5])


def main():
    kind, tbl, out = sys.argv[1:4]
    f = pd.read_pickle(f"{tbl}/{kind}_fills.pkl")
    f = f[(f.p > 0.01) & (f.p < 0.99)]
    fee = f.rate * f.p * (1 - f.p)
    f = f.assign(ret=(f.win - f.p - fee) / (f.p + fee))
    starts = np.sort(f.start.unique()); cut = starts[len(starts) // 2]
    rows = []
    for nm, lo, hi in (("band", .55, .75), ("cheap", .25, .45)):
        for h in ("A", "B", "all"):
            d = f if h == "all" else f[(f.start < cut) == (h == "A")]
            d = d[(d.p >= lo) & (d.p <= hi) & (d.t >= 30)]
            for first in (False, True):
                dd = d.sort_values(["start", "t"])
                if first:  # first qualifying fill per window within each group
                    dd = pd.concat([dd[~dd.crossed].groupby("start").head(1), dd[dd.crossed].groupby("start").head(1)])
                m, lo_, hi_ = diff_ci(dd, ~dd.crossed.values, dd.crossed.values)
                rows.append((kind, nm, h, "first" if first else "all", round(m * 100, 2), round(lo_ * 100, 2), round(hi_ * 100, 2)))
                print(*rows[-1])
    pd.DataFrame(rows, columns=["kind", "band", "half", "weight", "diff_notcrossed_minus_crossed_pct", "lo", "hi"]) \
        .to_csv(f"{out}/chop_diff_{kind}.csv", index=False)


if __name__ == "__main__":
    main()
