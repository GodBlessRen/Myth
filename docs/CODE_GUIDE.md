# 代码阅读与修改指南

Myth 是共享 SQLite 的单机模块化应用。纯合同、策略和应用用例通过端口协作；文件、模型、认证、数据库和 HTTP 在适配器或装配入口处理。它有明确的职责边界，也仍有共享表与跨仓储事务的耦合，不能把目录分开当作完全解耦。

所有新代码遵守[宪法第 11 节](ARCHITECTURE_CONSTITUTION.md#11-简体中文指导性注释)：简体中文说明文件职责、类协作、函数前提、字段单位及关键事务/恢复步骤。`python scripts/check_annotations.py` 检查说明是否存在，准确性需要结合实现审阅。

## 按这个顺序读

| 阅读入口 | 负责什么 | 修改时首先核对 |
| --- | --- | --- |
| `domain.py`、`core/primitives.py`、`models.py` | 身份、状态、字节计划、请求/结果/决定合同 | 意图、机会、授权、效果、验收是不同事实；字段可变性与计量缺测语义 |
| `domains/`、`strategies/` | 同级领域与纯组织策略 | 路由/粒度/增益不授予权限；表示变了不能换来源；未知收益保持 None |
| `ports.py`、`conversation_ports.py` | 应用协作合同 | 调用方和实现方各自负责哪些状态；端口存在不代表实际后端可用 |
| `application/agent.py`、`application/conversation_agent.py` | Exact / Conversation 有界用例 | 安全点、已有决定消费、收据恢复和固定验收；不得取得 SQL/具体供应商 |
| `store.py`、`adapters/*_store.py`、`platform/*_store.py` | 持久状态所有者 | 哪些表同事务提交、版本如何分配、迟到结果是否覆盖新状态 |
| `decision_runtime.py`、`artifacts.py`、`adapters/*_execution.py` | 固定请求、外部效果、收据与核对 | Ticket 前拒绝、派发后 UNKNOWN、摘要核对、效果与用量分别结算 |
| `adapters/delegation.py`、`adapters/parallel_delegation.py`、`adapters/subagent_runtime.py`、`platform/handoff.py` | 委派合同、共享子引擎视图、交接投影 | 批次 Ticket 原子准入；私有线程连接、共享预算与作用域恢复；父 Ticket 先于子效果；完整正文/元数据与默认摘要分开；拒收费用与替代义务均保留 |
| `runtime.py`、`agent_runtime.py`、`workspace.py` | 装配与入口准入 | 依赖装配顺序、明确范围、初始业务事实是否完整提交 |
| `goal_scheduler.py`、`web_workspace.py` | 计划机会与本机 Driver 生命周期 | opportunity 去重、租约、物理锁、线程独立连接和停止后的晚到收据 |
| `providers/`、`auth/` | 供应商传输、独立 OAuth 和安全凭据 | 凭据不进 Runtime、网络超时不证明未执行、认证存储不是跨系统事务 |
| `web.py`、`webui/`、`cli.py` | 入站与产品投影 | Host/Origin、稳定请求身份、迟到响应 generation、第三栏事实完整性 |
| `evaluation_runner.py`、`task_benchmark.py`、`platform/evaluation*`、`platform/evolution*` | 固定测量、配对、发布资格与显式切换 | 完整分母、固定版本、真实字节 Oracle、partial 不发布、资格不自动 Promote |

## 一次 Conversation 的协作

1. Web/CLI 按明确设置装配 `Workspace`，个人状态仓储先于对话仓储创建。应用取得 Repository、Execution、Control、Memory 和 GoalCheckpoint 端口。
2. `SqliteWorkspaceRepository.create_turn` 在短事务里核对入口、Session/Goal 占有者，冻结上下文并保存 Run、预算、Turn、用户消息与游标。Goal 的校验和写入由 `SqlitePersonalState` 加入同连接事务。
3. `ConversationAgent.run` 取得共享本机 Run 锁。持久 Lease 标明负责人，OS 锁互斥实际驱动；两者不能互相替代。
4. 先核对旧机会，再复用已有决定或构造固定模型请求。有界上下文保留当前意图、澄清、附件及最新证据；Compact 按实际使用的控制版本消费。
5. 模型调用有独立 Intent/Ticket/Receipt。工具决定仍是提案，参数/范围通过本地校验才能获得工具 Ticket；供应商/文件效果发生在数据库事务外。
6. 先发布收据再结算并消费步骤。未知效果不重发；已知参数拒绝在 Ticket 前反馈给下一规划步骤。效果已确认也不意味着用量已测得。
7. 回答提交前保存 finalization 义务；回答结束后补齐经历 Memory 和 Goal checkpoint。各仓储分别提交，启动恢复根据义务和回答事实幂等补偿。Turn `COMPLETED`、长期 Goal 完成和语义验收通过分别判定。

## 原子性具体指什么

模型设置的公开价格由 [`adapters/model_catalog.py`](../src/myth/adapters/model_catalog.py) 查询固定目录；不接收凭据或任意 URL。Web 门面先验证配置、在事务外解析标价，再由工作区仓储保存；新 Turn 使用完整冻结设置。自动报价的价格/查询时间不属于用户请求身份，自定义合同费率仍属于身份；历史 Run、恢复与计划使用已有快照。视图选择器 [`webui/choices.js`](../src/myth/webui/choices.js) 只包装原字段，不拥有业务状态。

“原子组件”强调单一职责、明确输入输出和状态所有权；“原子提交”强调业务决定不能部分落库。文件短、函数少或使用 Protocol，都不能单独证明这两种性质。

| 操作 | 数据库事务内 | 数据库事务外 / 恢复 |
| --- | --- | --- |
| 新 Goal | Goal + 初始 work state | 返回投影；任何初始写入失败都回滚 |
| 新 Conversation | Run、账号、Turn、消息、游标；可包含 Goal 关联/进度 | 模型/工具尚未派发；冻结来源对象的读取会占用准入写锁 |
| 到期计划 | occurrence + Conversation admission + 下一 due/sequence + 事件 | provider 检查、Driver 派发在外；提交后接管原 Run，UNKNOWN 不自动继续 |
| 独立精确修改入口 | Run、账号、Action、Attempt、资源预留及初始事件 | 对象/私有基线先准备；DB 失败可留下未引用字节，它们没有 Ticket，不修改原项目 |
| 控制命令 | 命令/设置、Turn/Core、Goal checkpoint 与事件，所有者共用短事务 | 模型能力网络检查在外；提交 CAS；安全点重新读取，终态不可重开 |
| 模型 / 工具开始 | 唯一 Ticket、机会状态和事件 | 实际外部调用；超时或崩溃先核对 |
| 效果结算 | 收据事实、资源转移、事件 / 步骤状态 | 收据文件先发布；字节核对只证明效果，不补造用量 |
| 策略发布 | 活动指针与发布历史 | 固定完整评测先执行；明确发布才影响未来 Turn |
| OAuth | 不使用 Runtime 数据库保存凭据 | 系统秘钥库、无 token 元数据、远端交换/撤销分开；失败不能宣称整体事务成功 |

## 当前需要继续约束的耦合

- Control 命令、安全点与 Turn/Core/Goal 投影已通过所有者加入同一事务。模型能力检查在事务外执行，提交用控制 revision 核对检查基础；Core 栅栏独立递增。委派先签发父工具 Ticket，再调用子模型，恢复只消费持久子决定。
- 回答、Memory、Goal checkpoint 与 Driver 释放仍分别提交；持久 finalization 义务负责补偿，`last_run_id` 防止旧进度覆盖新工作。补偿不是跨系统事务。
- `SqliteWorkspaceRepository` 负责项目、会话、工具机会和恢复游标；知识已交给 `SqliteKnowledgeRepository`，通过共享连接保留文档/分片事务；`ConversationWebService` 同时负责 API 门面、Driver 和计划线程。下一次按真实改动压力拆职责，拆分时保留现有原子准入协调入口。
- 跨聚合 join、DDL 装配和外键共享同一个数据库。当前的直接 import 守卫与纯领域冷导入测试不证明所有传递依赖都可独立部署。
- 本机对象、收据和数据库不能一起提交；断电、外部服务幂等、跨进程认证退出/刷新与多周运行需要各自验证。未引用准备对象暂时保留，未来 GC 需要可靠的存活引用/在途机会判断。

## 改代码的最短验证路径

```powershell
python -m pip install -e .
python scripts/check_annotations.py
python -m compileall -q src tests scripts
python -m unittest discover -s tests -v
node --check src/myth/webui/app.js
node --check src/myth/webui/inspector.js
node --check src/myth/webui/goals.js
```

涉及预算、准入或恢复时，先固定故障窗口和完整期望，再运行 `test_state_boundaries.py`、对应竞争/真实子进程回归。不要把字符覆盖、静态 DOM、替身 PASS 或历史真实模型报告外推到未测场景。

当前固定集在 `evals/`，旧集、诊断和一次性画面在 `.trash/` 留档，不进入发布包。数据库只接受当前 `SCHEMA_VERSION`，DDL 逐句在事务内原子初始化，完整 schema 重开只读检查。此次处置与故障证据见 [REFINEMENT_REVIEW](REFINEMENT_REVIEW.md)。
