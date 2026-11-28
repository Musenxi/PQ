# TASK-007 v2 残差模型干跑（与 TASK-005 同三折对照）

接收方：三台各跑一折（同 TASK-005 的分折）。发布：Muse，2026-11-28。
目的：验证 v2 残差架构（解析 fair 打底 + LightGBM 只学偏离）在另两折上
是否同样比 v1 略好。**管线干跑，不出交易结论。**

## 输入（已在仓库内）

- 脚本：`commander/pipeline/train_model_v2.py`（不要修改）
- 特征：`commander/results/TASK-004-features-*.csv` +
  `commander/results/TASK-003-features-Ju_Cue_JP2_Bot.csv`

## 命令

```bash
git pull
time python3 commander/pipeline/train_model_v2.py \
  --features 'commander/results/TASK-004-features-*.csv' \
             'commander/results/TASK-003-features-Ju_Cue_JP2_Bot.csv' \
  --train-end <你那折的 train-end>
```

## 分折（与 TASK-005 完全相同，方便逐折对照）

- @Ju_Cue_JP2_Bot：`--train-end 1795564800`（训 11-19~24，测 11-25~26）
- @Ju_Cue_SG1_bot：`--train-end 1795651200`（训 11-19~25，测 11-26）
- @Ju_Cue_JP1_bot：`--train-end 1795478400`（训 11-19~23，测 11-24~26）

注意这次分折与 TASK-005 里你跑的那折**错开一折**，为的是三台合起来把
v2 的三折都跑出来、且每折都有另一个人跑过 v1 可对照。

## 指挥端已跑的参照数（JP2 在 TASK-005 跑过的那折的 v2 版）

train-end 1795478400：logloss_fair_base 0.538、logloss_model 0.493
（v1 同折 0.498）、logloss_market_mid 0.471。

## 结果提交

结果文件：`commander/results/TASK-007-<你的 bot 用户名>.md`，格式：

```
TASK-007 完成
train-end: <你的数值>
运行耗时秒: <time 的 real 秒数>
<脚本 stdout 的 JSON 报告原样粘贴>
备注: <无则写"无">
```

commit + push。报错把原文贴进备注，第一行改 `TASK-007 失败`，照样提交。
