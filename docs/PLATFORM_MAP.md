# 当前组件地图

内圈领域/策略与 Port 由外圈 SQLite、文件、模型、认证和 HTTP 装配。此页只列当前接入的路径，成熟度按实测证据解释，不用占位实现代表功能。

| 职责 | 当前入口 | 实际路径 |
| --- | --- | --- |
| 执行事实 | `runtime.py`、`store.py` | Run / Action / Attempt / Ticket / Receipt / Budget / Verification |
| 对话 | `application/conversation_agent.py` | 有界 Agent Loop、固定步骤、恢复游标 |
| 控制 | `platform/control_store.py` | Steer / Pause / Resume / Stop / Compact |
| 上下文 | `conversation_context.py`、`model_capabilities.py` | 供应商中立预算、来源投影与模型能力合同 |
| 知识 | `adapters/knowledge_store.py` | 正文、分片、作用域、词面检索；可选 Milvus 派生索引 |
| 记忆 | `platform/memory_store.py` | 类型、revision、来源、freshness、Mental Model 与 Knowledge Page |
| 长期状态 | `adapters/personal_store.py` | Goal 与显式个人状态 |
| 调度 | `goal_scheduler.py`、`durable_executor.py` | 持久 occurrence、原子准入、lease、同 Run 接管 |
| 交付 | `delivery.py` | 可补偿收尾、独立验收、并发工作项账本 |
| 观测 | `platform/observability.py`、`webui/inspector.js` | 第三栏持久事实投影 |
| 模型/认证 | `providers/`、`auth/` | Ollama、OpenAI、DeepSeek、Myth 自有 ChatGPT OAuth、系统凭据库 |
| 评测/演进 | `evaluation_runner.py`、`platform/evaluation*`、`platform/evolution*` | 固定集、Ledger、候选、显式 Promote/Rollback |
| 入站 | `cli.py`、`web.py`、`web_workspace.py` | CLI、本机 HTTP 和工作台 |

实际策略包括 conservative Intent Pick、Direct、Agent Loop、Information Resolution、离线 Information Gain、Personal Agent 与 `agent.delegate` 单层只读委派。调用发生时仍经过原有准入、预算和证据边界。

已移除无调用者的 Workflow/MCP/Skills 占位类、内存 MemoryCatalog、Kernel/ControlPlane 旧别名和虚假的 planned adapter 登记。当前没有任意 Shell、A2A、浏览器执行或通用远程 Managed Agent；后续需求见 [ROADMAP](ROADMAP.md)，不在快照中冒充连接。

修改入口见 [CODE_GUIDE](CODE_GUIDE.md)，本次逐文件处置见 [FILE_REVIEW](FILE_REVIEW.md)。
