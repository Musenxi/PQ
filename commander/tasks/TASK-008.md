# TASK-008 单机多变体扫描（24 个变体 × 2 折）

接收方：**只 @Ju_Cue_JP2_Bot 一台**（指挥端按 lizi 的指示改的：一台机串行
跑完，多迭代、以量取胜）。发布：Muse，2026-11-28。
@Ju_Cue_SG1_bot @Ju_Cue_JP1_bot 本轮不用跑，等后续任务。

## 做什么

脚本 `commander/pipeline/sweep_variants.py` 已入仓（不要修改）。它把
24 个变体（v1/v2 引擎 × 特征子集 × 超参 × 决策时点）各在 2 个时间折上
训练，逐个报 log-loss（对市场 mid）和模拟盈亏，最后给排名表。

**定位：这是筛选，不是结论。** 变体多，总有几个靠运气好看的。排名按
两折平均 log-loss 差（对市场）；只有两折都赢过市场的才会被标记。
被标记的变体只是 12-03 正式重训的候选，要在新数据上过冻结标准才算数。

## 命令

```bash
git pull
time python3 commander/pipeline/sweep_variants.py \
  --features 'commander/results/TASK-004-features-*.csv' \
             'commander/results/TASK-003-features-Ju_Cue_JP2_Bot.csv'
```

预计总耗时几分钟。特征文件正好 8 个（7 个 TASK-004 + 1 个 TASK-003 JP2），
读入应为 8584 行 / 2152 窗口（脚本会在 stderr 打印，不对就停下来报群里）。

## 结果提交

结果文件：`commander/results/TASK-008-Ju_Cue_JP2_Bot.md`，格式：

```
TASK-008 完成
运行耗时秒: <time 的 real 秒数>
读入行数: <脚本 stderr 的 rows 数>
<脚本 stdout 原样粘贴（48 条 JSON + SUMMARY 段）>
备注: <无则写"无">
```

commit + push（署名用 Musenxi，与 JP1 一致）。报错把原文贴进备注，
第一行改 `TASK-008 失败`，照样提交。
