#!/usr/bin/env python3
"""Feature extraction v1 for the BTC 5m retrain (dry-run grade).

Reads one day of deep-recorder files (clob / rtds / binance) and emits one
CSV row per (window, decision offset) with features computed ONLY from data
at or before the decision time (no lookahead):

  binance prints : ts <= t          (feed-side ts)
  rtds twap_sixty: ts <= t          (series ts; note _recv lags 2-60 s in
                                     live use -- v1 plumbing only)
  clob snapshots : _recv <= t

Labels (official winners) are NOT derived here from prices. If --labels
points to a CSV with columns slug,winner (built from Gamma outcomePrices),
the winner is joined on slug; otherwise the winner column stays empty.

Usage:
  python3 extract_features.py --data-dir DIR --date 2026-11-25 \
      --start-unix 1795564800 --end-unix 1795651200 \
      [--labels labels.csv] --out features.csv

Window range is [start-unix, end-unix) on the slug suffix (window start).
Decision offsets are fixed at 60/120/180/240 s into the 300 s window.
Prints a JSON summary to stdout at the end.
"""
import argparse, csv, gzip, json, math, os, sys
from bisect import bisect_right

OFFSETS = [60, 120, 180, 240]

COLUMNS = [
    "slug", "window_start", "offset_s", "tau_s",
    "spot_open", "spot_now", "move", "sigma_1s", "n_prints_900",
    "twap_open", "twap_now", "twap_margin",
    "early_max_abs_move_120", "early_move_120",
    "up_bid", "up_ask", "up_mid", "spread",
    "up_bid_depth", "up_ask_depth", "book_imbalance", "lt_up",
    "down_bid", "down_ask",
    "winner", "label_up",
]


def open_maybe_gz(path):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "rt", encoding="utf-8")


def day_file(data_dir, stream, date):
    for cand in (f"{stream}-{date}.jsonl.gz", f"{stream}-{date}.jsonl"):
        p = os.path.join(data_dir, cand)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"{stream}-{date}.jsonl[.gz] not in {data_dir}")


def load_binance(path):
    ts, px = [], []
    with open_maybe_gz(path) as f:
        for line in f:
            r = json.loads(line)
            ts.append(float(r["ts"])); px.append(float(r["p"]))
    return ts, px


def load_twap(path):
    ts, val = [], []
    with open_maybe_gz(path) as f:
        for line in f:
            r = json.loads(line)
            if r.get("topic") == "crypto_prices_twap_sixty":
                ts.append(float(r["ts"]) / 1000.0); val.append(float(r["value"]))
    return ts, val


def load_clob(path):
    """slug -> {outcome: (recvs, bids, asks, bid_depth, ask_depth, lts)}"""
    raw = {}
    with open_maybe_gz(path) as f:
        for line in f:
            r = json.loads(line)
            slug = r["slug"]
            d = raw.setdefault(slug, {}).setdefault(r["outcome"], [])
            bd = sum(float(s) for _, s in (r.get("bids") or []))
            ad = sum(float(s) for _, s in (r.get("asks") or []))
            d.append((float(r["_recv"]), r.get("bid"), r.get("ask"), bd, ad,
                      r.get("lt")))
    out = {}
    for slug, by_out in raw.items():
        out[slug] = {}
        for outcome, rows in by_out.items():
            rows.sort(key=lambda x: x[0])
            out[slug][outcome] = (
                [x[0] for x in rows], [x[1] for x in rows],
                [x[2] for x in rows], [x[3] for x in rows],
                [x[4] for x in rows], [x[5] for x in rows])
    return out


def last_at(ts, vals, t):
    i = bisect_right(ts, t) - 1
    return vals[i] if i >= 0 else None


