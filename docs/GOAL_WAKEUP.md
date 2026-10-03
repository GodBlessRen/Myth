# Goal 定时唤醒

Myth 服务运行时，可以让显式计划到期创建一个正常的工作轮次。计划持久化在 SQLite；Web 页面关闭不会取消计划，Web 服务关闭期间不执行。

## 工作台

1. 在「目标与计划」创建长期 Goal。
2. 选择已有工作会话；首次没有会话时，表单会创建一个独立工作会话。
3. 点击「安排工作」，选会话、任务、首次时间和重复间隔。
4. 当前模型/provider/窗口/步数/输出预算在保存时固定。修改全局模型设置影响未来创建的计划；已有计划继续使用自己的快照。
5. 到期的 Run 可以在「打开会话」查看、Steer、Pause、Resume、Stop；Runtime Goal 区显示计划来源和 due time。

一次性 Timer 成功 admission 后结束；固定间隔计划继续保留下一次 due time。暂停计划只阻止未来 admission，已开始的轮次在对话中管理。暂停 Goal 也阻止未来 admission。

## HTTP 合同

创建：`POST /api/workspace/goals/{goal_id}/schedules`。

```json
{
  "request_id": "caller-owned-stable-id",
  "session_id": "session_...",
  "prompt": "读取项目发布说明，生成有来源依据的检查报告。",
  "due_at": "2026-10-04T09:00:00+08:00",
  "interval_seconds": 86400
}
```

`due_at` 必须含时区，持久化为 UTC epoch；UI 输入和显示使用浏览器本地时区。`interval_seconds` 省略/null 表示仅一次；整数范围 60–31536000。固定秒数间隔不是时区感知 cron，跨夏令时不承诺保持同一个当地时刻。

`request_id` 固定入口意图，网络重试应使用同一个 ID。重复请求返回已有计划；改 prompt/Goal/session/time/settings 会冲突。旧客户端可以省略 ID，此时每次请求都是新计划。

读取：`GET /api/workspace/schedules`、`GET /api/workspace/goals/{goal_id}/schedules`。响应包括 enabled、下一次 due time、固定 settings、last_error、最近 20 次 Wakeup/Run/status。

启停：`POST /api/workspace/schedules/{schedule_id}/enabled`，body `{"enabled":false}`。已 firing 的一次性计划不能重新启用，请创建新的 Timer。

Goal 状态：`POST /api/workspace/goals/{goal_id}/state`，body `{"state":"PAUSED"}` 或 `ACTIVE`。

## 提交与恢复

```text
due schedule
  -> provider readiness（事务外）
  -> BEGIN IMMEDIATE
  -> validate Goal / Session / unfinished work
  -> immutable Turn snapshot + budgets
  -> occurrence + Run + Goal link + checkpoint + event
  -> COMMIT
  -> Driver Lease + normal Control / Ticket / Receipt
```

- admission 失败时事务整体回滚，sequence 和 due time 不消费。
- unavailable provider、忙会话、暂停/等待/阻塞 Goal 保留计划，按 1、2、4、8、16、32、60 秒退避，之后每分钟检查一次；次数与截止时间持久保存，原因可见。
- 同一个 Goal 跨会话也不能创建重叠未完成轮次。
- 同一机会只有一个 Run。两个连接争抢由 SQLite 写事务和 occurrence 主键串行化。
- commit 后、Driver 启动前进程退出，重启服务会找到原 Run 并恢复。
- 未确定结果保持 UNKNOWN；定时器不自动继续它，不创建一个新 Run 绕过核对。
- Driver 恢复仍使用 OS 单 Run 锁、Lease、原 Turn snapshot、原模型/工具收据。
- 错过多个重复时段时只创建一次工作机会，next due 推到未来，避免启动时补发一大批模型调用。
- 服务最多同时管理四个定时派发工作；手动对话沿用已有 Driver 合同。
- 已完成旧 Run 的迟到 Goal checkpoint 不能覆盖新 Run 的进度身份。

现有 `goal_triggers` 里的 cron/event/webhook/email 数据仍只是合同记录，不会自动成为 executable schedule。此实现没有系统常驻服务、分布式调度器或远端 webhook。

## 验证

```powershell
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -p test_v021_goal_scheduler.py -v
python -m unittest discover -s tests -p test_schedule_web.py -v
```

测试覆盖回滚、两连接竞争、commit 后 `os._exit`、服务重启、暂停、模型快照、入口去重、持久指数退避、正常 Driver/Control、UNKNOWN 不自动重放。断网边界见 [NETWORK_RECOVERY.md](NETWORK_RECOVERY.md)。
