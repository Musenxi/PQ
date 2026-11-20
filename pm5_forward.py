#!/usr/bin/env python3
"""pm5 forward test vs the Azure deep recorder (PAPER analysis only).

For each BTC 5m window T in the recorder's clob files:
  - signal: lizi's frozen pm5 (Quant commit 7141231) from Binance perp
    1m bars, generated at T-60s (features end at the bar opened T-2min);
  - entry price: the recorder's own book snapshot for window T nearest
    to T-60s (searched in [T-90s, T-30s]) -- the true pre-open ask,
    walked for a $5 stake over the recorded top-10 ladder;
  - result: Gamma official winner (cached).
Rows are appended (deduped by slug) to results.jsonl; a tier summary
is printed. Fee: 0.07 before 2026-11-20 23:59 UTC, 0.05 after (the
5m taker schedule flip), per-window by window start.
"""
import argparse
import ast
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REC_DATA = "/root/polymarket-recorder/data"
RESULTS = os.path.join(HERE, "results.jsonl")
WINNERS = os.path.join(HERE, "winners.json")
FEE_FLIP_UTC = 1795219140  # 2026-11-20 23:59 UTC
STAKE = 5.0

from quant.data.binance_vision import _fetch, _kline_paths, parse_klines  # noqa: E402
from quant.research import event_pm5 as pm5  # noqa: E402
from quant.research.event_minute import build_minute_features  # noqa: E402
import pandas as pd  # noqa: E402
from pathlib import Path  # noqa: E402

COLUMNS = ["open", "high", "low", "close", "volume", "taker_buy_volume"]
UA = {"User-Agent": "Mozilla/5.0 (pm5-forward)"}


def fee_rate(start_ts):
    return 0.07 if start_ts < FEE_FLIP_UTC else 0.05


def load_winners():
    if os.path.exists(WINNERS):
        return json.loads(open(WINNERS).read())
    return {}


def gamma_winner(slug, cache):
    if slug in cache:
        return cache[slug]
    try:
        req = urllib.request.Request(
            f"https://gamma-api.polymarket.com/events?slug={slug}", headers=UA)
        ev = json.loads(urllib.request.urlopen(req, timeout=12).read())
        if not ev:
            return None
        m = ev[0]["markets"][0]
        if m.get("umaResolutionStatus") != "resolved" or not m.get("outcomePrices"):
            return None
        outs = ast.literal_eval(m["outcomes"])
        prices = [float(x) for x in ast.literal_eval(m["outcomePrices"])]
        w = outs[prices.index(max(prices))]
        cache[slug] = w
        return w
    except Exception:
        return None


def perp_bars(day_from, day_to):
    """Perp 1m bars: Vision daily zips, REST klines for the tail day."""
    frames = []
    paths = _kline_paths("BTCUSDT", "1m", pd.Timestamp(day_from, tz="UTC"),
                         pd.Timestamp(day_to, tz="UTC"), "futures/um", "klines")
    for path in paths:
        payload = _fetch(path)
        if payload is not None:
            frames.append(parse_klines(payload)[COLUMNS].astype(float))
    m1 = pd.concat(frames).sort_index()
    m1 = m1[~m1.index.duplicated(keep="last")]
    # REST tail: Vision daily zips can lag >1 day (the 2026-11-19 zip
    # still 404s on 11-20); fill from the last Vision bar to now via
    # fapi klines in 1500-bar chunks so the feature grid has no holes.
    try:
        start_ms = int(m1.index.max().timestamp() * 1000) + 60000
        end_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
        while start_ms < end_ms:
            url = (f"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT"
                   f"&interval=1m&startTime={start_ms}&limit=1500")
            req = urllib.request.Request(url, headers=UA)
            raw = json.loads(urllib.request.urlopen(req, timeout=15).read())
            if not raw:
                break
            idx = pd.to_datetime([r[0] for r in raw], unit="ms", utc=True)
            m1 = pd.concat([m1, pd.DataFrame(
                {"open": [float(r[1]) for r in raw], "high": [float(r[2]) for r in raw],
                 "low": [float(r[3]) for r in raw], "close": [float(r[4]) for r in raw],
                 "volume": [float(r[5]) for r in raw],
                 "taker_buy_volume": [float(r[9]) for r in raw]}, index=idx)])
            start_ms = int(raw[-1][0]) + 60000
    except Exception as e:
        print(f"[warn] REST tail failed: {e}", flush=True)
    m1 = m1.sort_index()
    return m1[~m1.index.duplicated(keep="last")]


def predictions(m1, model):
    feats = build_minute_features(m1)
    feats = feats[feats["z2880"].notna() & feats["r1"].notna()].copy()
    feats["sym"] = 0
    start = feats.index + pd.Timedelta(minutes=2)
    keep = (start.minute % 5 == 0) & (start.second == 0)
    feats = feats[keep]
    feats.index = start[keep]
    return pd.Series(model.predict(feats), index=feats.index)


