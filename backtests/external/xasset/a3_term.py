"""Idea 3: term-structure consistency. Long market L (15m/1h) and short market S (5m/15m)
that end at the same time and settle on the same Chainlink TWAP F, with different strikes.
python -I a3_term.py"""
import os, sys, numpy as np, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from load import meta, Mkt, boot_ci, TD
M = meta()
GAP = int(sys.argv[1]) if len(sys.argv) > 1 else 5
def fee_rate(a, d, t):
    if d == "1h": return 0.01
    if a == "btc": return 0.05 if t >= 1795219140 else 0.07
    return 0.01
PAIRS = (("15m", "5m", 600, 300), ("1h", "15m", 2700, 900), ("1h", "5m", 3300, 300))
ex = lambda sl: os.path.exists(os.path.join(TD, sl + ".json.gz"))
for Ld, Sd, off, sdur in PAIRS:
    print(f"\n===== {Ld} vs last {Sd}")
    for a in ("btc", "eth", "sol", "xrp"):
        Ls = sorted(k for k, v in M.items() if v["asset"] == a and v["dur"] == Ld and ex(k) and v["k"])
        nwin = nviol = narb = 0; vsz = []; arbp = []; combo = []; ffmis = 0
        imp, real = [], []; arbinfo = []
        for sl in Ls:
            u = M[sl]["start"]; ss = f"{a}-updown-{Sd}-{u + off}"
            if ss not in M or not ex(ss) or not M[ss]["k"]: continue
            L, S = Mkt(sl), Mkt(ss)
            if not (L.ok and S.ok): continue
            KL, KS = M[sl]["k"], M[ss]["k"]
            if M[sl]["f"] and M[ss]["f"] and abs(M[sl]["f"] / M[ss]["f"] - 1) > 1e-9: ffmis += 1
            nwin += 1
            # orientation: 'wide' leg = Up on lower strike market; 'narrow' = Up on higher strike
            lowL = KL < KS
            # combo: buy Up(low-strike mkt) + Down(high-strike mkt) -> pays 1 + 1{Klow<=F<Khigh}
            lowM, highM = (L, S) if lowL else (S, L)
            ts0 = u + off
            # (i) monotonicity violations from last-trade prices, sampled every 15s
            viol = 0; mx = 0
            for t in range(ts0 + 15, ts0 + sdur - 10, 15):
                pl, ph = lowM.last_up(t, 10), highM.last_up(t, 10)
                if np.isnan(pl) or np.isnan(ph): continue
                if ph - pl > 0.0: viol = 1; mx = max(mx, ph - pl)
            nviol += viol; vsz += [mx] if viol else []
            # (ii) executable arb from actual taker BUY fills within 5s: Up(low) at a1, Down(high) at b1
            iu = np.where((lowM.oi == 0) & (lowM.side == 1) & (lowM.ts >= ts0))[0]
            idn = np.where((highM.oi == 1) & (highM.side == 1) & (highM.ts >= ts0))[0]
            best = 9; binfo = None
            if len(iu) and len(idn):
                tb = highM.ts[idn]
                for i in iu:
                    j0, j1 = bisect.bisect_left(tb, lowM.ts[i] - GAP), bisect.bisect_right(tb, lowM.ts[i] + GAP)
                    if j1 > j0:
                        a1 = lowM.px[i]; b1 = highM.px[idn[j0:j1]].min()
                        dl = Ld if lowM is L else Sd; dh = Sd if lowM is L else Ld
                        c = a1 + b1 + fee_rate(a, dl, u) * a1 * (1 - a1) + fee_rate(a, dh, u) * b1 * (1 - b1)
                        if c < best: best = c; binfo = (int(ts0 + sdur - lowM.ts[i]), round(a1, 3), round(float(b1), 3), round(abs(KL / KS - 1) * 1e4, 1))
            if best < 1: narb += 1; arbp.append(1 - best); arbinfo.append(binfo)
            # (iii) fair value of the 'between' probability at t = ts0+60 (one per window)
            t = ts0 + 60
            pl, ph = lowM.last_up(t, 20), highM.last_up(t, 20)
            if not (np.isnan(pl) or np.isnan(ph)):
                between = int(lowM.yes == 1 and highM.yes == 0)
                imp.append(pl - ph); real.append(between)
        if nwin == 0: print(a, "no data"); continue
        imp, real = np.array(imp), np.array(real)
        line = f" {a}: windows={nwin} F-mismatch={ffmis} viol(any 15s sample, last-trade)={nviol} ({nviol/nwin:.1%}) med max-viol={np.median(vsz) if vsz else 0:.3f}"
        line += f" | exec arb fills<=GAPs apart, cost+fees<1: {narb} windows, med edge={np.median(arbp) if arbp else 0:.3f}"
        print(line)
        if arbinfo:
            ai = np.array(arbinfo, float)
            print(f"    arb detail: median sec-to-end={np.median(ai[:,0]):.0f}, med legs=({np.median(ai[:,1]):.3f},{np.median(ai[:,2]):.3f}), med strike gap={np.median(ai[:,3]):.1f}bp, share with a leg<=0.05: {np.mean(np.minimum(ai[:,1],ai[:,2])<=0.05):.2f}")
        if len(imp) > 50:
            for lo, hi in ((-1, 0.0), (0.0, 0.05), (0.05, 0.15), (0.15, 1.1)):
                k = (imp > lo) & (imp <= hi)
                if k.sum() >= 10: print(f"    implied P(between) in ({lo},{hi}]: n={k.sum()} mean impl={imp[k].mean():.3f} realised={real[k].mean():.3f}")
