"""Build analysis tables from the raw cache.

Usage: python -I build.py <kind> <rawdir> <outdir>
Writes <outdir>/<kind>_fills.pkl (taker BUY fills, t>=0) and <kind>_win.pkl (per-window checkpoints).
Up-mid proxy before each fill = median of fill-implied Up prices of the previous 7 fills
(Up fill at p -> p, Down fill at p -> 1-p), strictly prior (no lookahead).
Crossing: state + when mid>0.53, - when mid<0.47; crossed = a +/- flip happened before the fill.
"""
import gzip, json, os, sys
from collections import deque
import numpy as np, pandas as pd

STEP = {"5m": 300, "15m": 900, "1h": 3600}
CUTOFF = 1795219140  # 2026-11-20 23:59 UTC
RATE_OLD = {"5m": 0.07, "15m": 0.07, "1h": 0.07}
RATE_NEW = {"5m": 0.05, "15m": 0.05, "1h": 0.01}


def main():
    kind, raw, out = sys.argv[1], sys.argv[2], sys.argv[3]
    T = STEP[kind]
    mdir, tdir = f"{raw}/{kind}/meta", f"{raw}/{kind}/trades"
    cps = [T * k // 10 for k in range(1, 10)]  # checkpoints at 10%..90%
    F, W = [], []
    skipped = {"missing": 0, "unresolved": 0, "notrades": 0}
    for fn in sorted(os.listdir(tdir)):
        if not fn.endswith(".json.gz"):
            continue
        s = int(fn.split(".")[0])
        m = json.load(open(f"{mdir}/{s}.json"))
        try:
            op = [float(x) for x in json.loads(m["outcomePrices"])]
        except Exception:
            skipped["missing"] += 1; continue
        if sorted(op) != [0.0, 1.0]:
            skipped["unresolved"] += 1; continue
        upwin = 1 if op[0] == 1.0 else 0
        rows = json.load(gzip.open(f"{tdir}/{fn}", "rt"))
        rows.reverse()  # API is newest-first; reverse -> chronological
        rows = [r for r in rows if s <= r[0] < s + T]
        if len(rows) < 10:
            skipped["notrades"] += 1; continue
        last = deque(maxlen=7)
        state, crossed = 0, False
        imb = 0.0; vol = 0.0
        cpi = 0; cprec = {}
        rate = RATE_NEW[kind] if s >= CUTOFF else RATE_OLD[kind]
        for ts, oi, side, p, size, wal in rows:
            t = ts - s
            while cpi < len(cps) and t >= cps[cpi]:
                mid = float(np.median(last)) if last else np.nan
                cprec[cps[cpi]] = (mid, imb, vol, crossed)
                cpi += 1
            mid = float(np.median(last)) if last else np.nan
            if side == 1:
                F.append((s, t, oi, p, size, p * size, mid, crossed,
                          int((oi == 0) == (upwin == 1)), rate, wal))
            # update state with this fill
            u = p if oi == 0 else 1 - p
            last.append(u)
            # signed $ flow toward Up
            usd = p * size
            imb += usd if (oi == 0) == (side == 1) else -usd
            vol += usd
            m2 = float(np.median(last))
            ns = 1 if m2 > 0.53 else (-1 if m2 < 0.47 else 0)
            if ns != 0:
                if state != 0 and ns != state:
                    crossed = True
                state = ns
        while cpi < len(cps):
            mid = float(np.median(last)) if last else np.nan
            cprec[cps[cpi]] = (mid, imb, vol, crossed); cpi += 1
        for c, (mid, im, vo, cr) in cprec.items():
            W.append((s, c, mid, im, vo, cr, upwin))
    f = pd.DataFrame(F, columns=["start", "t", "oi", "p", "size", "usd", "mid", "crossed", "win", "rate", "wal"])
    w = pd.DataFrame(W, columns=["start", "cp", "mid", "imb", "vol", "crossed", "upwin"])
    f.to_pickle(f"{out}/{kind}_fills.pkl"); w.to_pickle(f"{out}/{kind}_win.pkl")
    print(kind, "windows", w.start.nunique(), "buy fills", len(f), "skipped", skipped)


if __name__ == "__main__":
    main()
