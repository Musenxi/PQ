"""Paper-sim of pre-window two-sided maker bids from the trade tape (conservative fill rule).
Rule: during [T0, T1) seconds relative to window start, rest BUY bids of Q shares on BOTH Up and Down at price b.
Fill only when a maker-side fill on that token (economic long) prints at a price STRICTLY below b (queue fully consumed).
Hold to settlement (or merge pairs at $1). Maker rebate ignored (upside). Window-clustered stats.
Usage: python3 -I prewindow_sim.py <out_prefix>"""
import sys, numpy as np, pandas as pd
f = pd.read_csv(sys.argv[1] + "_fills.csv.gz", usecols=["start", "role", "tok", "side", "size", "t", "q_long", "payout_long"])
f = f[f.role == "M"]
f["lt"] = np.where(f.side == "BUY", f.tok, 1 - f.tok)
starts = sorted(f.start.unique())
pay = f.groupby(["start", "lt"]).payout_long.first().unstack()
rows = []
for (T0, T1) in [(-300, 0), (-300, -60), (-300, -90), (-60, 0), (-180, -60), (-3600, -90), (-3600, -300), (-120, -60)]:
    seg = f[(f.t >= T0) & (f.t < T1)]
    for b in [0.45, 0.46, 0.47, 0.48]:
        for Q in [10, 25]:
            x = seg[seg.q_long < b]
            fill = x.groupby(["start", "lt"])["size"].sum().unstack(fill_value=0).reindex(starts, fill_value=0).clip(upper=Q)
            fill = fill.reindex(columns=[0, 1], fill_value=0)
            p0 = pay.reindex(starts)[0].fillna(pay.reindex(starts)[1].rsub(1)).values
            pnl = fill[0] * (p0 - b) + fill[1] * ((1 - p0) - b)
            cap = (fill[0] + fill[1]) * b
            rows.append([f"[{T0},{T1})", b, Q, (fill.sum(axis=1) > 0).mean(), ((fill[0] > 0) & (fill[1] > 0)).mean(),
                         pnl.mean(), pnl.mean() / (pnl.std() / np.sqrt(len(pnl))), pnl.sum() / cap.sum(),
                         ((fill[0] + fill[1]) * (0.5 - b)).sum() / cap.sum(), pnl.sum()])
r = pd.DataFrame(rows, columns=["window", "bid", "Q", "p_fill", "p_both", "pnl/win", "t", "roi", "edge@0.5", "total"])
pd.set_option("display.width", 200); print(r.round(4).to_string(index=False))
