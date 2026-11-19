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
  regimes       the same aggregation split by the PRIOR-1H BTC move known
                at the window's open: open(this window) - open(1h earlier)
                >= +$100 -> up, <= -$100 -> down, else range; windows
                without a 1h-earlier open in the data are "unknown".
                AMENDED 2026-11-19: the original definition classified a
                window by its OWN close-open, which for directional
                strategies is circular (an "up window" is by construction
                a window where Up won). Regime splits printed by earlier
                versions are superseded.
  bonferroni    per-family CI at the Bonferroni-corrected level
                1 - 0.05/n_families, for multiple-comparison honesty.

Usage: farm_report.py <settlements.jsonl> [trades.jsonl]
"""
import json
import random
import sys
from collections import defaultdict

REGIME_USD = 100.0
BOOT = 2000


def block_bootstrap_ci(series, block, iters=BOOT, level=0.95):
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
    a = (1.0 - level) / 2.0
    return means[int(a * iters)], means[min(iters - 1, int((1 - a) * iters))]


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
    slug_open = {}                    # slug -> Chainlink open print
    for s in sett:
        fam = s.get("family") or s["account"].split("-")[0].upper()
        win_pnl[fam][s["slug"]] = win_pnl[fam].get(s["slug"], 0.0) + float(s["pnl"])
        if s.get("open") is not None:
            slug_open[s["slug"]] = float(s["open"])

    def regime(slug):
        """Ex-ante regime: prior-1h move known at this window's open."""
        try:
            start = int(slug.rsplit("-", 1)[1])
        except (ValueError, IndexError):
            return "unknown"
        prev = "btc-updown-5m-%d" % (start - 3600)
        if slug not in slug_open or prev not in slug_open:
            return "unknown"
        mv = slug_open[slug] - slug_open[prev]
        return "up" if mv >= REGIME_USD else "down" if mv <= -REGIME_USD else "range"

    win_regime = {s: regime(s) for s in slug_open}
    n_fam = len(win_pnl)
    bf_level = 1.0 - 0.05 / max(n_fam, 1)

    print(f"{'family':<7} {'trades':>6} {'decis':>5} {'nwin':>5} {'sum':>8} {'mean/win':>8}  95% CI (block bootstrap)  Bonferroni {bf_level*100:.1f}% CI")
    for fam in sorted(win_pnl):
        slugs = sorted(win_pnl[fam])
        series = [win_pnl[fam][s] for s in slugs]
        n = len(series)
        block = max(6, min(48, n // 10)) if n >= 10 else max(1, n // 2)
        ci = block_bootstrap_ci(series, block)
        bf = block_bootstrap_ci(series, block, level=bf_level)
        ci_txt = f"[{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "n too small"
        bf_txt = f"[{bf[0]:+.2f}, {bf[1]:+.2f}]" if bf else ""
        print(f"{fam:<7} {entries.get(fam, 0):>6} {len(decisions.get(fam, ())):>5} {n:>5} "
              f"{sum(series):>+8.2f} {sum(series)/n:>+8.2f}  {ci_txt}  {bf_txt}")
        for reg in ("up", "down", "range", "unknown"):
            sub = [win_pnl[fam][s] for s in slugs if win_regime.get(s) == reg]
            if sub:
                print(f"{'':<7}   {reg:<7} windows={len(sub):>3}  sum={sum(sub):>+8.2f}  mean={sum(sub)/len(sub):+.2f}")


if __name__ == "__main__":
    main()
