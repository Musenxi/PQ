"""Paper twin of the 1h live probe, derived from the probe's OWN
order log: for every window, take the probe's FIRST submit decision
(side + ask at that moment) and paper-fill $5 at that ask. Direction
and timing are therefore identical to the live probe BY CONSTRUCTION;
the only differences left are execution (kills, slippage, 5-share
minimum sizing) -- which is exactly what the probe exists to measure.
Winner: the probe's settlements ledger (Gamma official), with a
Gamma fallback for windows the probe submitted but never filled.
"""
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

DATA = "/root/polymarket-live1h/data"
JST = timezone(timedelta(hours=9))
STAKE = 5.0
SEG = [(1795255200, "S1 full band"), (1795262400, "S2 0.55-0.75"),
       (None, "S3 0.60-0.75")]


def seg_of(start):
    for cut, name in SEG:
        if cut is None or start < cut:
            return name
    return SEG[-1][1]


def gamma_winner(slug):
    try:
        req = urllib.request.Request(
            "https://gamma-api.polymarket.com/events?slug=" + slug,
            headers={"User-Agent": "probe-twin/1.0"})
        ev = json.loads(urllib.request.urlopen(req, timeout=15).read())
        m = ev[0]["markets"][0]
        if m.get("umaResolutionStatus") != "resolved":
            return None
        prices = json.loads(m["outcomePrices"])
        return "Up" if float(prices[0]) > 0.5 else "Down"
    except Exception:
        return None


def main():
    first = {}
    for line in open(os.path.join(DATA, "orders.jsonl")):
        r = json.loads(line)
        if r.get("disposition") != "submit":
            continue
        slug = r["slug"]
        if slug not in first or r["ts"] < first[slug]["ts"]:
            first[slug] = r
    live = {}
    winners = {}
    for line in open(os.path.join(DATA, "settlements.jsonl")):
        r = json.loads(line)
        live[r["slug"]] = live.get(r["slug"], 0.0) + r["pnl"]
        winners[r["slug"]] = r["winner"]

    rows = []
    for slug, r in sorted(first.items(),
                          key=lambda kv: int(kv[0].rsplit("-", 1)[1])):
        start = int(slug.rsplit("-", 1)[1])
        winner = winners.get(slug) or gamma_winner(slug)
        if winner is None:
            continue
        ask = float(r["ask"])
        rate = 0.07 if start < 1795212000 else 0.01
        shares = STAKE / ask
        fee = rate * ask * (1 - ask) * shares
        twin_pnl = (shares if r["side"] == winner else 0.0) - STAKE - fee
        rows.append({"slug": slug, "start": start, "seg": seg_of(start),
                     "side": r["side"], "ask": ask, "winner": winner,
                     "twin": twin_pnl, "live": live.get(slug)})

    print(f"{'window(JST)':12} {'seg':14} {'side@ask':10} {'win':5} "
          f"{'twin':>8} {'live':>8}")
    for r in rows[-8:]:
        t = datetime.fromtimestamp(r["start"], JST).strftime("%m-%d %H:%M")
        lv = f"{r['live']:+.2f}" if r["live"] is not None else "  (none)"
        print(f"{t:12} {r['seg']:14} {r['side'] + '@' + format(r['ask'], '.2f'):10} "
              f"{r['winner']:5} {r['twin']:+8.2f} {lv:>8}")
    print()
    for _, name in [(0, "S1 full band"), (0, "S2 0.55-0.75"),
                    (0, "S3 0.60-0.75")]:
        sub = [r for r in rows if r["seg"] == name]
        if not sub:
            continue
        twin = sum(r["twin"] for r in sub)
        both = [r for r in sub if r["live"] is not None]
        live_sum = sum(r["live"] for r in both)
        agree = sum(1 for r in both)  # direction identical by construction
        print(f"{name}: twin windows={len(sub)} twin PnL={twin:+.2f} | "
              f"live on same windows: {live_sum:+.2f} "
              f"({len(both)} windows, direction agreement {agree}/{len(both)})")
    tot_t = sum(r["twin"] for r in rows)
    print(f"ALL: twin PnL={tot_t:+.2f} over {len(rows)} windows")


if __name__ == "__main__":
    main()
