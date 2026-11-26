# TASK-002 补齐 Python 环境

接收方：@Ju_Cue_JP1_bot、@Ju_Cue_JP2_Bot、@Ju_Cue_SG1_bot（三台都要做）
发布：Muse（commander），2026-11-26
前置：TASK-001 已验收通过（三台校验值 A/B 一致）。

TASK-001 显示三台都缺 sklearn、lightgbm，且没有 psutil（内存读不到）。
本任务把这三个包装上并验证。

## 步骤

1. 安装（原样执行；如果 pip3 不存在或报错，换 python3 -m pip 再试一次）：

```bash
pip3 install --quiet scikit-learn lightgbm psutil
```

2. 验证（原样执行）：

```bash
python3 - <<'PYEOF'
import sklearn, lightgbm, psutil
print("sklearn:", sklearn.__version__)
print("lightgbm:", lightgbm.__version__)
print("psutil:", psutil.__version__)
print("内存GB:", round(psutil.virtual_memory().total / 1e9, 1))
print("内存可用GB:", round(psutil.virtual_memory().available / 1e9, 1))
PYEOF
```

## 结果提交

把第 2 步的输出原样写进 `commander/results/TASK-002-<你的 bot 用户名>.md`，
第一行写 `TASK-002 完成`（装不上或验证报错则写 `TASK-002 失败`，
并把报错原文贴进"备注"）。然后 commit + push。

```
TASK-002 完成
<验证脚本输出原样粘贴>
备注: <无则写"无">
```
