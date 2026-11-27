TASK-004 完成

2026-11-20: 耗时秒 9.102813 | 产出md5 3589af4072073aee8b55219dfc1cd183 | 脚本 JSON summary:
```json
{
 "windows": 288,
 "rows": 1152,
 "offsets": [
  60,
  120,
  180,
  240
 ],
 "labeled": 1152,
 "nan_counts": {
  "slug": 0,
  "window_start": 0,
  "offset_s": 0,
  "tau_s": 0,
  "spot_open": 0,
  "spot_now": 0,
  "move": 0,
  "sigma_1s": 659,
  "n_prints_900": 0,
  "twap_open": 0,
  "twap_now": 0,
  "twap_margin": 0,
  "early_max_abs_move_120": 795,
  "early_move_120": 795,
  "up_bid": 108,
  "up_ask": 90,
  "up_mid": 198,
  "spread": 198,
  "up_bid_depth": 0,
  "up_ask_depth": 0,
  "book_imbalance": 0,
  "lt_up": 0,
  "down_bid": 90,
  "down_ask": 108,
  "winner": 0,
  "label_up": 0
 },
 "first_slug": "btc-updown-5m-1795132800",
 "last_slug": "btc-updown-5m-1795218900"
}
```

2026-11-23: 耗时秒 9.805863 | 产出md5 eb8990652485cefbb207988e8c8a1b05 | 脚本 JSON summary:
```json
{
 "windows": 288,
 "rows": 1152,
 "offsets": [
  60,
  120,
  180,
  240
 ],
 "labeled": 1152,
 "nan_counts": {
  "slug": 0,
  "window_start": 0,
  "offset_s": 0,
  "tau_s": 0,
  "spot_open": 0,
  "spot_now": 0,
  "move": 0,
  "sigma_1s": 0,
  "n_prints_900": 0,
  "twap_open": 4,
  "twap_now": 1,
  "twap_margin": 1,
  "early_max_abs_move_120": 288,
  "early_move_120": 288,
  "up_bid": 101,
  "up_ask": 95,
  "up_mid": 196,
  "spread": 196,
  "up_bid_depth": 0,
  "up_ask_depth": 0,
  "book_imbalance": 0,
  "lt_up": 0,
  "down_bid": 95,
  "down_ask": 101,
  "winner": 0,
  "label_up": 0
 },
 "first_slug": "btc-updown-5m-1795392000",
 "last_slug": "btc-updown-5m-1795478100"
}
```

备注: 2026-11-20 的 sigma_1s 缺失659行，early_max_abs_move_120 与 early_move_120 各缺失795行，符合任务注明的 Binance 源中断背景。2026-11-23 的两项 early-window 特征各缺失288行，按脚本在 offset_s=60 时留空的规则；TWAP 和盘口缺失计数见对应 JSON。无执行错误。
