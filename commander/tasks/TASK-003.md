# TASK-003 特征提取管线干跑（2026-11-25 一天数据）

接收方：三台都做，但分片不同（见下）。发布：Muse，2026-11-27。
目的：只验证管线（下载→解压→跑脚本→产出特征表），**不出任何交易结论**。

## 输入

1. 脚本和标签都在本仓库：
   - 脚本 `commander/pipeline/extract_features.py`（不要修改它）
   - 标签 `commander/pipeline/labels/labels_2026-11-25.csv`（官方赢家，已备好）
2. 数据包（约 28 MB，含 clob/rtds/binance 三个流，2026-11-25 全天）：
   - 下载：https://muse.ai/files/1506320995891377/2137357776960733/s293juv2n7wb5wtlr5lqh3se/recorder-2026-11-25.tar.gz
   - md5：`bdeee12943c79953e9efb3bcdd524389`
   - **链接有效期到 2026-11-29 10:46 JST**。过期或下不动就在群里报，我重传。

## 步骤（原样执行，把路径换成你本机的仓库路径）

```bash
git pull
curl -L -o /tmp/recorder-2026-11-25.tar.gz "https://muse.ai/files/1506320995891377/2137357776960733/s293juv2n7wb5wtlr5lqh3se/recorder-2026-11-25.tar.gz"
md5sum /tmp/recorder-2026-11-25.tar.gz   # 必须等于 bdeee12943c79953e9efb3bcdd524389，不符就停下来报到群里
mkdir -p /tmp/rec25 && tar -xzf /tmp/recorder-2026-11-25.tar.gz -C /tmp/rec25
time python3 commander/pipeline/extract_features.py \
  --data-dir /tmp/rec25 --date 2026-11-25 \
  --start-unix <你的起始> --end-unix <你的结束> \
  --labels commander/pipeline/labels/labels_2026-11-25.csv \
  --out commander/results/TASK-003-features-<你的 bot 用户名>.csv
```

## 分片（窗口起始 unix，左闭右开）

- @Ju_Cue_JP2_Bot：**全天** `--start-unix 1795564800 --end-unix 1795651200`
- @Ju_Cue_SG1_bot：**前半** `--start-unix 1795564800 --end-unix 1795608000`
- @Ju_Cue_JP1_bot：**后半** `--start-unix 1795608000 --end-unix 1795651200`

## 结果提交

1. 特征表：`commander/results/TASK-003-features-<你的 bot 用户名>.csv`（脚本直接产出）
2. 结果文件：`commander/results/TASK-003-<你的 bot 用户名>.md`，格式：

```
TASK-003 完成
运行耗时秒: <time 输出的 real 秒数>
产出md5: <你那份 features csv 的 md5sum>
<脚本 stdout 的 JSON summary 原样粘贴>
备注: <无则写"无">
```

3. commit + push。报错不要改脚本，把报错原文贴进结果文件的"备注"，
   第一行改写为 `TASK-003 失败`，照样提交。
