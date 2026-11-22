"""Maker vs taker economics from analyze.py fills file.
Usage: python3 -I maker_econ.py <out_prefix>
Every fill row is expressed as an economic LONG of one token at price q (BUY tok@p -> q=p; SELL tok@p -> long other @1-p).
pnl_settle includes taker fee / estimated maker rebate. Markouts mkH = (price_long(t+H) - q)*size using last taker print.
"""
import sys, numpy as np, pandas as pd

pre = sys.argv[1]
f = pd.read_csv(pre + "_fills.csv.gz")
f["notional"] = f.q_long * f["size"]
f["gross"] = (f.payout_long - f.q_long) * f["size"]
f["qb"] = pd.cut(f.q_long, [0, .05, .1, .2, .3, .4, .5, .6, .7, .8, .9, .95, .99, 1.0001], right=False)
f["tb"] = pd.cut(f.t, [-1e9, 0, 60, 120, 180, 240, 270, 290, 300, 1e9], right=False,
                 labels=["pre", "0-60", "60-120", "120-180", "180-240", "240-270", "270-290", "290-300", "post"])
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)


def tab(by):
    g = f.groupby(["role"] + by, observed=True)
    t = pd.DataFrame({"n": g.size(), "notional": g.notional.sum(), "gross": g.gross.sum(), "pnl": g.pnl_settle.sum(),
                      "fee": g.fee.sum(), "reb": g.rebate.sum(), "mk10": g.mk10.sum(), "mk30": g.mk30.sum(),
                      "mk60": g.mk60.sum()})
    t["roi_gross"] = t.gross / t.notional
    t["roi_net"] = t.pnl / t.notional
    t["mk10/$"] = t.mk10 / t.notional
    t["mk30/$"] = t.mk30 / t.notional
    return t.round(4)


print("== totals by role ==\n", tab([]))
print("\n== by role x price bucket (q_long = price paid for the token you end up long) ==\n", tab(["qb"]))
print("\n== by role x time-in-window ==\n", tab(["tb"]))
# maker fills, cheap side vs favourite, by time
m = f[f.role == "M"].copy()
m["side_cls"] = np.where(m.q_long < 0.5, "long_cheap", "long_fav")
g = m.groupby(["side_cls", "tb"], observed=True)
t = pd.DataFrame({"notional": g.notional.sum(), "pnl": g.pnl_settle.sum(), "mk10": g.mk10.sum(), "mk30": g.mk30.sum()})
t["roi"] = t.pnl / t.notional; t["mk10/$"] = t.mk10 / t.notional; t["mk30/$"] = t.mk30 / t.notional
print("\n== maker fills: long cheap vs long fav x time ==\n", t.round(4))
