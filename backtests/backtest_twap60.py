#!/usr/bin/env python3
"""Final-60s TWAP-arithmetic backtest (strategy A, lizi 2026-11-21).

Hypothesis: in the last 60 s of a BTC 5m window the settlement TWAP
is mostly arithmetic -- the realised part of the final-60s mean is
already fixed, the remaining variance shrinks with (60-k)^3 -- while
the CLOB price still tracks spot. If the market under-weights the
realised TWAP segment, an arithmetic fair (the farm v0.4 formula,
restricted to the final 60 s and the contested band) beats the ask.

Data: the Azure deep recorder (Binance prints, 1 s CLOB snapshots,
RTDS twap_sixty for a semantics check). Settlement ONLY from Gamma
outcomePrices (lizi's principle); priceToBeat from Gamma
eventMetadata for the Chainlink open anchor.

Per window, first trigger only (one trade per window), stake $5:
  arithmetic fair at snapshot time t (k seconds into the final 60):
    E[TWAP] = (realised_mean_adj * k + spot_adj * (60 - k)) / 60
    var     = sigma^2 * (60 - k)^3 / (3 * 60^2)     (v0.4 formula)
    fair_up = Phi( ln(E[TWAP] / open_cl) / sqrt(var) )
  spot/realised from Binance prints, adjusted by the basis measured
  at the window open (priceToBeat - Binance price at open).
  Buy a side when fair_side - ask >= GAP and ask in [0.20, 0.80].
Fill variants: (i) trigger snapshot's ask (optimistic);
(ii) next snapshot's ask (quote survival). Fees 0.07 before
2026-11-20 23:59 UTC, 0.05 after. Stdlib only; runs on Azure.
"""
import bisect
import glob as _glob
import gzip
import json
import math
import os
import random
import time
import urllib.request

REC = "/root/polymarket-recorder/data"


def open_rec(kind, day):
    """Recorder files are gzipped after 2 days; open either form."""
    plain = os.path.join(REC, f"{kind}-{day}.jsonl")
    if os.path.exists(plain):
        return open(plain)
    return gzip.open(plain + ".gz", "rt")
HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0"}
FEE_FLIP = 1795219140  # 2026-11-20 23:59 UTC
STAKE = 5.0
BAND = (0.20, 0.80)
GAPS = (0.03, 0.05, 0.08)


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def load_binance(days):
    ts, px = [], []
    for d in days:
        try:
            f = open_rec("binance", d)
        except FileNotFoundError:
            continue
        with f:
            for line in f:
                r = json.loads(line)
                ts.append(float(r["ts"]))
                px.append(float(r["p"]))
    idx = sorted(range(len(ts)), key=lambda i: ts[i])
    return [ts[i] for i in idx], [px[i] for i in idx]


def price_at(ts, px, t):
    i = bisect.bisect_right(ts, t) - 1
    return px[i] if i >= 0 else None


def load_snapshots(days):
    """(slug, outcome) -> sorted [(recv, ask, asks_ladder)] for tau in [0, 65]."""
    out = {}
    for d in days:
        try:
            f = open_rec("clob", d)
        except FileNotFoundError:
            continue
        with f:
            for line in f:
                if '"asks"' not in line:
                    continue
                r = json.loads(line)
                slug = r.get("slug")
                if not slug or "-5m-" not in slug:
                    continue
                T = int(slug.rsplit("-", 1)[1])
                recv = float(r["_recv"])
                tau = T + 300 - recv
                if tau < 0 or tau > 65:
                    continue
                asks = r.get("asks") or []
                if not asks:
                    continue
                out.setdefault((slug, r["outcome"]), []).append(
                    (recv, float(asks[0][0]), asks))
    for k in out:
        out[k].sort()
    return out


def load_twap_end(days):
    """slug -> twap_sixty value at window end (settlement series check)."""
    pts = []
    for d in days:
        try:
            f = open_rec("rtds", d)
        except FileNotFoundError:
            continue
        with f:
            for line in f:
                if "twap_sixty" not in line:
                    continue
                r = json.loads(line)
                pts.append((float(r["ts"]) / 1000.0, float(r["value"])))
    pts.sort()
    return pts