def walk_asks(asks, stake):
    """VWAP to spend `stake` walking recorded ask levels; None if the
    visible ladder cannot fill 99% of it."""
    got = cost = 0.0
    for p, s in asks:
        if cost >= stake:
            break
        take_cost = min(s * p, stake - cost)
        got += take_cost / p
        cost += take_cost
    if cost < stake * 0.99:
        return None
    return cost / got


def preopen_asks(slugs):
    """slug -> {outcome: (recv_offset_s, vwap)} from the recorder clob
    files: the snapshot nearest to T-60 within [T-90, T-30]."""
    best = {s: {} for s in slugs}
    files = sorted(f for f in os.listdir(REC_DATA) if f.startswith("clob-"))
    want = set(slugs)
    for fn in files:
        with open(os.path.join(REC_DATA, fn)) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                slug = r.get("slug")
                if slug not in want:
                    continue
                T = int(slug.rsplit("-", 1)[1])
                off = r["_recv"] - T
                if not (-90 <= off <= -30):
                    continue
                cur = best[slug].get(r["outcome"])
                if cur is None or abs(off + 60) < abs(cur[0] + 60):
                    vwap = walk_asks(r.get("asks") or [], STAKE)
                    best[slug][r["outcome"]] = (off, vwap)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-back", type=int, default=8,
                    help="clob files / bars lookback window")
    args = ap.parse_args()
    model = pm5.Pm5Model.load(Path(HERE) / "models" / "event_signal")
    done = set()
    if os.path.exists(RESULTS):
        done = {json.loads(l)["slug"] for l in open(RESULTS) if l.strip()}

    # candidate windows: slugs present in recent clob files
    files = sorted(f for f in os.listdir(REC_DATA) if f.startswith("clob-"))
    files = files[-(args.days_back + 1):]
    slugs = set()
    for fn in files:
        day = fn[5:15]
        with open(os.path.join(REC_DATA, fn)) as f:
            for line in f:
                try:
                    slugs.add(json.loads(line)["slug"])
                except Exception:
                    continue
    now = datetime.now(timezone.utc)
    todo = sorted(s for s in slugs
                  if int(s.rsplit("-", 1)[1]) + 300 < now.timestamp()
                  and s not in done)
    print(f"candidates={len(todo)} (already done={len(done)})", flush=True)
    if not todo:
        return
    t_min = min(int(s.rsplit("-", 1)[1]) for s in todo)
    t_max = max(int(s.rsplit("-", 1)[1]) for s in todo)
    bars_from = datetime.fromtimestamp(t_min - 3 * 86400, timezone.utc).strftime("%Y-%m-%d")
    bars_to = datetime.fromtimestamp(t_max, timezone.utc).strftime("%Y-%m-%d")
    preds = predictions(perp_bars(bars_from, bars_to), model)
    books = preopen_asks(todo)
    cache = load_winners()
    new_rows = 0
    with open(RESULTS, "a") as out:
        for slug in todo:
            T = int(slug.rsplit("-", 1)[1])
            Ts = pd.Timestamp(T, unit="s", tz="UTC")
            if Ts not in preds.index:
                continue
            w = gamma_winner(slug, cache)
            if w is None:
                continue
            p = float(preds.loc[Ts])
            side = "Up" if p >= 0.5 else "Down"
            off, vwap = books.get(slug, {}).get(side, (None, None))
            row = {"slug": slug, "start": T, "p": round(p, 4),
                   "conf": round(abs(p - 0.5), 4), "side": side,
                   "winner": w, "win": side == w,
                   "ask_off_s": None if off is None else round(off, 1),
                   "ask": None if vwap is None else round(vwap, 4)}
            if vwap:
                sh = STAKE / vwap
                fr = fee_rate(T)
                row["fee_rate"] = fr
                row["pnl"] = round(sh * (1.0 if row["win"] else 0.0) - STAKE
                                   - fr * sh * vwap * (1 - vwap), 4)
            out.write(json.dumps(row) + "\n")
            new_rows += 1
    json.dump(cache, open(WINNERS, "w"))
    print(f"appended {new_rows} rows", flush=True)

    rows = [json.loads(l) for l in open(RESULTS) if l.strip()]
    priced = [r for r in rows if r.get("ask")]
    print(f"total rows={len(rows)} priced={len(priced)}", flush=True)
    for name, thr in (("all", 0.0), ("top20", 0.02620549278301393),
                      ("top10", 0.035060987352053624), ("top05", 0.04079314582556408)):
        d = [r for r in priced if r["conf"] >= thr]
        if not d:
            print(f"{name}: no priced bets", flush=True)
            continue
        wr = sum(r["win"] for r in d) / len(d)
        ma = sum(r["ask"] for r in d) / len(d)
        pnl = sum(r["pnl"] for r in d)
        print(f"{name}: bets={len(d)} win={wr:.1%} mean_ask={ma:.3f} "
              f"win-ask={wr - ma:+.3f} pnl=${pnl:+.2f}", flush=True)


if __name__ == "__main__":
    main()
