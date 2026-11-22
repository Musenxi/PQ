"""Wallet forensics on cached up/down windows (output of fetch_windows.py).

Usage: python3 -I analyze.py <window_dir> <out_prefix>
Writes <out_prefix>_fills.parquet-like CSV (fills.csv.gz), <out_prefix>_wallet_window.csv, <out_prefix>_wallets.csv
and prints summary tables.

Accounting (per wallet, per window):
  cash = sum(SELL size*price) - sum(BUY size*price) - taker_fee + maker_rebate
  pnl  = cash + sum_i net_shares_i * payout_i       (linear => splits/merges net out exactly)
  taker_fee   = rate * p*(1-p) * size  on taker rows (rate from feeSchedule, default 0.05)
  maker_rebate = rebateRate * rate * p*(1-p) * size on maker rows (estimate; paid off-feed daily)
Maker/taker role: rows present in taker_only=true feed are taker rows (multiset match), rest maker.
"""
import json, os, sys, glob, collections, math, gzip, csv, bisect

def main():
    wdir, outp = sys.argv[1], sys.argv[2]
    files = sorted(glob.glob(os.path.join(wdir, "*.json")))
    fills_out = gzip.open(outp + "_fills.csv.gz", "wt", newline="")
    fw = csv.writer(fills_out)
    fw.writerow(["start", "wallet", "role", "tok", "side", "size", "price", "t", "q_long", "payout_long",
                 "pnl_settle", "fee", "rebate", "mk10", "mk30", "mk60", "is_win_tok"])
    ww_rows = []
    names = {}
    nwin = 0
    for fn in files:
        d = json.load(open(fn))
        m = d["meta"]
        try:
            op = [float(x) for x in json.loads(m["outcomePrices"])]
            toks = json.loads(m["clobTokenIds"])
        except Exception:
            continue
        if sorted(op) != [0.0, 1.0]:
            continue
        nwin += 1
        start, step = m["start"], m["step"]
        fs = m.get("feeSchedule") or {}
        rate = float(fs.get("rate", 0.05) or 0.0)
        rr = float(fs.get("rebateRate", 0.2) or 0.0)
        tokidx = {toks[0]: 0, toks[1]: 1}
        key = lambda x: (x["transaction_hash"], x["proxy_wallet"], x["token_id"], x["side"], x["size"], x["price"])
        tk = collections.Counter(key(x) for x in d["taker"])
        rows = []
        for x in d["all"]:
            if x["token_id"] not in tokidx:
                continue
            k = key(x)
            role = "M"
            if tk.get(k, 0) > 0:
                tk[k] -= 1; role = "T"
            rows.append((x, role))
            if x.get("pseudonym") or x.get("name"):
                names[x["proxy_wallet"]] = x.get("name") or x.get("pseudonym")
        # price path for token0 (Up) from all fills (taker rows only to avoid duplicates)
        path = []
        for x, role in rows:
            if role != "T":
                continue
            p0 = x["price"] if tokidx[x["token_id"]] == 0 else 1 - x["price"]
            path.append((x["timestamp"], p0))
        path.sort()
        pts = [a for a, _ in path]
        end = start + step
        def up_price(t):
            if t >= end:
                return op[0]
            i = bisect.bisect_right(pts, t) - 1
            return path[i][1] if i >= 0 else None
        agg = collections.defaultdict(lambda: collections.defaultdict(float))
        for x, role in rows:
            w = x["proxy_wallet"]; ti = tokidx[x["token_id"]]
            s, p, t = float(x["size"]), float(x["price"]), x["timestamp"] - start
            pay = op[ti]
            sign = 1 if x["side"] == "BUY" else -1
            fee = rate * p * (1 - p) * s if role == "T" else 0.0
            reb = rr * rate * p * (1 - p) * s if role == "M" else 0.0
            pnl = sign * (pay - p) * s - fee + reb
            # economic long: BUY tok@p == long tok @p ; SELL tok@p == long other @1-p
            q = p if sign > 0 else 1 - p
            lt = ti if sign > 0 else 1 - ti
            payl = op[lt]
            mks = []
            for h in (10, 30, 60):
                u = up_price(x["timestamp"] + h)
                if u is None:
                    mks.append("")
                    continue
                pl = u if lt == 0 else 1 - u
                mks.append(round((pl - q) * s, 5))
            fw.writerow([start, w, role, ti, x["side"], s, p, t, round(q, 5), payl, round(pnl, 5),
                         round(fee, 5), round(reb, 5)] + mks + [int(pay == 1)])
            a = agg[w]
            a["cash"] += -sign * p * s - fee + reb
            a["sh%d" % ti] += sign * s
            a["vol"] += p * s
            a["mvol"] += p * s if role == "M" else 0
            a["fee"] += fee; a["reb"] += reb
            a["n"] += 1
            a["tw"] += t * p * s
            a["late"] += p * s if t >= step - 30 else 0
            a["pre"] += p * s if t < 0 else 0
            a["sellvol"] += p * s if sign < 0 else 0
            a["buy%d" % ti] += s if sign > 0 else 0
            a["buyc%d" % ti] += p * s if sign > 0 else 0
            a["qv"] += q * p * s
            a["hi"] += p * s if q >= 0.9 else 0
            a["L%d" % lt] += s
            a["Lc%d" % lt] += q * s
        for w, a in agg.items():
            pnl = a["cash"] + a["sh0"] * op[0] + a["sh1"] * op[1]
            both = int(a["buy0"] > 0 and a["buy1"] > 0)
            pair_cost = ""
            if both:
                pair_cost = round(a["buyc0"] / a["buy0"] + a["buyc1"] / a["buy1"], 4)
            L0, L1 = a["L0"], a["L1"]
            two = round(min(L0, L1) / max(L0, L1), 3) if max(L0, L1) > 0 else 0
            epc = round(a["Lc0"] / L0 + a["Lc1"] / L1, 4) if L0 > 0 and L1 > 0 else ""
            ww_rows.append([start, w, round(pnl, 4), round(a["vol"], 4), round(a["mvol"], 4), round(a["fee"], 4),
                            round(a["reb"], 4), int(a["n"]), round(a["tw"] / a["vol"], 1) if a["vol"] else "",
                            round(a["late"], 4), round(a["pre"], 4), round(a["sellvol"], 4), both, pair_cost,
                            round(a["sh0"], 3), round(a["sh1"], 3), round(a["qv"] / a["vol"], 4) if a["vol"] else "",
                            round(a["hi"], 4), int(op[0] == 1), two, epc])
    fills_out.close()
    with open(outp + "_wallet_window.csv", "w", newline="") as f:
        c = csv.writer(f)
        c.writerow(["start", "wallet", "pnl", "vol", "mvol", "fee", "reb", "n", "tavg", "late", "pre", "sellvol",
                    "both", "pair_cost", "sh0", "sh1", "qavg", "hivol", "up_won", "two", "epc"])
        c.writerows(ww_rows)
    json.dump(names, open(outp + "_names.json", "w"))
    print("windows", nwin, "wallet-windows", len(ww_rows))

if __name__ == "__main__":
    main()
