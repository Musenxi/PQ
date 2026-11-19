#!/usr/bin/env python3
"""FAIR fresh-vs-stale book attribution (pre-registered 2026-11-19).

Splits FAIR's family x window PnL by whether the leg-1 fills in that
window were taken on books the v2.1 filter would have rejected
(would_reject, logged by farm v2.0.1 record-only build):

  fresh    every FAIR leg-1 fill in the window has would_reject == False
  stale    every FAIR leg-1 fill has would_reject == True
  mixed    both kinds present (reported, excluded from the decision CI)
  unmarked no would_reject field (pre-v2.0.1 rows; excluded)

Decision rule (pre-registered in docs/audit-2026-11-19.md): if the fresh
group's per-window mean block-bootstrap 95% CI includes 0, FAIR is
downgraded to "no evidence" and v2.1 is deployed for continued
observation; otherwise FAIR passes gate 1, v2.1 is deployed and the
one-week read clock restarts at deployment.

Usage: fair_booksplit.py <settlements.jsonl> <trades.jsonl> [--since EPOCH]
"""
import json
import random
import sys
from collections import defaultdict

BOOT = 2000


def block_bootstrap_ci(series, iters=BOOT):
    n = len(series)
    if n < 5:
        return None
    block = max(6, min(48, n // 10)) if n >= 10 else max(1, n // 2)
    rng = random.Random(42)
    blocks = [series[i:i + block] for i in range(0, n - block + 1)] or [series]
    means = []
    for _ in range(iters):
        sample = []
        while len(sample) < n:
            sample.extend(rng.choice(blocks))
        means.append(sum(sample[:n]) / n)
    means.sort()
    return means[int(0.025 * iters)], means[min(iters - 1, int(0.975 * iters))]


def main():
    sett_path, trades_path = sys.argv[1], sys.argv[2]
    since = 0.0
    if "--since" in sys.argv:
        since = float(sys.argv[sys.argv.index("--since") + 1])

    # window -> set of would_reject flags over FAIR leg-1 fills
    flags = defaultdict(set)
    n_fills = n_marked = 0
    for t in (json.loads(l) for l in open(trades_path)):
        if t.get("family") != "FAIR" and not t["account"].startswith("fair"):
            continue
        if t.get("leg") != 1:
            continue
        from datetime import datetime
        if datetime.fromisoformat(t["ts"]).timestamp() < since:
            continue
        n_fills += 1
        if "would_reject" in t:
            n_marked += 1
            flags[t["slug"]].add(bool(t["would_reject"]))

    group = {}
    for slug, fs in flags.items():
        group[slug] = "fresh" if fs == {False} else "stale" if fs == {True} else "mixed"

    win_pnl = defaultdict(float)
    for s in (json.loads(l) for l in open(sett_path)):
        fam = s.get("family") or s["account"].split("-")[0].upper()
        if fam == "FAIR":
            win_pnl[s["slug"]] += float(s["pnl"])

    print(f"FAIR leg-1 fills in scope: {n_fills} (with would_reject: {n_marked})")
    series = {}
    for g in ("fresh", "stale", "mixed"):
        series[g] = [win_pnl[s] for s in sorted(win_pnl) if group.get(s) == g]
        ss = series[g]
        if ss:
            ci = block_bootstrap_ci(ss)
            ci_txt = f"[{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "n too small"
            print(f"{g:<6} windows={len(ss):>3}  sum={sum(ss):>+9.2f}  "
                  f"mean/win={sum(ss)/len(ss):+.2f}  95% CI {ci_txt}")
        else:
            print(f"{g:<6} windows=  0")
    unmarked = [s for s in win_pnl if s not in group]
    if unmarked:
        print(f"unmarked windows={len(unmarked)} (no marked fills; excluded)")

    ci = block_bootstrap_ci(series["fresh"]) if series["fresh"] else None
    print("--- pre-registered decision ---")
    if ci is None:
        print("INSUFFICIENT DATA: fresh group has < 5 windows; rule cannot fire.")
    elif ci[0] <= 0 <= ci[1]:
        print(f"Fresh-group CI {ci} includes 0 -> FAIR downgraded to NO EVIDENCE; "
              "deploy v2.1 and keep observing.")
    else:
        print(f"Fresh-group CI {ci} excludes 0 -> FAIR passes gate 1; "
              "deploy v2.1 and restart the one-week clock at deployment.")


if __name__ == "__main__":
    main()
