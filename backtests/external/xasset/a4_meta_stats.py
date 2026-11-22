"""Idea 4 (meta only): base rates, autocorrelation of consecutive 5m outcomes, weekend vs weekday, by asset.
python -I a4_meta_stats.py"""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import meta, boot_ci
M = meta()
for d in ("5m", "15m", "1h"):
    for a in ("btc", "eth", "sol", "xrp"):
        v = sorted((x for x in M.values() if x["asset"] == a and x["dur"] == d and x["res"][0] != x["res"][1]), key=lambda x: x["start"])
        if len(v) < 100: continue
        y = np.array([int(x["res"][0] == "1") for x in v]); s = np.array([x["start"] for x in v])
        r = np.array([(x["f"] / x["k"] - 1) if x["f"] and x["k"] else np.nan for x in v])
        cons = np.diff(s) == {"5m": 300, "15m": 900, "1h": 3600}[d]
        ac = np.corrcoef(y[:-1][cons], y[1:][cons])[0, 1]
        ok = cons & ~np.isnan(r[:-1]) & ~np.isnan(r[1:])
        acr = np.corrcoef(r[:-1][ok], r[1:][ok])[0, 1]
        wd = ((s // 86400 + 4) % 7)  # 0=Mon
        we = wd >= 5
        print(f"{a} {d} n={len(y)} Up={y.mean():.3f} acf(outcome)={ac:+.3f} acf(ret)={acr:+.3f} (se~{1/np.sqrt(cons.sum()):.3f}) Up weekend={y[we].mean():.3f} weekday={y[~we].mean():.3f}")
