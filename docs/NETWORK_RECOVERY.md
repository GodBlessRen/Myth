# 断网恢复

Myth 会保存原任务并等待连接恢复。Conversation 和 Goal 的后台推进使用原 `run_id`、冻结上下文、Execution Cursor、已完成工具及收据；浏览器连接断开不终止 Run。

连续失败后等待 **1、2、4、8、16、32、60 秒**，第七档起每分钟一次。间隔从上一次失败检查结束时开始计算；操作本身耗时和系统调度会影响实际时间。恢复并取得合法决定后清零；下一次断网从一秒开始。没有设置两小时的任务过期时间。

## 哪些情况可以自动继续

| 证据 | 处理 |
|---|---|
| 供应商就绪检查失败 | 保存等待；不签发模型 Ticket、不消费步骤预算 |
| 推理连接尚未建立，明确 DNS、拒连、无路由 | 发布零派发/零 token 收据；原子结算旧机会并释放当前请求键，到期重新准入 |
| 已有本地工具决定与固定授权范围 | 继续该本地步骤，保存真实收据；需要模型时再等待 |
| 已发送后的超时、连接重置、半截 SSE/JSON、没有完成收据 | `UNKNOWN / RECONCILE`；不自动重发 |
| 明确 401/403/429 等推理拒绝 | 保持已知失败，处理认证/额度/配置后再行动 |
| OAuth refresh 已派发但轮转结果不明 | 认证模块保持待核对/重新授权；重连不重放旧 refresh token |

`ProviderUnavailable` 只由传输层 `connect` 阶段的明确失败证据生成，固定三项零用量。仅有 URLError 类型或“尚未收到 response”不能证明未发送：发送/读取后的同名无路由错误仍是 UNKNOWN。传输继承标准库代理及 TLS 校验，不自动重定向。失败收据与原请求摘要绑定；原 Attempt 保留审计，自动继续仍需新预算准入/Ticket。`UNKNOWN` 的占用不通过连接探测释放。

## 持久等待与控制

- `workspace_network_retries` 保存每个 Run 的连续失败次数、离线开始时间、最近检查、UTC 下次检查时间及固定公开原因；不保存 token、请求头、异常正文。
- Goal 计划保存 `retry_failures/retry_at`，由当前 schema 明确创建。未到期的重复扫描不重复累加；准入成功重置计数。
- Run Driver Lease 避免并发接管，本机执行锁阻止重复驱动；到期时间先在 SQL 候选中筛除，等待队列不会挤占就绪工作的 LIMIT。
- 探测线程、worker/Driver 心跳、业务进度分别记录。重新探测不会刷新原 checkpoint 的进度时间；进程退出后由下一 worker 读取持久截止时间，不从一秒重新开始。
- Pause/Stop 是本地控制，不依赖远端恢复。Pause 保留等待现场；Resume 后继续尊重原截止时间；Stop 终止未来重连。
- 第三栏 Recovery 显示等待原因、失败次数、下次检查倒计时和当前间隔。浏览器只重读已有会话，不自动重发用户消息、控制命令或 OAuth 登录提交；首次加载失败也进入同一退避循环。其展示计时器在刷新页面后重建，服务端 Run 的等待不受影响。

运行常驻执行器的入口仍是 `myth --root <root> worker`，Web 启动时会确保它存在。此机制不安装操作系统服务：应用/机器关闭后无进程执行，重新启动后继续。Exact CLI 也会保留派发前断连的原 Run/step，但需要再次显式驱动，当前后台自动发现范围为 Conversation/Goal。

## 验证

`tests/test_network_recovery.py` 覆盖两小时虚拟时钟离线（超过一百次检查）、worker 重启、完整退避、工具结果复用、暂停/停止、队列公平、收据落盘后 `os._exit` 和真实 loopback HTTP 已接收后超时。`tests/test_reconnect_ui.cjs` 用同一前端控制器验证首次失败、所有间隔、恢复重置、单个在途读取和停止后的晚到响应。

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p test_network_recovery.py -v
node --test tests/test_reconnect_ui.cjs
```

两小时虚拟时钟回归证明持久状态和调度逻辑；它不是墙钟两小时浸泡，也不证明真实 GPT 的断网恢复或推理质量。当前 OpenAI 使用 `store=false`，丢失完成响应时没有可依赖的远端结果查询合同，必须保持 UNKNOWN。

当前执行结果见 [审查报告](REFINEMENT_REVIEW.md)，历史验证原件在垃圾站保留。
