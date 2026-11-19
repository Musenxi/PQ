# live-probe — FAIR 5m 实盘执行探针（已停机，待评审）

2026-11-19 经 lizi 授权的**有限实盘执行测试**：用真实订单测量 FAIR 5m 信号的
执行现实（成交率、滑点、报价存活），**不是策略验证，更不是策略规模部署**。
FAIR 本身未经验证（见 `docs/settlement-grading-bug-2026-11-19.md`：修正结算口径后
农场 FAIR 为负）。2026-11-19 20:07 JST 按 lizi 指令停机（Azure 服务停止 + STOP 闸），
等待评审。

- `live_probe.py` — 探针本体。信号逻辑复制自农场 v2.0.1（开盘前 basis、TWAP 感知
  公允价、盘口接收时刻年龄）；下单为 FOK 市价买入、封顶决策 tick 的 best ask；
  凭据全部走环境变量（`/etc/polymarket-live.env`，仓库内无任何密钥）。
  门控：无私钥 = DRY 模式；真实下单还需 `ARMED` 文件存在；`STOP` 文件为急停闸。
  结算只认 Gamma 官方结果（2026-11-19 晚修复，含 UMA resolved 守卫）。
- `tg_report.py` — Telegram 实时汇报机器人（@jupoly_bot）：只读 tail 探针的
  orders/settlements 日志，推送成交/FOK 被杀/提交失败/结算，并响应 /status。
- `results/` — 完整实盘账本（2026-11-19 当日）：`signals.jsonl`（每次触发与处置）、
  `orders.jsonl`（含 post_latency_ms、成交股数/成本、滑点）、`settlements.jsonl`、
  `probe_state.json`（停机快照，open_orders 已清空）。

配置沿革（结果必须按段看，不得合并）：启动 fair-07（gap 0.08 / tau 60 /
band 0.15–0.92）→ 19:13 JST 切 gap 0.12（fair-09）→ 19:15 JST 切第一名配置
fair-12（gap 0.12 / band 0.30–0.80）。限额沿革：$1.50 目标 / $5 单笔上限为现行界限；
每日单数上限与 $30 日支出上限已于当晚经 lizi 指令撤销。

最终战绩：提交 29、成交 14、FOK 被杀 9、未达交易所 6；已结算 14 笔（8 胜），
净 **−$1.7476**。执行器 2026-11-19 18:47 JST 起位于 Azure 都柏林
（VPS 时代同口径：8 提交 3 成交）；账户余额在停机时约 $46（现金 + 未赎回赢利 +
持仓口径见机器人 /status）。本账户按一次性处理：私钥曾以附件形式经过聊天平台一次，
任何放大规模前必须更换账户。
