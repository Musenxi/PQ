# Optimization backtests — 2026-11-17 ~21:25 JST

Method: `~/workspace/polymarket-paper/resim.py` replays recorded ticks.
Datasets: Box v0.3 full set (67 settled leg-1 entries, asks only, no bids) and
VPS v0.5 set (12 settled entries, ticks include bids). Fee formula as live:
fee/share = 0.07 * p * (1-p); live pair rule p1 + opp_ask + opp_fee/share < T.

## A) Pair-threshold sweep (tick replay)

VPS (replay at T=0.95 reproduces actual exactly: -21.41):
- 0.95: 8 pairs +3.39, 4 unpaired -24.81, total -21.41
- 0.96: total -21.79 | 0.97: -22.54 | 0.98: -16.44 (one rescue) | 0.99: -16.72

Box (replay at 0.95 gives -17.14 vs actual +1.04 — replay does NOT reproduce
the Box baseline, mostly the windfall window's fills; deltas still usable):
- 0.95: -17.14 | 0.96: -17.73 | 0.97: -28.27 | 0.98: -27.75 | 0.99: -36.99

Verdict: REJECT loosening. On the large dataset it monotonically loses —
the margin surrendered on all 50+ pairs outweighs rescuing 1-2 unpaired legs.

## B) Exit rule (VPS only, bids required; sell unpaired leg-1 at best bid)

- trigger 60s: total -7.40 (5 exits, exit PnL -10.33, avg ~-2.07/exit)
- trigger 90s: total -12.59 | trigger 120s: total -14.34
- vs actual -21.41 on the same 12 windows.

Verdict: ADOPT as the v0.6 core change. Caveats: n=12 entries / 5 exits;
assumes full fill at best bid (paper); earlier trigger was better in-sample.

## C) Trend filter (actual results partitioned by trailing 300s spot move)

Box (n=67): |d|<75: 52 entries, pair 40/52, +14.16 | 75-150: 12, 9/12, -8.75
| >150: 3, 2/3, -4.37. Dropping |d|>100 keeps 58, PnL +6.06 (vs +1.04).
Dropping trend-chase entries makes it WORSE (-4.80).
VPS (n=12): 75-150 bucket was 0/3 paired, -18.69; drop>100 -> -8.98.

Verdict: INCONCLUSIVE / weak. Small positive for a |d300|>100 guard on the
Box set (~+$5 over 67 windows, noise-level); do not add yet — one variable
at a time. Revisit with more data.

## Decision (assistant's pick, delegated by lizi 2026-11-17)

v0.6 = v0.5 + exit rule only (sell unpaired leg-1 at best bid once it has
been unpaired for 60-90s). Threshold stays 0.95. No trend filter yet.
Deploy as paper only, fresh data dir, after lizi's go-ahead.
