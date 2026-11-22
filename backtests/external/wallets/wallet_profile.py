"""Profile selected wallets' fills (where/when/how they make money).
Usage: python3 -I wallet_profile.py <out_prefix> <id6,id6,...>"""
import sys, numpy as np, pandas as pd
pre, ids = sys.argv[1], sys.argv[2].split(",")
f = pd.read_csv(pre + "_fills.csv.gz")
f["id"] = f.wallet.str[2:8]
f = f[f.id.isin(ids)].copy()
f["notional"] = f.q_long * f["size"]
f["qb"] = pd.cut(f.q_long, [0, .2, .35, .5, .65, .8, .95, 1.01], right=False)
f["tb"] = pd.cut(f.t, [-1e9, 0, 60, 120, 180, 240, 280, 1e9], right=False, labels=["pre","0-60","60-120","120-180","180-240","240-280","280+"])
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 500)
for i in ids:
    x = f[f.id == i]
    if x.empty: continue
    print(f"\n######## {i}  fills={len(x)} windows={x.start.nunique()} med_fill_$={x.notional.median():.1f} maker={ (x.role=='M').mean():.2f} buyrows={(x.side=='BUY').mean():.2f}")
    for by in ["qb", "tb"]:
        g = x.groupby(by, observed=True)
        t = pd.DataFrame({"notional": g.notional.sum(), "pnl": g.pnl_settle.sum(), "mk10": g.mk10.sum(), "mk30": g.mk30.sum()})
        t["sh"] = t.notional / t.notional.sum(); t["roi"] = t.pnl / t.notional; t["mk10/$"] = t.mk10 / t.notional; t["mk30/$"] = t.mk30 / t.notional
        print(t[["sh", "notional", "pnl", "roi", "mk10/$", "mk30/$"]].round(3).to_string())
