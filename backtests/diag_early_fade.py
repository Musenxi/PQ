"""Diagnostic: BTC 1h 'early pop then fade' (2026-11-23, lizi's question).

Question: when BTC moves early in a 1h window, how often does that
direction survive to the official (Gamma/TWAP) settlement, and is
buying the early direction at the contemporaneous ask profitable
by early-move size? Plus the farm slice: how do fair-07 / fv7-persist
entries perform conditional on the index move at their entry moment?

Data: Quant observer pm1h_*.jsonl on Azure (book rows every ~10 s
with Binance index + top-5 books; resolution rows = official winner,
price_to_beat, final_price) and farm1h trades/settlements copied
from the VPS. Read-only diagnostic; generates a candidate feature
for the ~2026-12-03 retrain, NOT a live change.
"""
import json, glob, collections, bisect, sys

OBS = sorted(glob.glob('/root/quant/data/polymarket/pm1h_*.jsonl'))
FARM_TR = '/tmp/farm1h_trades.jsonl'
FARM_ST = '/tmp/farm1h_settlements.jsonl'

def load(p):
    rows = []
    try:
        for line in open(p):
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except Exception: pass
    except FileNotFoundError:
        pass
    return rows

# ---- observer: per-window index path, books, resolution (BTC only)
paths = {}       # slug -> list of (offset, index, up_ask, down_ask)
winner = {}      # slug -> 'Up'/'Down'
for fn in OBS:
    for r in load(fn):
        if r.get('type') == 'resolution':
            # resolution rows carry no 'symbol'; use the slug prefix
            if r['slug'].startswith('btc-') and r.get('winner') in ('Up', 'Down'):
                winner[r['slug']] = r['winner']
            continue
        if r.get('symbol') != 'btc':
            continue
        if r.get('type') == 'book':
            slug = r['slug']
            idx = (r.get('ref') or {}).get('index')
            if idx is None:
                continue
            ua = (r.get('up') or {}).get('asks') or []
            da = (r.get('down') or {}).get('asks') or []
            paths.setdefault(slug, []).append(
                (r['offset'], idx,
                 ua[0][0] if ua else None,
                 da[0][0] if da else None))

for slug in paths:
    paths[slug].sort()

def at(slug, target_off, tol=45):
    """(index, up_ask, down_ask) at the sample nearest target_off."""
    pts = paths.get(slug)
    if not pts:
        return None
    offs = [p[0] for p in pts]
    i = bisect.bisect_left(offs, target_off)
    cands = []
    if i < len(pts): cands.append(pts[i])
    if i > 0: cands.append(pts[i - 1])
    best = min(cands, key=lambda p: abs(p[0] - target_off))
    if abs(best[0] - target_off) > tol:
        return None
    return best[1], best[2], best[3]

slugs = sorted(set(paths) & set(winner))
print(f'BTC 1h windows with path + official winner: {len(slugs)}')

BUCKETS = [(0, 15), (15, 40), (40, 80), (80, 1e9)]
def bucket(x):
    for lo, hi in BUCKETS:
        if lo <= abs(x) < hi:
            return f'{lo}-{int(hi) if hi < 1e9 else "+"}'
    return '?'

def analyse(k):
    surv = collections.defaultdict(lambda: [0, 0])       # bucket -> [n, survive]
    trade = collections.defaultdict(lambda: [0, 0.0])    # bucket -> [n, sum win-ask]
    for slug in slugs:
        s0 = at(slug, 0)
        sk = at(slug, k)
        if not s0 or not sk:
            continue
        m = sk[0] - s0[0]
        if m == 0:
            continue
        side = 'Up' if m > 0 else 'Down'
        ask = sk[1] if side == 'Up' else sk[2]
        b = bucket(m)
        surv[b][0] += 1
        win = 1.0 if winner[slug] == side else 0.0
        surv[b][1] += win
        if ask is not None:
            fee = 0.01 * ask * (1 - ask)
            trade[b][0] += 1
            trade[b][1] += win - ask - fee
    print(f'-- early move at +{k}s, by |move| bucket (USD) --')
    for lo, hi in BUCKETS:
        b = f'{lo}-{int(hi) if hi < 1e9 else "+"}'
        n, s = surv[b]
        tn, tp = trade[b]
        if n:
            print(f'  |m| {b:>7}: n={n:3d} survive {s/n:.0%} '
                  f'| buy early side: n={tn} win-ask {tp/tn:+.3f}')

for k in (120, 300, 600):
    analyse(k)

# ---- fade detail at +300: pops up that finished Down, drops that finished Up
fade_up = fade_dn = pop_up = pop_dn = 0
for slug in slugs:
    s0, s5 = at(slug, 0), at(slug, 300)
    if not s0 or not s5:
        continue
    m = s5[0] - s0[0]
    if m >= 40:
        pop_up += 1
        if winner[slug] == 'Down': fade_up += 1
    if m <= -40:
        pop_dn += 1
        if winner[slug] == 'Up': fade_dn += 1
print(f'pops +$40 by +300s: {pop_up}, faded to Down: {fade_up} '
      f'({fade_up/pop_up:.0%})' if pop_up else 'no +$40 pops')
print(f'drops -$40 by +300s: {pop_dn}, faded to Up: {fade_dn} '
      f'({fade_dn/pop_dn:.0%})' if pop_dn else 'no -$40 drops')

# ---- farm slice: entries by index move at entry moment
trades = load(FARM_TR)
sett = {(r['account'], r['slug']): r for r in load(FARM_ST)
        if isinstance(r.get('pnl'), (int, float))}
ent = collections.defaultdict(lambda: [0, 0, 0.0])   # (acct, bucket) -> [n, wins, win-ask sum]
for t in trades:
    if t['account'] not in ('fair-07', 'fv7-persist') or t.get('leg') != 1:
        continue
    slug = t['slug']
    if slug not in winner:
        continue
    start = int(slug.split('-')[-1])
    import datetime
    ets = datetime.datetime.fromisoformat(
        t['ts'].replace('Z', '+00:00')).timestamp()
    off = ets - start
    s0, se = at(slug, 0), at(slug, off, tol=60)
    if not s0 or not se:
        continue
    m = se[0] - s0[0]
    b = bucket(m)
    ask = t['price']
    win = 1.0 if winner[slug] == t['side'] else 0.0
    fee = 0.01 * ask * (1 - ask)
    e = ent[(t['account'], b)]
    e[0] += 1; e[1] += win; e[2] += win - ask - fee
print('-- farm entries by |index move at entry| --')
for acct in ('fair-07', 'fv7-persist'):
    for lo, hi in BUCKETS:
        b = f'{lo}-{int(hi) if hi < 1e9 else "+"}'
        n, w, s = ent[(acct, b)]
        if n:
            print(f'  {acct} |m| {b:>7}: n={n:3d} win {w/n:.0%} win-ask {s/n:+.3f}')
