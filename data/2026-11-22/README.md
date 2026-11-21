# Raw research data snapshot — 2026-11-22 ~00:55 JST

Paper-farm and live-probe ledgers from the Polymarket BTC up/down
project, exported for offline research. All `.jsonl.gz` — one JSON
object per line. All timestamps inside rows are unix seconds (UTC);
slug suffixes are window start times (unix). Markets:
`btc-updown-5m-<start>` and `btc-updown-1h-<start>`.

## Layout

| dir | what | engine |
|---|---|---|
| `farm-5m-old/` | Original 5m shadow farm, 84 accounts, 7 families (FAIR/MOM/REV/ACVR/SNIPE/OPENFADE/MVAL), running since 2026-11-18 ~16:16 JST, UNBANDED (family bands in `accounts.json`) | `shadow-farm/farm.py` (v2.1 since 2026-11-20 10:11 JST) |
| `farm-5m-band-farm2/` | Band farm opened 2026-11-21 ~19:00 JST: same engine, EVERY entry band = (0.60, 0.75). Roster 30 accounts until 19:52 JST, then completed to 54 (added SNIPE 12 / OPENFADE 6 / MVAL 6) | `shadow-farm/farm2.py` |
| `farm-1h/` | BTC 1h paper farm, FAIR 12 + LATE 8 + BAND clone `band-01` (added 2026-11-21 ~18:52 JST) | `probe-1h/farm1h.py` |
| `farm-1h-swing/` | SWING 4 + OSC 4 exit-rule families on farm1h fair-05 entries | `probe-1h/farm1h_swing.py` |
| `copy-trade/` | Paper mirror of wallet viniangusso's BTC 5m buys (detection via public activity API; lag is minutes) | `shadow-farm/copy_trade.py` |
| `live-probe-1h/` | REAL-MONEY execution probe on Azure (FAIR 1h signals, $1.50 target / $5 max per order / 1 fill per window). `orders.jsonl` = every submit attempt, `settlements.jsonl` = graded fills, `signals.jsonl` = gate evaluations | repo-root `live_probe_1h.py` |
| `live-probe-5m/` | REAL-MONEY 5m probe, PAUSED (final: 15 settled, +$1.37) | — |
| `pm5-forward/` | Forward test of the frozen Quant pm5 model (T−60s entries from recorder books), `results.jsonl` | `pm5_forward.py` |

## Row schemas (farms)

- `trades.jsonl`: one row per executed paper buy:
  `{account, slug, side (Up/Down), price, shares, cost, fees, ts, leg}`
  (`leg` 2 = SNIPE pair-completion leg — exclude leg 2 for entry
  statistics). MVAL rows are multi-entry accumulations.
- `settlements.jsonl`: one row per (account, window) at grading:
  `{account, slug, pnl, ...}` — pnl is net of entry fees, in USD,
  stake $5 per entry (MVAL up to 4/8 entries per window).
- `accounts.json`: the config registry (id, family, params, band).

## Accounting rules (important)

- **Winner = Polymarket's official resolution only** (Gamma
  `outcomePrices` after `umaResolutionStatus == "resolved"`).
  Never derive winners from prices. A grading bug that did exactly
  that was found and fixed 2026-11-19 ~19:43 JST (1,087 rows
  corrected, Δ −$4,888.62); these exports are POST-fix.
- **Judge families family×window**: sum pnl over a family's accounts
  per slug first (accounts within a family are highly correlated —
  FAIR's 12 configs are only 6 distinct; tau_min 30/60 pairs are
  identical), then block-bootstrap over windows. Family totals in
  raw sums are inflated by the account count (~12×).
- Fees: taker fee/share = feeRate × p × (1−p), read live per market.
  Fee change 2026-11-20 23:59 UTC: BTC 5m 0.07 → 0.05; BTC 1h
  0.07 → 0.01. Rows before/after straddle the change.
- Paper fills are at the quoted best ask (2s book polls, freshness
  filter ≤4s since v2.1) — systematically optimistic vs real fills.

## Known holes and config breaks (do not pool across these)

- **Tokyo Binance feed outage** 2026-11-20 16:20 UTC →
  2026-11-21 05:51 UTC (disk full): farms have NO valid windows in
  this range (spot feed frozen/absent).
- **FAIR booksplit verdict** (pre-registered): on fresh books FAIR
  lost significantly (240 windows, 95% CI [−15.22, −5.59]/window
  family-sum) — FAIR is formally "no evidence" since 2026-11-20.
- **Live probe 1h segments** (band/gate changes; never pool):
  S1 full band (0.15, 0.92) until 2026-11-21 19:00 JST
  (25 settled windows, −$20.64, includes the 2026-11-20 00:00 JST
  stacking incident: 4 fills, −$14.97);
  S2 band (0.55, 0.75) 2026-11-21 19:00–21:00 JST;
  S3 band (0.60, 0.75) from 2026-11-21 21:00 JST.
  Entry gate since 2026-11-20: calibration-corrected fair (z/1.35),
  corrected gap ≥ 0.06; per-window cap = 1 FILLED order.
- **band-01** (farm-1h): band (0.55, 0.75) from 2026-11-21 18:52 JST,
  narrowed to (0.60, 0.75) from the 21:00 JST window.
- **farm2 roster break** 2026-11-21 19:52 JST (see above).

## Headline state at export

- Old farm full run: all 7 families negative (family-sums ≈ FAIR
  −$2.6k, MVAL −$5.4k over ~600–800 windows/family).
- MVAL's money is NOT its pair mechanic: locked-pair component ≈ 0;
  PnL is unpaired directional stacking (old farm: Down positions
  +$1,141 vs Up −$6,133). FAIR loses on BOTH sides (Up −$1,344 /
  Down −$1,070).
- Inverting FAIR's trades counterfactually loses the same amount
  (−$2,227 vs −$2,324): both sides' asks sit above their win rates.
- The one open hypothesis: the (0.60, 0.75) "sweet band" (farm2 +
  band-01 + probe S3), pre-registered reads ~2026-11-28/29.
