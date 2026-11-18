#!/usr/bin/env python3
"""Generate a static dashboard.html (video-terminal style) from data/*.jsonl."""
import json, os, html
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

def load(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]

ticks = load("ticks.jsonl")
trades = load("trades.jsonl")
settles = load("settlements.jsonl")
state = {}
sp = os.path.join(DATA, "state.json")
if os.path.exists(sp):
    state = json.load(open(sp))
s = state.get("summary", {})
# Prefer log-derived totals (survive restarts / state resets)
if settles:
    s = {"windows": len(settles),
         "wins": sum(1 for x in settles if x["pnl"] >= 0),
         "losses": sum(1 for x in settles if x["pnl"] < 0),
         "pairs": sum(1 for x in settles if x["paired"]),
         "skips": s.get("skips", 0),
         "trades": len(trades),
         "pnl": round(sum(x["pnl"] for x in settles), 4)}
pnl = s.get("pnl", 0.0)
last = ticks[-1] if ticks else {}

def rows(items, cols):
    out = []
    for it in items:
        tds = "".join(f"<td>{html.escape(str(it.get(c, '')))}</td>" for c in cols)
        out.append(f"<tr>{tds}</tr>")
    return "\n".join(out) or "<tr><td colspan='9' class='mut'>暂无记录</td></tr>"

trade_rows = []
for t in trades:
    trade_rows.append({"time": t["ts"][11:19], "market": t["slug"].replace("btc-updown-5m-", ""),
                       "leg": t["leg"], "side": t["side"], "price": t["price"],
                       "shares": t["shares"], "cost": t["cost"], "fees": t["fees"]})
settle_rows = []
for t in settles:
    settle_rows.append({"market": t["slug"].replace("btc-updown-5m-", ""), "winner": t["winner"],
                        "open": round(t["open"], 1), "close": round(t["close"], 1),
                        "paired": "yes" if t["paired"] else "no", "pnl": t["pnl"]})
tick_rows = [{"time": t["ts"][11:19], "btc": t["spot"], "open": round(t["open"], 1) if t["open"] else "",
              "tau": t["tau"], "jump20": t["jump20"], "fair_up": t["fair_up"],
              "up_ask": t["up_ask"], "down_ask": t["down_ask"], "action": t["action"]} for t in ticks[-30:]][::-1]

doc = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>xmayeth-snipe paper v0.1 — Polymarket BTC 5m 纸面交易</title>
<style>
body{{background:#0b0f0c;color:#c9f7c9;font-family:ui-monospace,Menlo,monospace;margin:24px}}
h1{{font-size:18px;color:#7dff8a}} h2{{font-size:14px;color:#7dff8a;margin-top:28px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap}}
.card{{border:1px solid #234;border-radius:8px;padding:10px 16px;background:#101613}}
.card b{{font-size:20px;display:block;color:#fff}}
table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px}}
td,th{{border-bottom:1px solid #223;padding:4px 8px;text-align:left}}
th{{color:#8ab}} .mut{{color:#678}} .pos{{color:#7dff8a}} .neg{{color:#ff7d7d}}
p.note{{color:#9ab;font-size:12px;line-height:1.7;max-width:900px}}
</style></head><body>
<h1>paper-snipe v0.1 · btc up/down 5m · feed binance · settle chainlink TWAP-60s · pair&lt;.95 · hold=resolve</h1>
<div class="cards">
<div class="card">已结算窗口<b>{s.get('windows',0)}</b></div>
<div class="card">胜 / 负<b>{s.get('wins',0)} / {s.get('losses',0)}</b></div>
<div class="card">配对<b>{s.get('pairs',0)}</b></div>
<div class="card">跳过(late/thin)<b>{s.get('skips',0)}</b></div>
<div class="card">纸面交易笔数<b>{s.get('trades',0)}</b></div>
<div class="card">纸面盈亏 USD<b class="{'pos' if pnl>=0 else 'neg'}">{pnl:+.2f}</b></div>
<div class="card">最新 BTC<b>{last.get('spot','—')}</b></div>
<div class="card">当前窗口剩余秒<b>{last.get('tau','—')}</b></div>
</div>

<h2>纸面成交 (trades)</h2>
<table><tr><th>time UTC</th><th>market</th><th>leg</th><th>side</th><th>price</th><th>shares</th><th>cost</th><th>fees</th></tr>
{rows(trade_rows, ['time','market','leg','side','price','shares','cost','fees'])}</table>

<h2>结算 (settlements)</h2>
<table><tr><th>market</th><th>winner</th><th>open(Chainlink)</th><th>close(Chainlink)</th><th>paired</th><th>pnl</th></tr>
{rows(settle_rows, ['market','winner','open','close','paired','pnl'])}</table>

<h2>最近行情 (last ticks)</h2>
<table><tr><th>time UTC</th><th>BTC(Binance)</th><th>open</th><th>tau s</th><th>jump 20s $</th><th>fair Up</th><th>Up ask</th><th>Down ask</th><th>action</th></tr>
{rows(tick_rows, ['time','btc','open','tau','jump20','fair_up','up_ask','down_ask','action'])}</table>

<p class="note">说明：这是纸面交易，没有真实下单。信号源为 Binance 现货（领先指标），开仓参考价与结算来自 Polymarket 的 Chainlink 价格接口；该市场实际按 Chainlink TWAP-60s 结算，模型用正态近似 P(Up)=Φ(ln(S/S0)/(σ√τ))，属于简化近似。手续费按市场费率表模拟：fee = shares × 0.07 × p × (1−p)，仅 taker。样本很小时盈亏没有统计意义，需要连续记录几天再评估。</p>
</body></html>"""

with open(os.path.join(HERE, "dashboard.html"), "w") as f:
    f.write(doc)
print(f"dashboard.html written: {len(trades)} trades, {len(settles)} settlements, {len(ticks)} ticks, pnl {pnl:+.2f}")
