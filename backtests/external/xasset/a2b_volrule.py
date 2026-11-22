"""Robustness of the vol-model-vs-PM rule (idea 2). Parameter-free: scale=1.
Model q = Phi( ln(S_cb/K_cb) / (sigma*sqrt(T_eff)) ), T_eff = 260 - tau (60s TWAP settle),
S_cb = Coinbase 1m close at s+tau, K_cb = mid of Coinbase candle [s-60,s) (proxy of Chainlink 60s TWAP strike).
Signal: |q - p_PM| >= D, p_PM = median of trades in last 5s (<=15s old). Entry: first taker BUY fill of model side
in (t+lat, t+20]. One trade per window (first tau in 60,120,180,240 that triggers).
python -I a2b_volrule.py ASSET"""
import os, sys, numpy as np
from scipy.stats import norm
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import meta, Mkt, boot_ci, TD
from common import RAW, load_gz
M = meta(); YEAR = 365 * 86400
asset = sys.argv[1] if len(sys.argv) > 1 else "btc"; cur = asset.upper()
def fee_rate(a, t):
    if a == "btc": return 0.05 if t >= 1795219140 else 0.07
    return 0.01
cb = np.array(load_gz(os.path.join(RAW, f"cb_{cur}_1m.json.gz")), float); cbt = {int(r[0]): r for r in cb}
lr = np.diff(np.log(cb[:, 4])); lrt = cb[1:, 0]
dv = {}
if cur in ("BTC", "ETH"):
    dv = {int(r[0] // 1000): r[4] for r in load_gz(os.path.join(RAW, f"dvol_{cur}.json.gz"))}
def rv(t, mins):
    i = np.searchsorted(lrt, t); x = lr[max(0, i - mins):i]
    return np.sqrt(np.mean(x ** 2) / 60) if len(x) > mins * 0.8 else np.nan
slugs = sorted(k for k, v in M.items() if v["asset"] == asset and v["dur"] == "5m" and os.path.exists(os.path.join(TD, k + ".json.gz")))
W = []
for sl in slugs:
    s = M[sl]["start"]; c0 = cbt.get(s - 60)
    if c0 is None: continue
    m = Mkt(sl)
    if not m.ok: continue
    sig = {"dvol": dv.get(s - 60, np.nan) / 100 / np.sqrt(YEAR) if dv else np.nan, "rv60": rv(s, 60), "fixed": 0.55 / np.sqrt(YEAR)}
    obs = []
    for tau in (60, 120, 180, 240):
        c = cbt.get(s + tau - 60); p = m.last_up(s + tau, 15)
        if c is None or np.isnan(p): continue
        obs.append((tau, p, np.log(c[4] / ((c0[3] + c0[4]) / 2)), 260 - tau))
    W.append((s, m, sig, obs))
print(asset, "windows", len(W))
allS = np.array([w[0] for w in W]); q1, q2, q3 = np.percentile(allS, [25, 50, 75])
def run(key, D, lat=0, taus=(60, 120, 180, 240)):
    out = []
    for s, m, sig, obs in W:
        sg = sig[key]
        if np.isnan(sg): continue
        for tau, p, x, T in obs:
            if tau not in taus: continue
            q = norm.cdf(x / (sg * np.sqrt(T)))
            if abs(q - p) < D: continue
            side = 0 if q > p else 1
            f = m.buy_fill(side, s + tau + lat, 20 - lat)
            if np.isnan(f): continue
            win = m.yes if side == 0 else 1 - m.yes
            fav = (p > 0.5) == (side == 0)
            out.append((s, win - f - fee_rate(asset, s) * f * (1 - f), f, fav, tau, win - f))
            break
    return out
def rep(name, o):
    if len(o) < 20: print(f" {name}: n={len(o)}"); return
    a = np.array([r[1] for r in o]); cl = np.array([r[0] for r in o])
    m_, lo, hi = boot_ci(a, cl)
    qs = [a[(cl >= lo_) & (cl < hi_)].mean() for lo_, hi_ in ((0, q1), (q1, q2), (q2, q3), (q3, 9e9))]
    print(f" {name}: n={len(o)} px={np.mean([r[2] for r in o]):.3f} fav%={np.mean([r[3] for r in o]):.2f} pnl/sh={m_:+.4f} [{lo:+.4f},{hi:+.4f}] gross={np.mean([r[5] for r in o]):+.4f} quarters=" + " ".join(f"{x:+.3f}" for x in qs))
for key in ("dvol", "rv60", "fixed"):
    for D in (0.05, 0.08, 0.15, 0.25):
        rep(f"{key} D={D}", run(key, D))
print("latency / tau / side breakdown (dvol if available else rv60, D=0.15):")
key = "dvol" if dv else "rv60"
for lat in (1, 2, 5):
    rep(f"lat={lat}s D=0.15", run(key, 0.15, lat))
    rep(f"lat={lat}s D=0.15 rv60", run("rv60", 0.15, lat))
    for k2 in ("rv60", "fixed"):
        rep(f"lat={lat}s D=0.25 {k2}", run(k2, 0.25, lat))
for tau in (60, 120, 180, 240):
    rep(f"tau={tau} only", run(key, 0.15, 0, (tau,)))
o = run(key, 0.15)
rep("favourite side", [r for r in o if r[3]]); rep("cheap side", [r for r in o if not r[3]])
for lo_, hi_ in ((0, .3), (.3, .5), (.5, .7), (.7, 1)):
    rep(f"fill px {lo_}-{hi_}", [r for r in o if lo_ <= r[2] < hi_])