def book_at(book, t):
    if book is None:
        return (None,) * 6
    recvs, bids, asks, bds, ads, lts = book
    i = bisect_right(recvs, t) - 1
    if i < 0:
        return (None,) * 6
    return bids[i], asks[i], bds[i], ads[i], lts[i], recvs[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--start-unix", type=int, required=True)
    ap.add_argument("--end-unix", type=int, required=True)
    ap.add_argument("--labels", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    labels = {}
    if args.labels:
        with open(args.labels) as f:
            for row in csv.DictReader(f):
                labels[row["slug"]] = row["winner"]

    b_ts, b_px = load_binance(day_file(args.data_dir, "binance", args.date))
    t_ts, t_val = load_twap(day_file(args.data_dir, "rtds", args.date))
    clob = load_clob(day_file(args.data_dir, "clob", args.date))

    slugs = sorted(s for s in clob
                   if args.start_unix <= int(s.rsplit("-", 1)[1]) < args.end_unix)
    rows_out = []
    for slug in slugs:
        start = int(slug.rsplit("-", 1)[1])
        spot_open = last_at(b_ts, b_px, start)
        if spot_open is None:
            i = bisect_right(b_ts, start + 10) - 1
            spot_open = b_px[i] if i >= 0 else None
        twap_open = last_at(t_ts, t_val, start)
        # early-window path stats (prints in [start, start+120])
        lo = bisect_right(b_ts, start)
        hi = bisect_right(b_ts, start + 120)
        early_max = early_move = None
        if spot_open is not None and hi > lo:
            seg = b_px[lo:hi]
            early_max = max(abs(p - spot_open) for p in seg)
            early_move = seg[-1] - spot_open
        for off in OFFSETS:
            t = start + off
            spot_now = last_at(b_ts, b_px, t)
            move = (spot_now - spot_open) if (spot_now is not None
                                              and spot_open is not None) else None
            # trailing 900 s per-print log-return vol, scaled to per-second
            j1 = bisect_right(b_ts, t)
            j0 = bisect_right(b_ts, t - 900)
            sigma = None; npr = j1 - j0
            if npr >= 50:
                seg = b_px[j0:j1]
                rets = [math.log(seg[k + 1] / seg[k]) for k in range(len(seg) - 1)
                        if seg[k] > 0 and seg[k + 1] > 0]
                if len(rets) >= 30:
                    m = sum(rets) / len(rets)
                    var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
                    span = b_ts[j1 - 1] - b_ts[j0]
                    pps = npr / span if span > 0 else 0.0
                    sigma = math.sqrt(var) * math.sqrt(pps) if pps > 0 else None
            twap_now = last_at(t_ts, t_val, t)
            twap_margin = (twap_now - spot_open) if (twap_now is not None
                                                     and spot_open is not None) else None
            ub, ua, ubd, uad, ult, _ = book_at(clob[slug].get("Up"), t)
            db, da, _, _, _, _ = book_at(clob[slug].get("Down"), t)
            mid = ((ub + ua) / 2.0) if (ub is not None and ua is not None) else None
            spread = (ua - ub) if (ub is not None and ua is not None) else None
            imb = None
            if ubd is not None and uad is not None and (ubd + uad) > 0:
                imb = ubd / (ubd + uad)
            winner = labels.get(slug, "")
            rows_out.append({
                "slug": slug, "window_start": start, "offset_s": off,
                "tau_s": 300 - off,
                "spot_open": spot_open, "spot_now": spot_now, "move": move,
                "sigma_1s": sigma, "n_prints_900": npr,
                "twap_open": twap_open, "twap_now": twap_now,
                "twap_margin": twap_margin,
                "early_max_abs_move_120": early_max if off >= 120 else None,
                "early_move_120": early_move if off >= 120 else None,
                "up_bid": ub, "up_ask": ua, "up_mid": mid, "spread": spread,
                "up_bid_depth": ubd, "up_ask_depth": uad,
                "book_imbalance": imb, "lt_up": ult,
                "down_bid": db, "down_ask": da,
                "winner": winner,
                "label_up": (1 if winner == "Up" else 0) if winner else "",
            })

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows_out:
            w.writerow({k: ("" if r[k] is None else r[k]) for k in COLUMNS})

    nan_counts = {c: sum(1 for r in rows_out if r[c] is None or r[c] == "")
                  for c in COLUMNS}
    summary = {
        "windows": len(slugs), "rows": len(rows_out),
        "offsets": OFFSETS,
        "labeled": sum(1 for r in rows_out if r["winner"]),
        "nan_counts": nan_counts,
        "first_slug": slugs[0] if slugs else None,
        "last_slug": slugs[-1] if slugs else None,
    }
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
