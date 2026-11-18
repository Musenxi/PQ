# Claude 评审的逐条核验（2026-11-17 晚，针对 v0.3 / 24h 纸面数据）

## 被我们的数据/代码证实的

1. **「配对 = 浮盈止盈」重构成立**：对侧 ask ≈ 1 − 持有侧 bid，配对条件等价于持有侧 bid 涨过入场价约 5–7 个点。36 胜 0 负是路径选择的结果，不是套利证据。整体是卖期权形状（约 80% 赚 $1.2 / 20% 亏 $4.9），盈亏平衡配对率约 80–84%，实测 80%，卡在平衡线；45 窗口总盈亏标准误约 ±$16，当前净值与零无统计差异。
2. **TWAP 口径错误成立**：代码（snipe_paper.py 第 301 行）用 σ√τ 的终点分布，结算却是最后 60 秒 TWAP，正确波动为 σ√(τ−40)（τ>60）。常见入场 τ（130–285s）下高估波动约 10–17%，τ 越小越严重。偏差方向使 fair 偏保守，但口径确实错了，要修。
3. **openPrice 与 Gamma priceToBeat 偏差成立**：实测 10 个近期窗口，|差| 中位 $8.4、最大 $37.5（Claude 称中位 $6.5、最大 $23.6，同量级）。该量级歧义可制造 0.04–0.14 的假价差信号，与 0.08 入场门槛同量级。我们模型与结算都用 endpoint 的 openPrice，内部一致；但盘口定价锚部分参考 priceToBeat，信号会被污染。
4. **(a) 两腿同时锁定不成立**：与自有回测一致（82 窗口仅 9 次、每次 1–2 tick）。
5. **止损不创造期望 + 无 bid 数据不可回测**：成立。

## 被我们的数据证伪的

6. **「入场价收窄到 [0.25, 0.60]」不要采纳**：按入场价分桶（剔除存疑窗口，48 笔）：<0.25 共 6 笔、配对率 67%、−$2.71；0.25–0.60 共 33 笔、配对率 76%、−$9.48；>0.60 共 9 笔、配对率 100%、+$6.37，是唯一赚钱的价格带。Claude 只算了单笔盈亏比，没算配对率随价格的变化。样本小，结论方向仅供参考，但至少不能反着用。

## 无法验证的（Claude 自有小样本）

7. WebSocket 亚秒存活率（1 秒 29%）、44 分钟仅 1 段 <1.00 机会、延迟压力测试配对率 67%→33% 等，均来自其约 44 分钟样本，我们的 2 秒轮询数据测不了。方向性提醒（轮询高估可成交性）要认真对待，数字本身不作数。

## 补充：模型校准速查

按模型 fair 分桶看买入侧真实胜率：0.6→64%（n=14）、0.7→75%（n=16）、0.8→80%（n=5），大致单调、无离谱失准。模型不是一无是处，但样本小且有选择偏差。

## v0.4 优先级（核验后排序）

1. 修 TWAP 波动口径（σ√(τ−40)）；开盘价双源对账，endpoint openPrice 与 priceToBeat 差 >$10 的窗口跳过。
2. tick 补记 bid 与多档深度，才能测退出规则、镜像一致性和真实可成交性。
3. 把配对率当核心指标：需稳定 >84% 才有正期望的可能。

---

# v0.4 fixes implemented (2026-11-17 evening, at lizi's instruction)

Local `snipe_paper.py` is now v0.4. The box keeps running v0.3 untouched
until the 24h run ends 2026-11-18 09:22 JST; v0.4 deploys after that.

1. **TWAP vol term fixed.** Fair value uses sigma*sqrt(tau-40) for
   tau>=60; inside the final 60s, a partially-realised TWAP mean with
   variance sigma^2 * tau^3/(3*60^2). Old-term overstatement: 8% at
   tau=285, 17% at tau=150, 34% at tau=90, 73% at tau=60.
   Backtest (resimulation over the run's own ticks; sigma backed out
   per window from the rounded v0.3 fairs; depth filter not replayable):
   old-fair arm +$19.08 / 49 windows vs new-fair arm +$20.11 / 52
   windows. The harness does NOT reproduce the live baseline (live was
   -$0.80 excl. windfall over 45 windows), so the +$1 delta is
   indicative only: the fix is theoretically correct but not a PnL
   lever on this dataset. It slightly widens gaps -> slightly more
   entries (4 windows only-new: -$4.77; 1 only-old: -$6.36).
2. **Open-price live filter: NOT implementable as designed.** Gamma
   attaches eventMetadata.priceToBeat only after the window closes
   (verified live: current window's event has no eventMetadata key at
   all). Model and settlement already share the operative endpoint
   open, so v0.4 instead records open_ptb/open_diff in every
   settlement row (path verified via recover_orphans on a seeded old
   window). Post-hoc correlation over the 49 settled v0.3 windows
   (excl. windfall): |diff|<=10 -> n=24, PnL +$0.01, 3 unpaired
   (-$18.87); |diff|>10 -> n=25, PnL -$5.05, 7 unpaired (-$31.54);
   max |diff| $80.0 (the run's first trade window, an unpaired loss).
   Directionally consistent with the concern, not statistically
   decisive, and not live-actionable.
3. **Ticks record bids and sizes.** up/down bid, ask size, bid size
   added (verified in smoke test; also end-to-end BUY+PAIR in a
   4-minute scratch run). Exit rules and mirror-consistency checks
   become backtestable from the next run onward.
