#!/usr/bin/env python3
"""Family-level farm report under the revised (2026-11-19) read criteria.

Accounting rule: the unit of evidence is (family, window) -- never the
account and never the trade. Within one window every account of a family
rides the same single settlement, so k accounts entering the same side is
ONE independent decision, however many trades it produced.

For each family this reports:
  trades        raw leg-1 entries (the misleading count)
  decisions     distinct (window, side) with >= 1 entry (the honest count)
  windows       windows the family traded (the sample size)
  window PnL    family PnL summed per window -> mean, and a moving-block
                bootstrap 95% CI of that mean (blocks preserve the
                autocorrelation/regime clustering of consecutive windows)
  regimes       the same aggregation split by how the window resolved:
                up (close-open >= +$100), down (<= -$100), else range

Usage: farm_report.py <settlements.jsonl> [trades.jsonl]
"""
import json
import random
import sys
from collections import defaultdict

REGIME_USD = 100.0
BOOT = 2000


def block_bootstrap_ci(series, block, iters=BOOT):
    n = len(series)
    if n < 5:
        return None
    rng = random.Random(42)
    blocks = [series[i:i + block] for i in range(0, n - block + 1)] or [series]
    means = []
    for _ in range(iters):
        sample = []
        while len(sample) < n:
            sample.extend(rng.choice(blocks))
        means.append(sum(sample[:n]) / n)
    means.sort()
    return means[int(0.025 * iters)], means[int(0.975 * iters)]


def main():
    sett_path = sys.argv[1]
    trades_path = sys.argv[2] if len(sys.argv) > 2 else None
    sett = [json.loads(l) for l in open(sett_path)]

    decisions = defaultdict(set)      # family -> {(slug, side)}
    entries = defaultdict(int)        # family -> leg-1 count
    if trades_path:
        acct_fam = {}
        for t in (json.loads(l) for l in open(trades_path)):
            acct_fam[t["account"]] = t.get("family") or t["account"].split("-")[0].upper()
            if t.get("leg") == 1:
                fam = acct_fam[t["account"]]
                entries[fam] += 1
                decisions[fam].add((t["slug"], t["side"]))

    win_pnl = defaultdict(dict)       # family -> slug -> pnl sum
    win_regime = {}                   # slug -> regime
    for s in sett:
        fam = s.get("family") or s["account"].split("-")[0].upper()
        win_pnl[fam][s["slug"]] = win_pnl[fam].get(s["slug"], 0.0) + float(s["pnl"])
        if s.get("open") is not None and s.get("close") is not None:
            mv = float(s["close"]) - float(s["open"])
            win_regime[s["slug"]] = "up" if mv >= REGIME_USD else "down" if mv <= -REGIME_USD else "range"

    print(f"{'family':<7} {'trades':>6} {'decis':>5} {'nwin':>5} {'sum':>8} {'mean/win':>8}  95% CI (block bootstrap)")
    for fam in sorted(win_pnl):
        slugs = sorted(win_pnl[fam])
        series = [win_pnl[fam][s] for s in slugs]
        n = len(series)
        block = max(6, min(48, n // 10)) if n >= 10 else max(1, n // 2)
        ci = block_bootstrap_ci(series, block)
        ci_txt = f"[{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "n too small"
        print(f"{fam:<7} {entries.get(fam, 0):>6} {len(decisions.get(fam, ())):>5} {n:>5} "
              f"{sum(series):>+8.2f} {sum(series)/n:>+8.2f}  {ci_txt}")
        for reg in ("up", "down", "range"):
            sub = [win_pnl[fam][s] for s in slugs if win_regime.get(s) == reg]
            if sub:
                print(f"{'':<7}   {reg:<6} windows={len(sub):>3}  sum={sum(sub):>+8.2f}  mean={sum(sub)/len(sub):+.2f}")


if __name__ == "__main__":
    main()
