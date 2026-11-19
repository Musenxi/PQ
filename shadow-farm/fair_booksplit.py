#!/usr/bin/env python3
"""FAIR fresh-vs-stale book attribution (pre-registered 2026-11-19).

Splits FAIR's family x window PnL by whether the leg-1 fills in that
window were taken on books the v2.1 filter would have rejected
(would_reject, logged by farm v2.0.1 record-only build):

  fresh    every FAIR leg-1 fill in the window has would_reject == False
  stale    every FAIR leg-1 fill has would_reject == True
  mixed    both kinds present (reported, excluded from the decision CI)
  unmarked no would_reject field (pre-v2.0.1 rows; excluded)

Decision rule (pre-registered in docs/audit-2026-11-19.md, verbatim
substance): judge ONLY the fresh group, per-window mean, block
bootstrap 95% CI --
  CI entirely above 0  -> FAIR passes gate 1; deploy v2.1, restart the
                          one-week read clock at deployment.
  CI includes 0        -> FAIR downgraded to "no evidence"; deploy
                          v2.1 and keep observing.
  CI entirely below 0  -> FAIR loses significantly on fresh books;
                          also downgraded to "no evidence"; deploy
                          v2.1 and keep observing.
  fresh windows < 5    -> rule cannot fire; report only.

Auxiliary outputs (REPORT ONLY, never enter the decision):
  * per-account attribution: each account's settlement is grouped by
    its OWN leg-1 fill's would_reject, then summed per window -- closer
    to the sample v2.1 would actually trade, and immune to the
    mixed-window exclusion shrinking the fresh sample.
  * threshold sensitivity: the same window split recomputed from the
    logged book ages at 500ms and 2000ms instead of 1000ms.
  * fresh vs stale per-window means and their difference (block
    bootstrap CI) -- the direct test of the "profits come from stale
    books" hypothesis.

Usage: fair_booksplit.py <settlements.jsonl> <trades.jsonl> [--since EPOCH]
"""
import json
import random
import sys
from collections import defaultdict
from datetime import datetime

BOOT = 2000
FUTURE_MS = -2000          # ages below this count as stale at any threshold


