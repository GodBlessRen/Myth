# 下一阶段建设顺序

主线：让一个人跨日、跨会话、重启后继续完成真实工作，并用交付证据判断是否有效。当前已具备 Goal/Turn、恢复游标与租约、UNKNOWN 核对、独立 worker、受信测试 profile、Delivery 验收和 SOTA Route 账本；这些能力的存在不等于长期可靠性已经得到证明。

## 1. 用真实失败驱动改进

完整运行 `evals/daily-v1.json`，每题至少三次，保留 simple-loop 对照。固定模型、任务、工具与验收条件，保存全部失败和产物字节校验。按 Model / Context / Tool / Provider / Runtime / Product workflow 分类。

先修重复读取、无必要询问、忽略 Goal 进度、错误工具参数、完成自述与产物不符。验收：同题复跑改善且其他题不退化，人工接管与成本均有原始记录，不改题刷分。

## 2. 验证跨日使用和中断恢复

连续自用 2–4 周，覆盖模型断连、进程退出、长期 Pause、重复到期、未知调用核对、晚到结果。每个案例保留同一 `run_id`、Ticket/Receipt、预算与交付状态。

验收：恢复不重复副作用、不遗失持久进度；未解决的 UNKNOWN 明确等待；人工介入有记录。真实 provider 在途断开要单独测，不能由调用前拒连或固定脚本替代。

## 3. 只优化测得的成本

用相同任务比较 provider-visible Context、实测 token、模型/工具次数、耗时和 accepted outcome。Context 压缩同时核算预付成本、回读往返和缓存损失；SOTA Route 同时报 trajectory variance，检查能否稳定复现已验收的较省路线。

验收：one-mechanism / leave-one-out 在 discovery 集中解释差异，独立 held-out final 守住能力下限。Historical Replay 的未观察分支不计为成功；参数通过后显式 Promote。

## 4. 按改动压力继续拆职责

优先观察 Workspace 仓储与 Web 服务的修改交叉。若计划生命周期、Driver 或项目管理反复相互牵连，再沿现有所有权拆开。每次拆分保留同连接准入、原问题身份、稳定请求键和收尾补偿，并用故障测试验证。

无使用场景不新增 Protocol、Layer 或适配器登记。远端执行、多用户、分布式 worker、Webhook/Email、OS 服务安装和复杂多 Agent 编排等到明确需求出现。

## 每次变更的完成条件

当前源码、注释、架构说明与工具目录一致；淘汰内容进入 `.trash/<日期>/` 并注明替代入口；[验证与发布检查](VALIDATION.md)通过；结论注明版本、输入和证据范围。
