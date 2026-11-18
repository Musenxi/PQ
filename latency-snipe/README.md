# latency-snipe — BTC 5m 延迟狙击（主策略）

思路：Binance 现货价格领先，Polymarket BTC 5 分钟涨跌市场盘口滞后。当模型公允概率（TWAP 感知的正态模型 + Binance–Chainlink 基差修正）与盘口 ask 出现 ≥0.08 缺口、且 20 秒跳动 ≥$20 同向时，纸面买入第一腿 $6；若随后双腿合计成本 + 手续费 < 0.95，再买入等量第二腿锁定配对；持有到结算（Chainlink 末 60 秒 TWAP）。

## 文件
- `snipe_paper.py` — 采集器/策略本体（v0.6 代码：含 `--feed` 中继接入与 `--exit-after` 可选退出规则；v0.3/v0.4/v0.5 为同一代码的早期参数形态，演进见 `docs/`）。
- `binance_feed.py` — 东京节点行情中继：Binance aggTrade WebSocket → TCP 新行 JSON 转发（可选 AUTH 令牌），采集器断线时回退 REST。
- `make_dashboard.py` — 由 `data/*.jsonl` 生成静态 dashboard.html。
- `paper-snipe.service` / `paper-snipe.box.service` / `paper-snipe.vps.service` / `paper-feed.service` — systemd 部署单元（服务器地址已脱敏为占位符）。

## 结果（results/）
- `box-v0.3/` — Simular Box 干净长跑最终数据（2026-11-17 09:22 → 2026-11-18 21:35 JST，224 窗，+$19.95 / 去水分 −$11.56），含 dashboard.html。
- `vps-v0.5/` — 阿姆斯特丹 VPS 基线（东京中继喂价，242 窗，+$1.72；快照 2026-11-18 ~22:50）。
- `vps-v0.6/` — 同代码 + `--exit-after 60`（未配对第一腿 60 秒后按最优买价退出），229 窗，−$96.90；同窗 A/B 证明退出规则净代价约 $105。

裁决：三线均为统计零或负，家族关闭。详见 `docs/verdict-2026-11-18.md`。