def gamma_info(slug, cache):
    if slug in cache:
        return cache[slug]
    info = None
    try:
        req = urllib.request.Request(
            f"https://gamma-api.polymarket.com/events?slug={slug}", headers=UA)
        ev = json.loads(urllib.request.urlopen(req, timeout=12).read())
        m = ev[0]["markets"][0]
        if m.get("umaResolutionStatus") == "resolved":
            op = json.loads(m["outcomePrices"])
            meta = ev[0].get("eventMetadata") or {}
            info = {"winner": "Up" if float(op[0]) > 0.5 else "Down",
                    "ptb": meta.get("priceToBeat")}
    except Exception:
        info = None
    cache[slug] = info
    time.sleep(0.03)
    return info


def walk_asks(asks, usd):
    spent = got = 0.0
    for p, s in asks:
        p, s = float(p), float(s)
        take = min(s, (usd - spent) / p)
        if take <= 0:
            break
        spent += take * p
        got += take
        if spent >= usd - 1e-9:
            break
    if got <= 0 or spent < 0.99 * usd:
        return None
    return spent / got, got, spent


def sigma_at(ts, px, t):
    """Trailing-900 s stdev of 1 s log returns (per second), at time t."""
    rets = []
    prev = None
    s = int(t) - 900
    while s <= int(t):
        v = price_at(ts, px, s)
        if v is not None and prev is not None and prev > 0:
            rets.append(math.log(v / prev))
        if v is not None:
            prev = v
        s += 1
    if len(rets) < 300:
        return None
    mu = sum(rets) / len(rets)
    return math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets))


