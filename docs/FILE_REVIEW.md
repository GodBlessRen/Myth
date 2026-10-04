# 本轮逐文件处置

基线 `27462b2d70a775f3b4a597f9c7b9c010356c6fde` 的 234 个跟踪文件全部列入，包含宪法、开发规范、源码、前端、测试、配置、证据与垃圾站。方法：读取文件职责与结构、核对生产引用和发布归属；关键控制/预算/恢复路径进一步人工追踪并做 SQL、并发与进程故障验证。

“保留”表示有当前用途，不表示穷尽证明每行正确。长文件保留完整恢复职责；无调用者合同和重复入口才做删除。总体结论与实测见 [审查报告](REFINEMENT_REVIEW.md)。

| 基线文件 | 处置 | 判断 |
| --- | --- | --- |
| `.gitattributes` | 保留 | 保留当前构建、排除、启动或 CI 配置；已核对作用路径 |
| `.github/workflows/ci.yml` | 保留 | 保留当前构建、排除、启动或 CI 配置；已核对作用路径 |
| `.gitignore` | 保留 | 保留当前构建、排除、启动或 CI 配置；已核对作用路径 |
| `.trash/2026-10-04/AGENTS.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/README.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/ARCHITECTURE_CONSTITUTION.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/DELIVERY_WORKFLOW_V024.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/PLATFORM_MAP.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/SECURITY_PERFORMANCE_AUDIT.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/UI_REDESIGN.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/archive/ANNOTATION_AUDIT_V0211.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/archive/REVIEW_2026-10-03.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/archive/VALIDATION_HISTORY.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/archive/VALIDATION_V021.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/archive/tools/README.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/archive/tools/diagnose_v010.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/evidence/annotation-audit-v0211.json` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/docs/evidence/security-performance-2026-10-03.json` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/evals/archive/README.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/evals/archive/foundation-v1.json` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/evals/archive/foundation-v2.json` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/evals/archive/foundation-v3.json` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/src/myth/adapters/workspace_store.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/src/myth/platform/control.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/src/myth/platform/memory.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/src/myth/platform/memory_store.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/src/myth/sota_route.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/tests/test_conversation_context.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/tests/test_network_recovery.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/tests/test_platform_skeleton.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/tests/test_session_statistics.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/tests/test_v017_provider_context.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/removed-code/tests/test_v021_goal_scheduler.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/src/myth/platform/kernel.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/src/myth/platform/mcp.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/src/myth/platform/skills.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/src/myth/platform/workflow.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/2026-10-04/src/myth/providers/capabilities.py` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `.trash/README.md` | 归档保留 | 开发留档：恢复/比对原件；不参与 import、检索与发布 |
| `AGENTS.md` | 调整 | 保留最高原则，补充控制/委派故障回归要求 |
| `CHANGELOG.md` | 调整 | 保留有效说明：Changelog |
| `MANIFEST.in` | 保留 | 保留当前构建、排除、启动或 CI 配置；已核对作用路径 |
| `PRODUCT.md` | 调整 | 保留产品事实，清除只适用上一轮 UI 重构的临时限制措辞 |
| `README.md` | 调整 | 保留有效说明：Myth |
| `SECURITY.md` | 调整 | 重写中文当前安全合同，纠正 test.run/worker 与环境配置说明 |
| `docs/ARCHITECTURE.md` | 调整 | 重写为当前关系/所有权地图，专题按需链接，原件归档 |
| `docs/ARCHITECTURE_CONSTITUTION.md` | 调整 | 保留最高原则，增加同连接控制原子性与父子准入顺序 |
| `docs/CODE_GUIDE.md` | 调整 | 保留有效说明：代码阅读与修改指南 |
| `docs/DELIVERY.md` | 保留 | 保留有效说明：当前交付与验证合同 |
| `docs/DESIGN.md` | 保留 | 保留有效说明：Myth 界面设计 |
| `docs/FILE_REVIEW.md` | 保留 | 替换为本轮逐文件处置表，旧表留档 |
| `docs/GOAL_WAKEUP.md` | 调整 | 保留有效说明：Goal 定时唤醒 |
| `docs/LONG_RUN_VALIDATION.md` | 保留 | 保留有效说明：Long-run Validation / 长任务耐久验证 |
| `docs/MEMORY_LIFECYCLE.md` | 保留 | 保留有效说明：Memory Lifecycle |
| `docs/MILVUS_RETRIEVAL.md` | 保留 | 保留有效说明：Milvus Retrieval Adapter |
| `docs/NETWORK_RECOVERY.md` | 调整 | 保留有效说明：断网恢复 |
| `docs/OBSERVABILITY.md` | 保留 | 保留有效说明：Runtime Observatory Contract |
| `docs/PLATFORM_MAP.md` | 保留 | 保留有效说明：当前组件地图 |
| `docs/README.md` | 保留 | 保留有效说明：Myth Documentation |
| `docs/REFINEMENT_REVIEW.md` | 调整 | 替换为本轮基线与真实故障/验证，上一轮完整留档 |
| `docs/ROADMAP.md` | 调整 | 重写：真实任务、连续自用、成本实测、按压力拆职责；删除已完成计划 |
| `docs/SESSION_STATISTICS.md` | 保留 | 保留有效说明：会话统计 |
| `docs/SOTA_ROUTE.md` | 保留 | 保留有效说明：Myth v0.25 — SOTA Route |
| `docs/TASK_BENCHMARK.md` | 保留 | 保留有效说明：固定日常任务基线 |
| `docs/VALIDATION.md` | 调整 | 重写验证入口，连接实际命令、故障测试与证据边界 |
| `docs/evidence/daily-v1-before.json` | 保留 | 固定历史对照数据：用于同任务比较，不作为当前版本通过记录 |
| `docs/evidence/daily-v1-v021.json` | 保留 | 固定历史对照数据：用于同任务比较，不作为当前版本通过记录 |
| `docs/evidence/refinement-2026-10-04.json` | 移入垃圾站 | 移入垃圾站，上一轮证据不充当当前结果 |
| `evals/daily-v1.json` | 保留 | 保留当前完整固定评测集合及明确分母 |
| `evals/foundation-v4.json` | 保留 | 保留当前完整固定评测集合及明确分母 |
| `examples/acceptance.json` | 保留 | 保留最小可运行输入，供 Exact/CLI 示例和验收复现 |
| `examples/example.txt` | 保留 | 保留最小可运行输入，供 Exact/CLI 示例和验收复现 |
| `pyproject.toml` | 调整 | 当前包配置与依赖；版本同步 0.24.1，构建后验证实际资源 |
| `scripts/audit_secret_patterns.py` | 保留 | 已知秘钥格式的本地审计，不打印匹配值 |
| `scripts/benchmark_local_overhead.py` | 保留 | 固定本机开销对照，不访问真实模型或读取用户项目 |
| `scripts/check_annotations.py` | 保留 | 项目宪法的中文说明覆盖守卫 |
| `scripts/soak_long_run.py` | 保留 | 长任务 Durable Executor 浸泡/故障注入工具 |
| `scripts/validate_os_credentials.py` | 保留 | 系统凭据库容量/轮转/清理 smoke |
| `scripts/validate_package.py` | 保留 | 在隔离根核对真实安装 wheel、HTTP 静态资源和计划 API |
| `scripts/validate_release.py` | 保留 | 核对真实发布归档：垃圾站、运行数据和淘汰入口不得随 wheel/sdist/源码 ZIP 交付 |
| `src/myth/__init__.py` | 调整 | 公开 Runtime/组件入口与按需导出 |
| `src/myth/acceptance.py` | 调整 | 精简：删除无调用者帮助函数和导入，保留真实证据检查 |
| `src/myth/adapters/__init__.py` | 保留 | 具体 I/O 与状态仓储适配器包入口 |
| `src/myth/adapters/agent_execution.py` | 保留 | Exact Agent 的本机执行适配器 |
| `src/myth/adapters/agent_store.py` | 调整 | 调整：缺失固定验收合同明确报错，禁止空规则替代 |
| `src/myth/adapters/conversation_execution.py` | 调整 | 调整：先准入委派工具、持久子结果恢复、共享收据发布，知识 SQL 回仓储 |
| `src/myth/adapters/driver_lock.py` | 保留 | Exact Agent 与 Conversation 共用的本机 Driver 锁 |
| `src/myth/adapters/knowledge_store.py` | 调整 | 调整：拥有分片分页 SQL 和游标边界 |
| `src/myth/adapters/milvus_retrieval.py` | 保留 | Milvus 向量检索适配器 |
| `src/myth/adapters/personal_store.py` | 调整 | 调整：移除静默补造进度，checkpoint 可加入既有事务 |
| `src/myth/adapters/workspace_store.py` | 调整 | 调整：拥有 Turn 控制投影并协调 Core/Goal，同连接短事务 |
| `src/myth/agent_runtime.py` | 保留 | Exact Agent 的公开装配入口 |
| `src/myth/application/__init__.py` | 保留 | 纯应用用例包入口 |
| `src/myth/application/agent.py` | 保留 | Exact Agent 的有界应用用例 |
| `src/myth/application/conversation_agent.py` | 保留 | Conversation 与长期 Goal 的应用循环 |
| `src/myth/artifacts.py` | 保留 | 不可变对象、受管文件和收据日志的文件系统适配器 |
| `src/myth/auth/__init__.py` | 保留 | 本应用独立认证包入口 |
| `src/myth/auth/chatgpt.py` | 保留 | Myth 自有 ChatGPT OAuth 的认证适配器 |
| `src/myth/auth/provider_keys.py` | 保留 | 远端模型 API Key 的应用内安全凭据中心 |
| `src/myth/auth/transport.py` | 保留 | 认证外圈的受限 HTTP 传输 |
| `src/myth/cli.py` | 保留 | 命令行装配入口 |
| `src/myth/conversation.py` | 调整 | 精简：删除重复排序和 knowledge.read，统一工具参数与提示 |
| `src/myth/conversation_context.py` | 保留 | 从持久对话事实生成有预算的模型上下文 |
| `src/myth/conversation_ports.py` | 保留 | 对话用例的仓储、执行、控制、记忆和 Goal checkpoint 合同 |
| `src/myth/core/__init__.py` | 保留 | 最小核心合同的公开导出 |
| `src/myth/core/primitives.py` | 保留 | 长期 Goal 的最小不可变合同 |
| `src/myth/decision_runtime.py` | 调整 | 提取：已有决定读取/恢复共用入口，不给恢复流程 Provider |
| `src/myth/delivery.py` | 保留 | Conversation 交付账本：终态收尾、验收、工作项和人工关注 |
| `src/myth/demo.py` | 保留 | 可重复的本地精确替换演示工厂 |
| `src/myth/domain.py` | 调整 | 精简：删除未使用异常/结果类型，保留当前事实合同 |
| `src/myth/domains/__init__.py` | 保留 | 同级纯领域合同包入口 |
| `src/myth/domains/coordination.py` | 保留 | 组织工作方式的纯策略合同与登记表 |
| `src/myth/domains/information.py` | 保留 | Intent 与信息分辨率/增量/增益的纯数据合同 |
| `src/myth/domains/intent.py` | 保留 | Intent Pick 的纯协议 |
| `src/myth/domains/personal.py` | 保留 | 个人 Trigger 的纯合同 |
| `src/myth/durable_executor.py` | 保留 | 独立常驻 Durable Executor |
| `src/myth/evaluation_runner.py` | 调整 | Foundation 固定版本评测的本机运行器 |
| `src/myth/failures.py` | 保留 | 把已知失败标准化为模型可恢复、UI 可观测的数据 |
| `src/myth/goal_scheduler.py` | 调整 | 显式一次性/固定间隔 Goal 计划的本地调度适配器 |
| `src/myth/mental_model_refresh.py` | 保留 | Mental Model 自动刷新调度与持久工作协调 |
| `src/myth/model_capabilities.py` | 保留 | 模型能力目录的供应商无关投影 |
| `src/myth/models.py` | 保留 | 供应商无关的模型请求、结果与决策合同 |
| `src/myth/network_recovery.py` | 保留 | 断连恢复的纯规则 |
| `src/myth/platform/__init__.py` | 保留 | 横向能力合同与目录的公开导出 |
| `src/myth/platform/calibration.py` | 保留 | 配对增益证据的纯校准矩阵 |
| `src/myth/platform/capabilities.py` | 调整 | 能力描述和执行白名单的纯注册表 |
| `src/myth/platform/completion.py` | 保留 | Conversation 的 Verify-on-Stop 纯策略 |
| `src/myth/platform/components.py` | 保留 | 产品组件与架构地图的装配登记 |
| `src/myth/platform/context.py` | 保留 | 小型组件上下文的纯预算投影器 |
| `src/myth/platform/context_anchor.py` | 保留 | 可持久的增量 Context Anchor |
| `src/myth/platform/contracts.py` | 保留 | 组件成熟度与职责的纯描述合同 |
| `src/myth/platform/control.py` | 调整 | 控制命令的纯状态转换规则 |
| `src/myth/platform/control_store.py` | 调整 | 重写：仅拥有控制表，命令/安全点同事务委托状态所有者，CAS 与自身版本响应 |
| `src/myth/platform/cost_model.py` | 保留 | 显式成本权重合同及 SQLite 版本目录 |
| `src/myth/platform/evaluation.py` | 保留 | 固定评测集、观测、配对比较与发布门槛合同 |
| `src/myth/platform/evaluation_store.py` | 保留 | 评测运行和逐题观测的 SQLite 证据账本 |
| `src/myth/platform/evolution.py` | 保留 | 策略候选及人工发布决定的纯合同 |
| `src/myth/platform/evolution_store.py` | 保留 | 候选、证据、活动策略与发布历史的 SQLite 所有者 |
| `src/myth/platform/knowledge_views.py` | 调整 | Mental Model 与 Knowledge Page 的持久派生视图 |
| `src/myth/platform/memory.py` | 保留 | Memory 的用途分类 |
| `src/myth/platform/memory_lifecycle.py` | 保留 | Memory 生命周期的纯规则模块 |
| `src/myth/platform/memory_store.py` | 调整 | 生产记忆的持久 SQLite 适配器 |
| `src/myth/platform/observability.py` | 保留 | 事件事实的纯轨迹投影 |
| `src/myth/platform/replay.py` | 保留 | 历史 Replay World：把同一冻结条件下已发生的 SOTA Route 合并为可重放的已实现搜索空间 |
| `src/myth/platform/retrieval.py` | 保留 | 检索后端可用性与模式的纯路由合同 |
| `src/myth/platform/subagents.py` | 保留 | 子 Agent 的隔离执行合同与预算分配原语 |
| `src/myth/platform/tool_discovery.py` | 调整 | Conversation Tool 的渐进披露纯函数 |
| `src/myth/ports.py` | 调整 | 精简：仅保留 Exact 当前使用的两个端口，15 个空合同归档 |
| `src/myth/providers/__init__.py` | 保留 | 统一供应商适配器导出 |
| `src/myth/providers/base.py` | 保留 | 模型 I/O 的结构化端口 |
| `src/myth/providers/deepseek.py` | 保留 | DeepSeek Responses API 传输适配器 |
| `src/myth/providers/ollama.py` | 保留 | 本机 Ollama HTTP 适配器 |
| `src/myth/providers/openai.py` | 保留 | OpenAI Responses 与 ChatGPT 计划的传输适配器 |
| `src/myth/providers/scripted.py` | 保留 | 确定性的模型替身 |
| `src/myth/runtime.py` | 保留 | 受管精确文件任务的装配与执行协调入口 |
| `src/myth/session_statistics.py` | 保留 | Observability 的会话统计纯投影 |
| `src/myth/sota_route.py` | 保留 | SOTA Route：从已验收成功 Run 中学习更省的可观察执行路径 |
| `src/myth/store.py` | 调整 | 调整：事务加入规则通用命名、Core 自主维护状态与单调栅栏 |
| `src/myth/strategies/__init__.py` | 保留 | 可替换纯组织策略的公开导出 |
| `src/myth/strategies/information_control.py` | 调整 | 实时信息获取的纯准入策略 |
| `src/myth/strategies/information_gain.py` | 保留 | 配对固定评测证据的边际增益估计策略 |
| `src/myth/strategies/information_resolution.py` | 保留 | 同源信息 L0/L1/L2 的纯选择策略 |
| `src/myth/strategies/intent_pick.py` | 保留 | 保守 Intent Pick 的纯规则策略 |
| `src/myth/task_benchmark.py` | 调整 | 固定日常任务的真实 Workspace 运行器与独立小型 oracle |
| `src/myth/verification.py` | 保留 | 受限项目测试 profile |
| `src/myth/web.py` | 保留 | 本机 HTTP 入站与 Exact Agent 服务装配 |
| `src/myth/web_workspace.py` | 调整 | 调整：移除分离 Goal 后提交、旧 cancel 别名，模型预检带 revision |
| `src/myth/webui/app.css` | 保留 | 保留中文工作台静态资源及状态/交互投影，第三栏合同继续验证 |
| `src/myth/webui/app.js` | 保留 | 保留中文工作台静态资源及状态/交互投影，第三栏合同继续验证 |
| `src/myth/webui/favicon.svg` | 保留 | 保留中文工作台静态资源及状态/交互投影，第三栏合同继续验证 |
| `src/myth/webui/goals.js` | 保留 | 保留中文工作台静态资源及状态/交互投影，第三栏合同继续验证 |
| `src/myth/webui/index.html` | 保留 | 保留中文工作台静态资源及状态/交互投影，第三栏合同继续验证 |
| `src/myth/webui/inspector.js` | 保留 | 保留中文工作台静态资源及状态/交互投影，第三栏合同继续验证 |
| `src/myth/webui/reconnect.js` | 保留 | 保留中文工作台静态资源及状态/交互投影，第三栏合同继续验证 |
| `src/myth/webui/statistics.js` | 保留 | 保留中文工作台静态资源及状态/交互投影，第三栏合同继续验证 |
| `src/myth/webui/theme.js` | 保留 | 保留中文工作台静态资源及状态/交互投影，第三栏合同继续验证 |
| `src/myth/workspace.py` | 调整 | 精简：删除视图旧别名，保留装配与调用边界 |
| `start-myth.ps1` | 保留 | 保留当前构建、排除、启动或 CI 配置；已核对作用路径 |
| `tests/check_workspace_browser.cjs` | 保留 | 保留当前 UI/HTTP/生命周期测试或专用夹具；版本名不是删除依据 |
| `tests/test_agent_runtime.py` | 调整 | 回归边界：Exact Agent 端口装配与固定文件范围 |
| `tests/test_architecture.py` | 保留 | 回归边界：纯模块依赖方向 |
| `tests/test_context_eval_integration.py` | 保留 | Context、Capability、Recovery、Evaluation 与 Acceptance 的固定回归 |
| `tests/test_control_tower.py` | 调整 | 回归边界：持久控制、记忆与受限项目工具 |
| `tests/test_conversation_context.py` | 保留 | 回归边界：有界上下文与 Compact revision 消费 |
| `tests/test_decision_runtime.py` | 保留 | 回归边界：模型准入、收据和决定绑定 |
| `tests/test_delivery_workflow.py` | 调整 | v0.24 交付闭环：终态补偿、验收、工作项、人工关注与受限测试 profile |
| `tests/test_domain.py` | 保留 | 回归边界：纯字节替换规则 |
| `tests/test_durable_executor.py` | 保留 | 回归边界：独立 Durable Executor、同 Run 恢复与无进展观测 |
| `tests/test_execution_graph.py` | 保留 | Execution Graph 只读投影测试 |
| `tests/test_harness_deepening.py` | 保留 | Harness Engineering 四项深化的回归边界 |
| `tests/test_information_semantics.py` | 保留 | 回归边界：信息粒度、变化、增益和授权语义 |
| `tests/test_knowledge_views.py` | 保留 | 回归边界：Mental Model 是 materialized Memory view，Knowledge Page 只拥有树结构 |
| `tests/test_long_run_soak.py` | 保留 | 回归边界：长任务浸泡工具的健康路径与 UNKNOWN no-replay |
| `tests/test_memory_lifecycle.py` | 保留 | 回归边界：Evidence-backed Memory、immutable revision、freshness 与受约束 Delta |
| `tests/test_mental_model_auto_refresh.py` | 调整 | 回归边界：Mental Model 自动后台 Refresh 复用 Core Run / DecisionRuntime / DurableExecutor |
| `tests/test_milvus_retrieval.py` | 调整 | 回归边界：Milvus 派生索引、Hybrid hydration 与 Memory 渐进披露 |
| `tests/test_models.py` | 保留 | 回归边界：统一模型决定解析 |
| `tests/test_network_recovery.py` | 保留 | 断网恢复的故障注入回归 |
| `tests/test_observatory_ui.cjs` | 保留 | 保留当前 UI/HTTP/生命周期测试或专用夹具；版本名不是删除依据 |
| `tests/test_personal_agent_foundation.py` | 保留 | 回归边界：长期意图和描述性 Trigger |
| `tests/test_platform_skeleton.py` | 保留 | 回归边界：组合能力合同与成熟度 |
| `tests/test_platform_web.py` | 保留 | 回归边界：组件架构投影 |
| `tests/test_process_crash.py` | 保留 | 回归边界：真实子进程硬退出窗口 |
| `tests/test_provider_keys.py` | 调整 | 回归边界：应用内 Provider API Key 安全存储与显式进程环境配置 |
| `tests/test_providers.py` | 保留 | 回归边界：固定供应商传输夹具 |
| `tests/test_reconnect_ui.cjs` | 保留 | 保留当前 UI/HTTP/生命周期测试或专用夹具；版本名不是删除依据 |
| `tests/test_refinement.py` | 保留 | 沉淀期回归：schema 初始化、步骤消费和评测资格必须保持真实、原子、可重试 |
| `tests/test_replay_world.py` | 保留 | Replay World 回归：历史只覆盖已发生分支，候选策略不能从离线重放获得线上发布权限 |
| `tests/test_runtime.py` | 保留 | 回归边界：精确文件效果、预算与恢复 |
| `tests/test_schedule_web.py` | 保留 | 回归边界：本机计划 HTTP 与后台生命周期 |
| `tests/test_security_performance.py` | 保留 | 安全反例和延迟边界回归 |
| `tests/test_session_statistics.py` | 调整 | 会话统计的计量、持久恢复与本机 HTTP 回归 |
| `tests/test_sota_route.py` | 保留 | SOTA Route 回归：只从已验收成功 Run 学习同条件下更省的可观察路径 |
| `tests/test_state_boundaries.py` | 调整 | 回归边界：个人状态所有权与真实 SQL 故障回滚 |
| `tests/test_statistics_ui.cjs` | 保留 | 保留当前 UI/HTTP/生命周期测试或专用夹具；版本名不是删除依据 |
| `tests/test_task_benchmark.py` | 保留 | 回归边界：固定任务 Harness 及独立验收 |
| `tests/test_v011_runtime_closure.py` | 调整 | 回归边界：Control 竞争、Goal 准入和作用域 |
| `tests/test_v012_retrieval_eval.py` | 保留 | 回归边界：全候选召回与历史固定评测 |
| `tests/test_v013_eval_routing.py` | 保留 | 回归边界：固定知识路由和历史评测执行 |
| `tests/test_v014_information_gain.py` | 保留 | 回归边界：同题配对增益与成本语义 |
| `tests/test_v015_evolution_control_plane.py` | 保留 | 回归边界：策略发布资格、版本固定与显式回退 |
| `tests/test_v016_intent_correctness.py` | 保留 | 回归边界：算术/知识路由反例 |
| `tests/test_v017_provider_context.py` | 调整 | 回归边界：当前供应商窗口、温度和推理设置校验 |
| `tests/test_v0181_cache_observability.py` | 保留 | 回归边界：实际缓存计量与缺测显示 |
| `tests/test_v018_goal_work_loop.py` | 调整 | 回归边界：跨会话/重启长期进度 |
| `tests/test_v019_native_oauth.py` | 保留 | 回归边界：独立 OAuth 边界与安全存储 |
| `tests/test_v020_recovery_runtime.py` | 保留 | 回归边界：持久游标、Driver Lease 与安全接管 |
| `tests/test_v021_goal_scheduler.py` | 保留 | 回归边界：计划机会原子准入及恢复 |
| `tests/test_verified_agent.py` | 保留 | 回归边界：独立固定验收与 Agent 崩溃窗口 |
| `tests/test_web.py` | 保留 | 回归边界：包资源、HTTP 绑定与第三栏 DOM |
| `tests/test_web_contract.py` | 保留 | 回归边界：真实本机 HTTP 合同、入口去重及跨站拒绝 |
| `tests/test_workspace.py` | 保留 | 回归边界：对话、资料、受管产物和实际恢复 |
| `tests/test_workspace_interactions_ui.cjs` | 保留 | 保留当前 UI/HTTP/生命周期测试或专用夹具；版本名不是删除依据 |
| `tests/ui_fixture_server.py` | 保留 | 浏览器回归专用 loopback 服务 |

## 本轮新增

| 文件 | 处置 | 判断 |
| --- | --- | --- |
| `.trash/2026-10-04/deepening/README.md` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/acceptance.py` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/adapters/conversation_execution.py` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/adapters/conversation_execution.py.knowledge-read.txt` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/conversation.py` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/conversation.py.knowledge-read.txt` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/domain.py` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/platform/capabilities.py.knowledge-read.txt` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/platform/memory_store.py` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/platform/tool_discovery.py.knowledge-read.txt` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/ports.py` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/strategies/information_control.py.knowledge-read.txt` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-04/deepening/removed-code/src/myth/workspace.py` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/README.md` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/SECURITY.md` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/docs/ARCHITECTURE.md` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/docs/FILE_REVIEW.md` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/docs/NETWORK_RECOVERY.md` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/docs/REFINEMENT_REVIEW.md` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/docs/ROADMAP.md` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/docs/VALIDATION.md` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/docs/evidence/refinement-2026-10-04.json` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/replaced-source/src/myth/adapters/agent_store.py` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/replaced-source/src/myth/adapters/personal_store.py` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `.trash/2026-10-05/deepening/replaced-source/src/myth/platform/control_store.py` | 新增归档 | 基线原件/删除片段及理由；发布排除 |
| `docs/evidence/deepening-2026-10-05.json` | 新增 | 本轮固定基线、十项原版故障、源文件度量与真实验证结果 |
| `tests/test_control_atomicity.py` | 新增 | 控制命令的真实 SQLite 故障窗口 |
| `tests/test_delegation_boundaries.py` | 新增 | 委派准入与双层收据回归 |
