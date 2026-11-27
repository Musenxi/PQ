# TASK-005 训练管线干跑（8 天特征库，三折时间切分）

接收方：三台各跑一折（见下）。发布：Muse，2026-11-27。
目的：验证训练脚本在你们机器上端到端可跑、量各折的样本外指标稳定性。
**这是管线干跑，不出交易结论、不定策略。**

## 输入（全部已在仓库内，不需要下载）

- 脚本：`commander/pipeline/train_model.py`（不要修改）
- 特征：`commander/results/TASK-004-features-*.csv`（7 天）+
  `commander/results/TASK-003-features-Ju_Cue_JP2_Bot.csv`（11-25 全天）
- 环境：lightgbm 已装（TASK-002 验证过）。缺包就报群里，不要自己改脚本绕过。

## 命令（train-end 换成你那折的）

```bash
git pull
time python3 commander/pipeline/train_model.py \
  --features 'commander/results/TASK-004-features-*.csv' \
             'commander/results/TASK-003-features-Ju_Cue_JP2_Bot.csv' \
  --train-end <你那折的 train-end>
```

## 分折（按 window_start 时间切分，早训晚测）

- @Ju_Cue_JP2_Bot：`--train-end 1795478400`（训 11-19~23，测 11-24~26）
- @Ju_Cue_SG1_bot：`--train-end 1795564800`（训 11-19~24，测 11-25~26）
- @Ju_Cue_JP1_bot：`--train-end 1795651200`（训 11-19~25，测 11-26）

## 结果提交

结果文件：`commander/results/TASK-005-<你的 bot 用户名>.md`，格式：

```
TASK-005 完成
train-end: <你的数值>
运行耗时秒: <time 的 real 秒数>
<脚本 stdout 的 JSON 报告原样粘贴>
备注: <无则写"无">
```

commit + push。报错把原文贴进备注，第一行改 `TASK-005 失败`，照样提交。
