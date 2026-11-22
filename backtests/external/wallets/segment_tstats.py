"""Window-clustered t-stats for candidate mechanisms (segments of fills).
Usage: python3 -I segment_tstats.py <out_prefix>"""
import sys, numpy as np, pandas as pd
f = pd.read_csv(sys.argv[1] + "_fills.csv.gz")
f["notional"] = f.q_long * f["size"]
f["edge50"] = (0.5 - f.q_long) * f["size"]          # pre-window fair value 0.5 edge
NW = f.start.nunique()
segs = {
 "ALL maker": (f.role == "M"),
 "ALL taker": (f.role == "T"),
 "pre M q<=0.47": (f.role == "M") & (f.t < 0) & (f.q_long <= 0.47),
 "pre M q<=0.48": (f.role == "M") & (f.t < 0) & (f.q_long <= 0.48),
 "pre M q<0.50": (f.role == "M") & (f.t < 0) & (f.q_long < 0.50),
 "pre M last120s q<=0.48": (f.role == "M") & (f.t < 0) & (f.t >= -120) & (f.q_long <= 0.48),
 "pre T q>=0.52": (f.role == "T") & (f.t < 0) & (f.q_long >= 0.52),
 "in M fav .5-.8 t0-120": (f.role == "M") & f.t.between(0, 119) & f.q_long.between(0.5, 0.8),
 "in M cheap .2-.5 t0-120": (f.role == "M") & f.t.between(0, 119) & f.q_long.between(0.2, 0.4999),
 "in M fav .5-.8 t120-240": (f.role == "M") & f.t.between(120, 239) & f.q_long.between(0.5, 0.8),
 "in M .8-.95 any": (f.role == "M") & f.t.between(0, 299) & f.q_long.between(0.8, 0.95),
 "late M q>=.95 t>=240": (f.role == "M") & (f.t >= 240) & (f.q_long >= 0.95),
 "late T q>=.95 t>=240": (f.role == "T") & (f.t >= 240) & (f.q_long >= 0.95),
 "T fav .6-.8 t0-240": (f.role == "T") & f.t.between(0, 239) & f.q_long.between(0.6, 0.8),
 "T cheap .2-.5": (f.role == "T") & f.t.between(0, 299) & f.q_long.between(0.2, 0.4999),
}
rows = []
for k, msk in segs.items():
    x = f[msk]
    pw = x.groupby("start").pnl_settle.sum().reindex(sorted(f.start.unique()), fill_value=0)
    ew = x.groupby("start").edge50.sum().reindex(pw.index, fill_value=0)
    rows.append([k, len(x), x.notional.sum() / NW, pw.mean(), pw.mean() / (pw.std() / np.sqrt(NW)),
                 x.pnl_settle.sum() / x.notional.sum(), ew.sum() / x.notional.sum(), x.mk10.sum() / x.notional.sum(),
                 x.mk30.sum() / x.notional.sum()])
r = pd.DataFrame(rows, columns=["segment", "fills", "notional/win", "pnl/win", "t_clustered", "roi", "edge_vs_0.5", "mk10/$", "mk30/$"])
pd.set_option("display.width", 200)
print("windows", NW); print(r.round(4).to_string(index=False))
