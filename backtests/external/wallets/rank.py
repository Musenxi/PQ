"""Rank wallets & cluster archetypes from analyze.py outputs.
Usage: python3 -I rank.py <out_prefix> [min_windows=100]
"""
import sys, json, numpy as np, pandas as pd

pre = sys.argv[1]
minw = int(sys.argv[2]) if len(sys.argv) > 2 else 100
w = pd.read_csv(pre + "_wallet_window.csv")
names = json.load(open(pre + "_names.json"))
NW = w.start.nunique()
w["tvol"] = w.vol - w.mvol
g = w.groupby("wallet")
s = pd.DataFrame({
    "nwin": g.size(), "pnl": g.pnl.sum(), "vol": g.vol.sum(), "mvol": g.mvol.sum(), "fee": g.fee.sum(),
    "reb": g.reb.sum(), "mean": g.pnl.mean(), "sd": g.pnl.std(), "winr": g.pnl.apply(lambda x: (x > 0).mean()),
    "both": g.both.mean(), "sell": g.sellvol.sum(), "late": g.late.sum(), "pre": g.pre.sum(), "hivol": g.hivol.sum(),
    "n": g.n.sum(), "two": g.two.mean(),
})
s["tavg"] = (w.tavg * w.vol).groupby(w.wallet).sum() / s.vol
s["qavg"] = (w.qavg * w.vol).groupby(w.wallet).sum() / s.vol
# t-stat over ALL sampled windows (zero pnl when absent) and over active windows
s["t_active"] = s["mean"] / (s.sd / np.sqrt(s.nwin))
s["maker_sh"] = s.mvol / s.vol
s["sell_sh"] = s.sell / s.vol
s["late_sh"] = s.late / s.vol
s["pre_sh"] = s.pre / s.vol
s["hi_sh"] = s.hivol / s.vol
s["roi"] = s.pnl / s.vol
s["pc"] = w[w.both == 1].groupby("wallet").pair_cost.median()
s["epc"] = w.groupby("wallet").epc.median()
s["name"] = [names.get(a, "") for a in s.index]
s["id"] = [a[2:8] for a in s.index]
tot = s.vol.sum()
s["vol_sh"] = s.vol / tot


def arche(r):
    if r.maker_sh >= 0.7 and r.two >= 0.3:
        return "MM_both"          # quotes both sides passively
    if r.maker_sh >= 0.7:
        return "maker_1side"
    if r.hi_sh >= 0.5 or r.late_sh >= 0.5:
        return "late_snipe"       # buys >=0.9 / final 30s
    if r.two >= 0.3 and r.maker_sh < 0.3:
        return "taker_both"
    if r.maker_sh < 0.3:
        return "taker_dir"
    return "mixed"


s["arch"] = s.apply(arche, axis=1)
s.to_csv(pre + "_wallets.csv")
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
cols = ["id", "name", "nwin", "pnl", "mean", "t_active", "winr", "vol", "vol_sh", "roi", "maker_sh", "two", "epc",
        "sell_sh", "tavg", "late_sh", "pre_sh", "hi_sh", "qavg", "arch"]
fmt = lambda df: df[cols].round(3).assign(name=lambda d: d.name.str[:14]).to_string()
print("windows", NW, "wallets", len(s), "total notional", round(tot))
print("\n== top 25 by PnL ==\n" + fmt(s.sort_values("pnl", ascending=False).head(25)))
print("\n== bottom 10 by PnL ==\n" + fmt(s.sort_values("pnl").head(10)))
q = s[s.nwin >= minw]
print(f"\n== top 25 by t (nwin>={minw}, n={len(q)}) ==\n" + fmt(q.sort_values("t_active", ascending=False).head(25)))
print(f"\n== worst 10 by t (nwin>={minw}) ==\n" + fmt(q.sort_values("t_active").head(10)))
# archetype table (all wallets, and consistent winners)
def atab(df):
    a = df.groupby("arch").agg(nw=("pnl", "size"), pnl=("pnl", "sum"), vol=("vol", "sum"), winw=("nwin", "sum"))
    a["pnl_per_wwin"] = a.pnl / a.winw
    a["roi"] = a.pnl / a.vol
    a["vol_sh"] = a.vol / tot
    return a.round(4)
print("\n== archetypes, all wallets ==\n", atab(s))
print("\n== archetypes, nwin>=%d ==\n" % minw, atab(q))
cw = q[(q.t_active > 2) & (q.pnl > 0)]
print("\n== archetypes, consistent winners (t>2) ==\n", atab(cw))