def main():
    days = sorted({os.path.basename(p)[8:].removesuffix(".jsonl.gz")
                   .removesuffix(".jsonl")
                   for p in _glob.glob(os.path.join(REC, "binance-*.jsonl*"))})
    print(f"days: {days}", flush=True)
    print("loading binance prints...", flush=True)
    bts, bpx = load_binance(days)
    print(f"  {len(bts)} prints", flush=True)
    print("loading clob snapshots (final 65 s only)...", flush=True)
    snaps = load_snapshots(days)
    slugs = sorted({s for s, _ in snaps})
    print(f"  {len(snaps)} series, {len(slugs)} windows", flush=True)
    twap_pts = load_twap_end(days)
    twap_ts = [p[0] for p in twap_pts]

    cache_path = os.path.join(HERE, "twap60_gamma_cache.json")
    cache = {}
    if os.path.exists(cache_path):
        cache = json.load(open(cache_path))
    for slug in slugs:
        gamma_info(slug, cache)
    json.dump(cache, open(cache_path, "w"))
    print(f"  gamma resolved: {sum(1 for v in cache.values() if v)}", flush=True)

    # semantics check: sign(twap at end - priceToBeat) vs Gamma winner
    chk_ok = chk_n = 0
    for slug in slugs:
        info = cache.get(slug)
        if not info or info.get("ptb") is None:
            continue
        T = int(slug.rsplit("-", 1)[1])
        i = bisect.bisect_right(twap_ts, T + 300) - 1
        if i < 0:
            continue
        tw = twap_pts[i][1]
        pred = "Up" if tw >= float(info["ptb"]) else "Down"
        chk_n += 1
        chk_ok += pred == info["winner"]
    if chk_n:
        print(f"twap_sixty semantics check: {chk_ok}/{chk_n} = "
              f"{chk_ok / chk_n:.1%} agree with Gamma", flush=True)

    trades = {g: [] for g in GAPS}       # variant (i) trigger-ask fills
    trades_nx = {g: [] for g in GAPS}    # variant (ii) next-snapshot fills
    skipped = {"no_ptb": 0, "no_sigma": 0, "no_seg": 0, "stale_feed": 0}
    for slug in slugs:
        info = cache.get(slug)
        if not info:
            continue
        T = int(slug.rsplit("-", 1)[1])
        if info.get("ptb") is None:
            skipped["no_ptb"] += 1
            continue
        open_cl = float(info["ptb"])
        p_open = price_at(bts, bpx, T + 1)
        if p_open is None:
            skipped["no_seg"] += 1
            continue
        basis = open_cl - p_open
        # feed-freshness guard: the Tokyo Binance feed was down
        # 2026-11-20 16:20 UTC -> 2026-11-21 05:51 UTC (disk full);
        # windows whose final minute has no print within 30 s are
        # priced on a frozen series and must be excluded.
        li = bisect.bisect_right(bts, T + 300) - 1
        if li < 0 or bts[li] < T + 270:
            skipped["stale_feed"] += 1
            continue
        sig = sigma_at(bts, bpx, T + 240)
        if sig is None or sig <= 0:
            skipped["no_sigma"] += 1
            continue
        fee_rate = 0.05 if T >= FEE_FLIP else 0.07
        winner = info["winner"]
        # merge both sides' snapshots into one timeline
        timeline = []
        for side in ("Up", "Down"):
            for recv, ask, ladder in snaps.get((slug, side), []):
                timeline.append((recv, side, ask, ladder))
        timeline.sort()
        triggered = {g: False for g in GAPS}
        for idx, (recv, side, ask, ladder) in enumerate(timeline):
            tau = T + 300 - recv
            if tau > 60 or tau < 1:
                continue
            k = 60.0 - tau
            # realised segment mean over [T+240, recv] on the 1 s grid
            seg = []
            s = T + 240
            while s <= int(recv):
                v = price_at(bts, bpx, s)
                if v is not None:
                    seg.append(v)
                s += 1
            if not seg:
                continue
            realised = sum(seg) / len(seg) + basis
            spot_adj = price_at(bts, bpx, recv) + basis
            e_twap = (realised * k + spot_adj * (60 - k)) / 60.0
            var = sig * sig * (60 - k) ** 3 / (3 * 60 * 60)
            sd = math.sqrt(max(var, 1e-12))
            fair_up = phi(math.log(e_twap / open_cl) / sd)
            fair = fair_up if side == "Up" else 1.0 - fair_up
            if not (BAND[0] <= ask <= BAND[1]):
                continue
            edge = fair - ask
            for g in GAPS:
                if triggered[g] or edge < g:
                    continue
                triggered[g] = True
                w = walk_asks(ladder, STAKE)
                if w is None:
                    continue
                vwap, shares, spent = w
                fee = shares * fee_rate * vwap * (1 - vwap)
                win = side == winner
                pnl = (shares if win else 0.0) - spent - fee
                trades[g].append({"slug": slug, "tau": round(tau), "side": side,
                                   "ask": round(vwap, 4), "win": win,
                                   "pnl": round(pnl, 2)})
                # variant (ii): next snapshot of the same side within 3 s
                for recv2, side2, ask2, ladder2 in timeline[idx + 1:]:
                    if side2 != side:
                        continue
                    if recv2 - recv > 3:
                        break
                    w2 = walk_asks(ladder2, STAKE)
                    if w2 is None:
                        break
                    vwap2, shares2, spent2 = w2
                    fee2 = shares2 * fee_rate * vwap2 * (1 - vwap2)
                    pnl2 = (shares2 if win else 0.0) - spent2 - fee2
                    trades_nx[g].append({"slug": slug, "tau": round(tau),
                                         "side": side, "ask": round(vwap2, 4),
                                         "win": win, "pnl": round(pnl2, 2)})
                    break

    print(f"skipped: {skipped}", flush=True)
    rng = random.Random(42)
    for g in GAPS:
        for label, tt in (("trigger-ask", trades[g]), ("next-ask", trades_nx[g])):
            if not tt:
                print(f"gap {g}: {label}: no trades")
                continue
            n = len(tt)
            wr = sum(t["win"] for t in tt) / n
            ma = sum(t["ask"] for t in tt) / n
            diffs = [(1.0 if t["win"] else 0.0) - t["ask"] for t in tt]
            boot = []
            for _ in range(2000):
                boot.append(sum(rng.choice(diffs) for _ in range(n)) / n)
            boot.sort()
            lo, hi = boot[50], boot[1949]
            print(f"gap {g}: {label}: trades={n} win={wr:.1%} mean_ask={ma:.3f} "
                  f"win-ask={wr - ma:+.3f} CI[{lo:+.3f},{hi:+.3f}] "
                  f"pnl=${sum(t['pnl'] for t in tt):+.2f}")
    # tau split for the primary gap, trigger-ask variant
    tt = trades[0.05]
    if tt:
        for lo_t, hi_t in ((41, 60), (21, 40), (1, 20)):
            sub = [t for t in tt if lo_t <= t["tau"] <= hi_t]
            if sub:
                wr = sum(t["win"] for t in sub) / len(sub)
                ma = sum(t["ask"] for t in sub) / len(sub)
                print(f"  gap 0.05 tau {lo_t}-{hi_t}: n={len(sub)} win={wr:.1%} "
                      f"win-ask={wr - ma:+.3f} pnl=${sum(t['pnl'] for t in sub):+.2f}")


if __name__ == "__main__":
    main()