def block_bootstrap_ci(series, iters=BOOT, seed=42):
    n = len(series)
    if n < 5:
        return None
    block = max(6, min(48, n // 10)) if n >= 10 else max(1, n // 2)
    rng = random.Random(seed)
    blocks = [series[i:i + block] for i in range(0, n - block + 1)] or [series]
    means = []
    for _ in range(iters):
        sample = []
        while len(sample) < n:
            sample.extend(rng.choice(blocks))
        means.append(sum(sample[:n]) / n)
    means.sort()
    return means[int(0.025 * iters)], means[min(iters - 1, int(0.975 * iters))]


def _resample_mean(series, rng):
    n = len(series)
    block = max(6, min(48, n // 10)) if n >= 10 else max(1, n // 2)
    blocks = [series[i:i + block] for i in range(0, n - block + 1)] or [series]
    out = []
    while len(out) < n:
        out.extend(rng.choice(blocks))
    return sum(out[:n]) / n


def diff_ci(a, b, iters=BOOT):
    """Block-bootstrap CI for mean(a) - mean(b), independent resampling."""
    if len(a) < 5 or len(b) < 5:
        return None
    rng = random.Random(7)
    diffs = sorted(_resample_mean(a, rng) - _resample_mean(b, rng)
                   for _ in range(iters))
    return diffs[int(0.025 * iters)], diffs[min(iters - 1, int(0.975 * iters))]


def stale_at(ages, thr_ms):
    return any(a is None or a > thr_ms or a < FUTURE_MS for a in ages)


def group_of(flags):
    return "fresh" if flags == {False} else "stale" if flags == {True} else "mixed"


def print_group(tag, series_map):
    for g in ("fresh", "stale", "mixed"):
        ss = series_map.get(g, [])
        if ss:
            ci = block_bootstrap_ci(ss)
            ci_txt = f"[{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "n too small"
            print(f"  [{tag}] {g:<6} windows={len(ss):>3}  sum={sum(ss):>+9.2f}  "
                  f"mean/win={sum(ss)/len(ss):+.2f}  95% CI {ci_txt}")
        else:
            print(f"  [{tag}] {g:<6} windows=  0")


def main():
    sett_path, trades_path = sys.argv[1], sys.argv[2]
    since = 0.0
    if "--since" in sys.argv:
        since = float(sys.argv[sys.argv.index("--since") + 1])

    fills = []                # FAIR leg-1 fills in scope
    for t in (json.loads(l) for l in open(trades_path)):
        if t.get("family") != "FAIR" and not t["account"].startswith("fair"):
            continue
        if t.get("leg") != 1:
            continue
        if datetime.fromisoformat(t["ts"]).timestamp() < since:
            continue
        fills.append(t)
    marked = [t for t in fills if "would_reject" in t]
    print(f"FAIR leg-1 fills in scope: {len(fills)} (with would_reject: {len(marked)})")

    win_pnl = defaultdict(float)          # slug -> FAIR family PnL
    acct_pnl = {}                         # (account, slug) -> PnL
    for s in (json.loads(l) for l in open(sett_path)):
        fam = s.get("family") or s["account"].split("-")[0].upper()
        if fam == "FAIR":
            win_pnl[s["slug"]] += float(s["pnl"])
            acct_pnl[(s["account"], s["slug"])] = float(s["pnl"])

    # ---- primary split (decision basis): window level, logged flag ----
    flags = defaultdict(set)
    for t in marked:
        flags[t["slug"]].add(bool(t["would_reject"]))
    group = {slug: group_of(fs) for slug, fs in flags.items()}
    series = {g: [win_pnl[s] for s in sorted(win_pnl) if group.get(s) == g]
              for g in ("fresh", "stale", "mixed")}
    print("primary split (window level, 1000ms threshold, logged would_reject):")
    print_group("win", series)
    unmarked = [s for s in win_pnl if s not in group]
    if unmarked:
        print(f"  unmarked windows={len(unmarked)} (no marked fills; excluded)")

    # ---- decision (pre-registered; fresh group only) ----
    ci = block_bootstrap_ci(series["fresh"]) if series["fresh"] else None
    print("--- pre-registered decision ---")
    if ci is None:
        print("INSUFFICIENT DATA: fresh group has < 5 windows; rule cannot fire.")
    elif ci[0] > 0:
        print(f"Fresh-group CI [{ci[0]:+.2f}, {ci[1]:+.2f}] is entirely above 0 "
              "-> FAIR passes gate 1; deploy v2.1 and restart the one-week "
              "clock at deployment.")
    elif ci[1] < 0:
        print(f"Fresh-group CI [{ci[0]:+.2f}, {ci[1]:+.2f}] is entirely BELOW 0 "
              "-> FAIR loses significantly on fresh books: downgraded to "
              "NO EVIDENCE; deploy v2.1 and keep observing.")
    else:
        print(f"Fresh-group CI [{ci[0]:+.2f}, {ci[1]:+.2f}] includes 0 "
              "-> FAIR downgraded to NO EVIDENCE; deploy v2.1 and keep "
              "observing.")

    # ---- auxiliary 1: per-account attribution (report only) ----
    aflags = defaultdict(set)
    for t in marked:
        aflags[(t["account"], t["slug"])].add(bool(t["would_reject"]))
    agroup = {k: group_of(fs) for k, fs in aflags.items()}
    aseries = {}
    for g in ("fresh", "stale", "mixed"):
        per_win = defaultdict(float)
        for (acct, slug), pnl in acct_pnl.items():
            if agroup.get((acct, slug)) == g:
                per_win[slug] += pnl
        aseries[g] = [per_win[s] for s in sorted(per_win)]
    print("auxiliary (report only): per-account attribution, summed per window:")
    print_group("acct", aseries)

    # ---- auxiliary 2: threshold sensitivity (report only) ----
    aged = [t for t in fills if "book_age_ms" in t]
    for thr in (500, 2000):
        tflags = defaultdict(set)
        for t in aged:
            tflags[t["slug"]].add(stale_at(
                (t.get("book_age_ms"), t.get("dec_book_age_ms")), thr))
        tgroup = {slug: group_of(fs) for slug, fs in tflags.items()}
        tseries = {g: [win_pnl[s] for s in sorted(win_pnl) if tgroup.get(s) == g]
                   for g in ("fresh", "stale", "mixed")}
        print(f"auxiliary (report only): window split at {thr}ms threshold:")
        print_group(f"{thr}ms", tseries)

    # ---- auxiliary 3: fresh vs stale difference (report only) ----
    if series["fresh"] and series["stale"]:
        mf = sum(series["fresh"]) / len(series["fresh"])
        ms = sum(series["stale"]) / len(series["stale"])
        dci = diff_ci(series["fresh"], series["stale"])
        dci_txt = f"[{dci[0]:+.2f}, {dci[1]:+.2f}]" if dci else "n too small"
        print(f"auxiliary (report only): fresh mean/win {mf:+.2f} vs stale "
              f"{ms:+.2f}; difference {mf - ms:+.2f} per window, 95% CI {dci_txt}")


if __name__ == "__main__":
    main()
