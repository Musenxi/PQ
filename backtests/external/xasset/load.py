"""Build per-market price snapshots from trades. Up-equivalent price series.
snap(slug, t) -> dict with last Up-equivalent trade price at or before t, VWAP in [t-W,t],
and first taker BUY fill of each side within (t, t+H]."""
import os, sys, bisect
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RAW, load_gz

TD = os.path.join(RAW, "trades")
META = None

def meta():
    global META
    if META is None:
        META = {}
        for fn in ("meta.json.gz", "meta_rev.json.gz"):
            if os.path.exists(os.path.join(RAW, fn)):
                META.update({k: v for k, v in load_gz(os.path.join(RAW, fn)).items() if v})
    return META

class Mkt:
    def __init__(self, slug):
        self.m = meta()[slug]
        p = os.path.join(TD, slug + ".json.gz")
        rows = load_gz(p) if os.path.exists(p) else []
        a = np.array(rows, dtype=float).reshape(-1, 5)
        self.ts, self.oi, self.side, self.px, self.sz = a.T if len(a) else [np.zeros(0)] * 5
        # Up-equivalent price
        self.up = np.where(self.oi == 0, self.px, 1 - self.px)
        self.ok = len(a) > 0
        self.yes = 1 if self.m["res"][0] in ("1", 1, "1.0") else 0

    def last_up(self, t, maxage=30):
        i = bisect.bisect_right(self.ts, t) - 1
        if i < 0 or t - self.ts[i] > maxage:
            return np.nan
        # median of trades in the last 5s up to t (reduce bounce)
        j = bisect.bisect_left(self.ts, self.ts[i] - 5)
        return float(np.median(self.up[j:i + 1]))

    def vwap_up(self, t0, t1):
        i, j = bisect.bisect_right(self.ts, t0), bisect.bisect_right(self.ts, t1)
        if j <= i:
            return np.nan
        w = self.sz[i:j]
        return float((self.up[i:j] * w).sum() / w.sum())

    def buy_fill(self, outcome, t, h=20, minsize=0):
        """first taker BUY of outcome (0 Up, 1 Down) in (t, t+h]; returns price paid"""
        i = bisect.bisect_right(self.ts, t)
        while i < len(self.ts) and self.ts[i] <= t + h:
            if self.oi[i] == outcome and self.side[i] == 1 and self.sz[i] >= minsize:
                return float(self.px[i])
            i += 1
        return np.nan

def boot_ci(x, clusters=None, B=2000, seed=0):
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    if clusters is None:
        idx = rng.integers(0, len(x), (B, len(x)))
        m = x[idx].mean(1)
    else:
        cl = np.asarray(clusters); u, inv = np.unique(cl, return_inverse=True)
        s = np.bincount(inv, x); c = np.bincount(inv)
        idx = rng.integers(0, len(u), (B, len(u)))
        m = s[idx].sum(1) / c[idx].sum(1)
    return float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))
