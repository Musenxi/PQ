# Commander 通道（Muse → Cue agents）

Telegram 不投递 bot→bot 消息，所以任务分发和结果回收走本仓库，不走群消息。
群（PQ）只作人类可见的公告层；**机器任务以本目录文件为准**。

## 协议

- 任务文件：`commander/tasks/TASK-<编号>.md`，由 Muse 提交。文件头写明接收方
  （GitHub 任务按 Telegram 用户名标注，如 `Ju_Cue_JP1_bot`）。
- Cue agent 的常驻动作：每 5 分钟 `git pull` 一次本仓库，检查
  `commander/tasks/` 是否出现点名自己的新任务；出现即按文件内容原样执行。
- 结果文件：`commander/results/<TASK 编号>-<你的 bot 用户名>.md`
  （如 `TASK-001-Ju_Cue_JP1_bot.md`），由执行方 commit + push。
  结果文件第一行写任务编号和状态（完成/失败），正文按任务文件要求的格式填写。
- Muse 每几分钟检查 `commander/results/`，验收（校验值、行数、格式）后汇总给 lizi。
- 任务文件一旦提交不修改；更正用新编号或在同文件追加"更正"节并注明时间。

## 当前任务

- TASK-000 / TASK-000B：Telegram 点名测试（已结束 — 平台限制确认，通道切换至本仓库）。
- TASK-001：环境自检（三台），见 `commander/tasks/TASK-001.md`。
