# TASK-004 全量特征提取（2026-11-19 ~ 11-26 其余 7 天）

接收方：三台按天分片（见下）。发布：Muse，2026-11-27。
目的：把已录的其余 7 天全部提成特征表，为 12-03 正式重训备料。**仍不出交易结论。**
11-25 已在 TASK-003 完成，不要重跑。

## 输入

- 脚本：`commander/pipeline/extract_features.py`（仓库内，不要修改）
- 标签：`commander/pipeline/labels/labels_<日期>.csv`（仓库内，8 天已全齐）
- 数据包（每人只下自己分到的天；**链接 2026-11-29 约 11:30–12:00 JST 过期**，先下载再说）：

| 日期 | md5 | 链接 |
|---|---|---|
| 2026-11-19 | b262a338c95d4b02848c047742b1594d | https://muse.ai/files/1506320995891377/2269170583950251/iz92zbvno8efuvfgh0r6zljn/recorder-2026-11-19.tar.gz |
| 2026-11-20 | 611aaf3fa56d9914e0e27c177103abd3 | https://muse.ai/files/1506320995891377/1741865274026092/fb3us0pdbaytqmm4lbr5swvg/recorder-2026-11-20.tar.gz |
| 2026-11-21 | ec2f9529e2bbadd7adfff5d40ab1d53e | https://muse.ai/files/1506320995891377/2042494146417868/rconaqf6if8vu6pmtw7oyndk/recorder-2026-11-21.tar.gz |
| 2026-11-22 | c9857f402745a5cd1c514ed35f0e2ac4 | https://muse.ai/files/1506320995891377/1900112768068415/vhh00l0wcpmtjej2dozjgtl4/recorder-2026-11-22.tar.gz |
| 2026-11-23 | fd3a1c4db17a069d47fb59891c743673 | https://muse.ai/files/1506320995891377/1479193144367554/h0tvcc953noe3p7htqscc7oj/recorder-2026-11-23.tar.gz |
| 2026-11-24 | 8c001b8f14e6c526d90471d5d496d9ac | https://muse.ai/files/1506320995891377/1470322761854791/z4d0fu68shm0qjuj4s4dpsyq/recorder-2026-11-24.tar.gz |
| 2026-11-26 | d6f42b148476b88d89a8b529f9f5991c | https://muse.ai/files/1506320995891377/1203827345638762/scj1jweyxn92ae7y2nvs11zp/recorder-2026-11-26.tar.gz |

## 分片

- @Ju_Cue_JP2_Bot：2026-11-19、2026-11-22、2026-11-26
- @Ju_Cue_SG1_bot：2026-11-20、2026-11-23
- @Ju_Cue_JP1_bot：2026-11-21、2026-11-24

## 每天的命令（日期和 unix 范围换成当天）

```bash
git pull
curl -L -o /tmp/recorder-<日期>.tar.gz "<当天链接>"
md5sum /tmp/recorder-<日期>.tar.gz   # 必须与表中一致，不符就停下报群里
mkdir -p /tmp/rec-<日期> && tar -xzf /tmp/recorder-<日期>.tar.gz -C /tmp/rec-<日期>
time python3 commander/pipeline/extract_features.py \
  --data-dir /tmp/rec-<日期> --date <日期> \
  --start-unix <当天起始> --end-unix <当天结束> \
  --labels commander/pipeline/labels/labels_<日期>.csv \
  --out commander/results/TASK-004-features-<日期>-<你的 bot 用户名>.csv
```

每天的 unix 范围（slug 时间，左闭右开）：

- 2026-11-19：1795046400 – 1795132800
- 2026-11-20：1795132800 – 1795219200
- 2026-11-21：1795219200 – 1795305600
- 2026-11-22：1795305600 – 1795392000
- 2026-11-23：1795392000 – 1795478400
- 2026-11-24：1795478400 – 1795564800
- 2026-11-26：1795651200 – 1795737600

## 已知数据情况（照常跑，不要当故障）

- **2026-11-19 是半天**：记录仪当天约 13:13 UTC 才启动，之前的窗口没有盘口数据，
  产出行数会明显少于 1152 — 按实际产出报告即可。
- **2026-11-20 16:20 UTC 到 11-21 05:51 UTC**：东京 Binance 源中断过（磁盘满），
  这段窗口的现价类特征会缺失或陈旧，脚本会自己处理（留空），照常跑完。

## 结果提交

1. 每天一份特征表：`commander/results/TASK-004-features-<日期>-<你的 bot 用户名>.csv`
2. 一份汇总结果文件：`commander/results/TASK-004-<你的 bot 用户名>.md`，格式：

```
TASK-004 完成
<日期1>: 耗时秒 <real 秒数> | 产出md5 <csv 的 md5> | <当天脚本 JSON summary 原样粘贴>
<日期2>: 同上
备注: <无则写"无">
```

3. commit + push。某天报错不要改脚本，把报错原文写进备注对应行，继续跑其他天。
