# 逐文件处置记录

基线 `c0446dd` 的 253 个跟踪文件逐项列出；新增文件补列在表尾。源码核对职责、导入/引用和状态路径；重点改动有具体故障回归。图片属于历史设计证据，本次按生命周期留档，没有重新宣称它们通过当前 UI 验收。

“保留”表示未发现有证据支持删除/重写的收益，不表示所有行为已被穷尽证明。退休原件位于 `.trash/2026-10-04/<原路径>`；生产代码和发布包不使用它们。

| 原路径 / 新入口 | 判断 | 职责与理由 |
| --- | --- | --- |
| `.github/workflows/ci.yml` | 修改并保留 | .github/workflows/ci.yml；保留四平台回归，补全 35 项前端行为与真实构建/安装后 HTTP 检查。 |
| `.gitignore` | 修改并保留 | .gitignore；一次性 output 不再反复提交为生产文件。 |
| `AGENTS.md` | 修改并保留 | Myth 开发规范；压缩重复原则，固定当前修改、中文说明、淘汰、验证和发布流程。 |
| `CHANGELOG.md` | 修改并保留 | Changelog；同步当前事实/导航，职责仍成立。 |
| `PRODUCT.md` | 保留 | Myth 产品事实；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `README.md` | 修改并保留 | Myth；同步当前事实/导航，职责仍成立。 |
| `SECURITY.md` | 保留 | Security & Privacy Boundary；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/ARCHITECTURE.md` | 修改并保留 | Myth Architecture；同步当前事实/导航，职责仍成立。 |
| `docs/ARCHITECTURE_CONSTITUTION.md` | 修改并保留 | Myth 架构宪法；重写为当前可执行边界，保留安全/来源/UNKNOWN/独立验收，删旧兼容与未来清单。 |
| `docs/CODE_GUIDE.md` | 修改并保留 | 代码阅读与修改指南；知识所有权、持久 finalization、schema 和当前验证入口同步实现。 |
| `docs/DELIVERY_WORKFLOW_V024.md` | 移出生产树 | 阶段模拟计划已完成的部分改为当前 DELIVERY.md，旧设计留档。 |
| `docs/DESIGN.md` | 修改并保留 | Myth 界面设计；同步当前事实/导航，职责仍成立。 |
| `docs/GOAL_WAKEUP.md` | 保留 | Goal 定时唤醒；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/LONG_RUN_VALIDATION.md` | 保留 | Long-run Validation / 长任务耐久验证；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/MEMORY_LIFECYCLE.md` | 保留 | Memory Lifecycle；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/MILVUS_RETRIEVAL.md` | 保留 | Milvus Retrieval Adapter；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/NETWORK_RECOVERY.md` | 修改并保留 | 断网恢复；同步当前事实/导航，职责仍成立。 |
| `docs/OBSERVABILITY.md` | 保留 | Runtime Observatory Contract；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/PLATFORM_MAP.md` | 修改并保留 | 当前组件地图；只列实际装配，修正定时器和只读委派状态，删除占位成熟度。 |
| `docs/README.md` | 修改并保留 | Myth Documentation；同步当前事实/导航，职责仍成立。 |
| `docs/ROADMAP.md` | 修改并保留 | Myth Roadmap；同步当前事实/导航，职责仍成立。 |
| `docs/SECURITY_PERFORMANCE_AUDIT.md` | 移出生产树 | 历史诊断/过期版本证据，移出当前架构导航与发布内容。 |
| `docs/SESSION_STATISTICS.md` | 保留 | 会话统计；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/SOTA_ROUTE.md` | 保留 | Myth v0.25 — SOTA Route；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/TASK_BENCHMARK.md` | 保留 | 固定日常任务基线；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/UI_REDESIGN.md` | 移出生产树 | 历史诊断/过期版本证据，移出当前架构导航与发布内容。 |
| `docs/VALIDATION.md` | 修改并保留 | Validation；同步当前事实/导航，职责仍成立。 |
| `docs/archive/ANNOTATION_AUDIT_V0211.md` | 移出生产树 | 历史诊断/过期版本证据，移出当前架构导航与发布内容。 |
| `docs/archive/REVIEW_2026-10-03.md` | 移出生产树 | 历史诊断/过期版本证据，移出当前架构导航与发布内容。 |
| `docs/archive/VALIDATION_HISTORY.md` | 移出生产树 | 历史诊断/过期版本证据，移出当前架构导航与发布内容。 |
| `docs/archive/VALIDATION_V021.md` | 移出生产树 | 历史诊断/过期版本证据，移出当前架构导航与发布内容。 |
| `docs/archive/tools/README.md` | 移出生产树 | 历史诊断/过期版本证据，移出当前架构导航与发布内容。 |
| `docs/archive/tools/diagnose_v010.py` | 移出生产树 | 历史诊断/过期版本证据，移出当前架构导航与发布内容。 |
| `docs/evidence/annotation-audit-v0211.json` | 移出生产树 | 历史诊断/过期版本证据，移出当前架构导航与发布内容。 |
| `docs/evidence/daily-v1-before.json` | 保留 | docs/evidence/daily-v1-before.json；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/evidence/daily-v1-v021.json` | 保留 | docs/evidence/daily-v1-v021.json；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `docs/evidence/security-performance-2026-10-03.json` | 移出生产树 | 历史诊断/过期版本证据，移出当前架构导航与发布内容。 |
| `evals/archive/README.md` | 移出生产树 | 旧固定集；活跃回归统一当前 foundation-v4。 |
| `evals/archive/foundation-v1.json` | 移出生产树 | 旧固定集；活跃回归统一当前 foundation-v4。 |
| `evals/archive/foundation-v2.json` | 移出生产树 | 旧固定集；活跃回归统一当前 foundation-v4。 |
| `evals/archive/foundation-v3.json` | 移出生产树 | 旧固定集；活跃回归统一当前 foundation-v4。 |
| `evals/daily-v1.json` | 保留 | 当前固定任务/评测夹具；版本与题目身份参与验证；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `evals/foundation-v4.json` | 保留 | 当前固定任务/评测夹具；版本与题目身份参与验证；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `examples/acceptance.json` | 保留 | examples/acceptance.json；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `examples/example.txt` | 保留 | examples/example.txt；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `output/playwright/before-desktop.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/design-directions.html` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-desktop-dark.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-desktop-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-dialog-motion-end.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-dialog-motion-middle.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-dialog-motion-start.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-mobile-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-mobile-observatory.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-navigation-motion-end.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-navigation-motion-middle.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-navigation-motion-start.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-settings-dark-bottom.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-settings-dark.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-settings-deepseek.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-settings-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-settings-zoom-200.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-welcome-motion-end.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-welcome-motion-middle.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/final-welcome-motion-start.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-browser-report.json` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-chat-320-dark.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-chat-320-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-chat-390-dark.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-chat-390-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-desktop-chat-dark.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-desktop-chat-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-document-preview-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-goals-dark.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-knowledge-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-late-preview-1024.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-late-preview-390.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-navigation-320.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-navigation-390.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-project-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-runtime-1024.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-runtime-320.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-runtime-390.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-sessions-dark.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-settings-dark.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-settings-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-standard-runtime.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-tablet-dark.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/qa-tablet-light.png` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `output/playwright/standard-preview-report.json` | 移出生产树 | 一次性设计截图/报告，不承担运行和发布职责；保留原文件。 |
| `pyproject.toml` | 修改并保留 | pyproject.toml；版本同步 0.24.0；仍以 src 为唯一生产根与当前静态资源包。 |
| `scripts/audit_secret_patterns.py` | 保留 | 已知秘钥格式的本地审计，不打印匹配值。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `scripts/benchmark_local_overhead.py` | 修改并保留 | 固定本机开销对照，不访问真实模型或读取用户项目。；新增相同 10000 Memory 夹具下 Workspace 重开中位数对照。 |
| `scripts/check_annotations.py` | 保留 | 项目宪法的中文说明覆盖守卫。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `scripts/soak_long_run.py` | 保留 | 长任务 Durable Executor 浸泡/故障注入工具。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `scripts/validate_os_credentials.py` | 保留 | 系统凭据库容量/轮转/清理 smoke。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `scripts/validate_package.py` | 修改并保留 | 在隔离根核对真实安装 wheel、HTTP 静态资源和计划 API。；安装 wheel 后通过真实 HTTP 校验全部静态资源和 Goal/session/计划。 |
| `src/myth/__init__.py` | 修改并保留 | 公开 Runtime/组件入口与按需导出。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/acceptance.py` | 保留 | Exact Agent 的固定验收与有界上下文纯函数。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/adapters/__init__.py` | 保留 | 具体 I/O 与状态仓储适配器包入口。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/adapters/agent_execution.py` | 保留 | Exact Agent 的本机执行适配器。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/adapters/agent_store.py` | 修改并保留 | Exact Agent 的 SQLite 仓储实现。；当前 schema 由 Store 原子装配，删除旧库迁移；聚合所有权保留。 |
| `src/myth/adapters/conversation_execution.py` | 修改并保留 | 对话工具的本机执行适配器。；知识操作调用独立仓储，模型能力依赖内移，项目检索排除垃圾站。 |
| `src/myth/adapters/driver_lock.py` | 保留 | Exact Agent 与 Conversation 共用的本机 Driver 锁。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/adapters/milvus_retrieval.py` | 保留 | Milvus 向量检索适配器。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/adapters/personal_store.py` | 修改并保留 | 长期 Goal、进度、关联、Trigger 与个人设置的 SQLite 状态所有者。；当前 schema 由 Store 原子装配，删除旧库迁移；聚合所有权保留。 |
| `src/myth/adapters/workspace_store.py` | 修改并保留 | 项目、会话、知识与对话步骤的 SQLite 状态所有者。；拆出知识状态；删除旧库补丁；已准入步骤只消费一次，结果冲突拒绝。 |
| `src/myth/agent_runtime.py` | 保留 | Exact Agent 的公开装配入口。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/application/__init__.py` | 保留 | 纯应用用例包入口。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/application/agent.py` | 保留 | Exact Agent 的有界应用用例。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/application/conversation_agent.py` | 保留 | Conversation 与长期 Goal 的应用循环。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/artifacts.py` | 保留 | 不可变对象、受管文件和收据日志的文件系统适配器。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/auth/__init__.py` | 修改并保留 | 本应用独立认证包入口。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/auth/chatgpt.py` | 修改并保留 | Myth 自有 ChatGPT OAuth 的认证适配器。；保留 OAuth/OIDC 与原子凭据代际切换，删除旧单记录格式读取/清理。 |
| `src/myth/auth/provider_keys.py` | 修改并保留 | 远端模型 API Key 的应用内安全凭据中心。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/auth/transport.py` | 保留 | 认证外圈的受限 HTTP 传输。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/cli.py` | 保留 | 命令行装配入口。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/conversation.py` | 保留 | 对话的纯检索、算术及模型请求投影规则。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/conversation_context.py` | 修改并保留 | 从持久对话事实生成有预算的模型上下文。；删除旧附件快照兼容；固定附件与普通召回按真实来源分别预算。 |
| `src/myth/conversation_ports.py` | 修改并保留 | 对话用例的仓储、执行、控制、记忆和 Goal checkpoint 合同。；删除无调用者的 reject 别名；保留当前应用依赖合同。 |
| `src/myth/core/__init__.py` | 修改并保留 | 最小核心合同的公开导出。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/core/primitives.py` | 保留 | 长期 Goal 的最小不可变合同。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/decision_runtime.py` | 修改并保留 | 模型调用的持久准入、派发、收据和决策绑定协调器。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/delivery.py` | 修改并保留 | Conversation 交付账本：终态收尾、验收、工作项和人工关注。；计划分配、部分字段更新、验收摘要核对进入同一写事务；重写具体中文说明。 |
| `src/myth/demo.py` | 保留 | 可重复的本地精确替换演示工厂。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/domain.py` | 保留 | 纯领域词汇与字节级确定性规则。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/domains/__init__.py` | 修改并保留 | 同级纯领域合同包入口。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/domains/coordination.py` | 修改并保留 | 组织工作方式的纯策略合同与登记表。；删除未接入组织策略登记，保留当前 Intent/Agent/只读委派路径。 |
| `src/myth/domains/information.py` | 保留 | Intent 与信息分辨率/增量/增益的纯数据合同。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/domains/intent.py` | 修改并保留 | Intent Pick 的纯协议。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/domains/personal.py` | 保留 | 个人 Trigger 的纯合同。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/durable_executor.py` | 修改并保留 | 独立常驻 Durable Executor。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/evaluation_runner.py` | 修改并保留 | Foundation 固定版本评测的本机运行器。；筛选题目明确 partial 不发布；未知题号拒绝，当前全套评测保持固定。 |
| `src/myth/failures.py` | 修改并保留 | 把已知失败标准化为模型可恢复、UI 可观测的数据。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/goal_scheduler.py` | 修改并保留 | 显式一次性/固定间隔 Goal 计划的本地调度适配器。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/mental_model_refresh.py` | 修改并保留 | Mental Model 自动刷新调度与持久工作协调。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/models.py` | 保留 | 供应商无关的模型请求、结果与决策合同。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/network_recovery.py` | 保留 | 断连恢复的纯规则。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/__init__.py` | 修改并保留 | 横向能力合同与目录的公开导出。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/platform/calibration.py` | 保留 | 配对增益证据的纯校准矩阵。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/capabilities.py` | 修改并保留 | 能力描述和执行白名单的纯注册表。；只登记可执行或确有合同使用的能力，去掉零实现 planned 工具。 |
| `src/myth/platform/completion.py` | 保留 | Conversation 的 Verify-on-Stop 纯策略。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/components.py` | 修改并保留 | 产品组件与架构地图的装配登记。；移除占位登记、未使用持有对象，保留真实第三栏观测依赖。 |
| `src/myth/platform/context.py` | 保留 | 小型组件上下文的纯预算投影器。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/context_anchor.py` | 保留 | 可持久的增量 Context Anchor。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/contracts.py` | 修改并保留 | 组件成熟度与职责的纯描述合同。；删旧 WIRED/Layer 包装；成熟度合同仍由组件地图使用。 |
| `src/myth/platform/control.py` | 修改并保留 | 控制命令的纯状态转换规则。；只保留当前控制合同，移除 abort 词汇和重复包装。 |
| `src/myth/platform/control_store.py` | 修改并保留 | Control 命令、revision 与投影的 SQLite 所有者。；当前字段统一 stopped；去掉 ControlPlane 与旧别名，保留晚到事实。 |
| `src/myth/platform/cost_model.py` | 修改并保留 | 显式成本权重合同及 SQLite 版本目录。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/platform/evaluation.py` | 修改并保留 | 固定评测集、观测、配对比较与发布门槛合同。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/platform/evaluation_store.py` | 修改并保留 | 评测运行和逐题观测的 SQLite 证据账本。；当前 schema 由 Store 原子装配，删除旧库迁移；聚合所有权保留。 |
| `src/myth/platform/evolution.py` | 保留 | 策略候选及人工发布决定的纯合同。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/evolution_store.py` | 修改并保留 | 候选、证据、活动策略与发布历史的 SQLite 所有者。；当前 schema 由 Store 原子装配，删除旧库迁移；聚合所有权保留。 |
| `src/myth/platform/kernel.py` | 移出生产树 | 无生产调用者的旧 MythKernel 别名；唯一入口为 MythComponents。 |
| `src/myth/platform/knowledge_views.py` | 修改并保留 | Mental Model 与 Knowledge Page 的持久派生视图。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/platform/mcp.py` | 移出生产树 | 只在组件地图/占位测试使用，没有执行路径。 |
| `src/myth/platform/memory.py` | 修改并保留 | Memory 的用途分类。；仅保留当前类型合同，去掉无生产调用者的第二套内存目录。 |
| `src/myth/platform/memory_lifecycle.py` | 保留 | Memory 生命周期的纯规则模块。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/memory_store.py` | 修改并保留 | 生产记忆的持久 SQLite 适配器。；保留 revision/freshness/派生视图；删除旧库升级与每次启动全量回填。 |
| `src/myth/platform/observability.py` | 保留 | 事件事实的纯轨迹投影。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/replay.py` | 保留 | 历史 Replay World：把同一冻结条件下已发生的 SOTA Route 合并为可重放的已实现搜索空间。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/retrieval.py` | 保留 | 检索后端可用性与模式的纯路由合同。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/skills.py` | 移出生产树 | 仅目录占位，没有生产调用者。 |
| `src/myth/platform/subagents.py` | 保留 | 子 Agent 的隔离执行合同与预算分配原语。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/tool_discovery.py` | 保留 | Conversation Tool 的渐进披露纯函数。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/platform/workflow.py` | 移出生产树 | 未接入执行的占位实现，避免登记冒充功能。 |
| `src/myth/ports.py` | 保留 | Exact Agent 与横向能力的端口合同。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/providers/__init__.py` | 修改并保留 | 统一供应商适配器导出。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/providers/base.py` | 保留 | 模型 I/O 的结构化端口。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/providers/capabilities.py` | 移出生产树 | 纯合同内移为 model_capabilities.py；旧导入路径淘汰。 |
| `src/myth/providers/deepseek.py` | 修改并保留 | DeepSeek Responses API 传输适配器。；能力合同依赖内移，保持当前厂商原生推理设置。 |
| `src/myth/providers/ollama.py` | 保留 | 本机 Ollama HTTP 适配器。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/providers/openai.py` | 修改并保留 | OpenAI Responses 与 ChatGPT 计划的传输适配器。；能力合同依赖内移，保留当前 Responses/流式完成/用量与认证路径。 |
| `src/myth/providers/scripted.py` | 保留 | 确定性的模型替身。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/runtime.py` | 保留 | 受管精确文件任务的装配与执行协调入口。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/session_statistics.py` | 保留 | Observability 的会话统计纯投影。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/sota_route.py` | 修改并保留 | SOTA Route：从已验收成功 Run 中学习更省的可观察执行路径。；去掉旧数据全量导入与历史标记表；只消费显式验收，检索排除垃圾站。 |
| `src/myth/store.py` | 修改并保留 | Core 执行事实与多资源预算的 SQLite 状态所有者。；当前格式身份、原子 DDL、并发 WAL 首启；业务事务与装配明确分开。 |
| `src/myth/strategies/__init__.py` | 修改并保留 | 可替换纯组织策略的公开导出。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/strategies/information_control.py` | 保留 | 实时信息获取的纯准入策略。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/strategies/information_gain.py` | 保留 | 配对固定评测证据的边际增益估计策略。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/strategies/information_resolution.py` | 保留 | 同源信息 L0/L1/L2 的纯选择策略。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/strategies/intent_pick.py` | 保留 | 保守 Intent Pick 的纯规则策略。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/task_benchmark.py` | 修改并保留 | 固定日常任务的真实 Workspace 运行器与独立小型 oracle。；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/verification.py` | 修改并保留 | 受限项目测试 profile。；保留受限测试执行合同；中文说明按 profile、子进程和收据边界解释。 |
| `src/myth/web.py` | 修改并保留 | 本机 HTTP 入站与 Exact Agent 服务装配。；移除旧 abort 路由，当前 Stop 入口不变。 |
| `src/myth/web_workspace.py` | 修改并保留 | 对话 HTTP 产品门面与后台 Driver 生命周期。；知识 API 显式调用独立仓储，其他 Driver/Goal/验收路径保留。 |
| `src/myth/webui/app.css` | 保留 | 当前产品页面/静态资源；实际 HTTP 与前端行为回归覆盖；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/webui/app.js` | 修改并保留 | 当前产品页面/静态资源；实际 HTTP 与前端行为回归覆盖；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/webui/favicon.svg` | 保留 | 当前产品页面/静态资源；实际 HTTP 与前端行为回归覆盖；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/webui/goals.js` | 保留 | 当前产品页面/静态资源；实际 HTTP 与前端行为回归覆盖；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/webui/index.html` | 保留 | 当前产品页面/静态资源；实际 HTTP 与前端行为回归覆盖；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/webui/inspector.js` | 修改并保留 | 当前产品页面/静态资源；实际 HTTP 与前端行为回归覆盖；清理旧导出、字段或依赖；当前合同与真实调用路径保留。 |
| `src/myth/webui/reconnect.js` | 保留 | 当前产品页面/静态资源；实际 HTTP 与前端行为回归覆盖；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/webui/statistics.js` | 保留 | 当前产品页面/静态资源；实际 HTTP 与前端行为回归覆盖；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/webui/theme.js` | 保留 | 当前产品页面/静态资源；实际 HTTP 与前端行为回归覆盖；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `src/myth/workspace.py` | 修改并保留 | 对话产品的装配根。；装配真实组件，去掉 Kernel 别名与历史 SOTA 回填。 |
| `start-myth.ps1` | 保留 | start-myth.ps1；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/check_workspace_browser.cjs` | 保留 | 当前前端行为/浏览器回归与夹具入口；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_agent_runtime.py` | 保留 | 回归边界：Exact Agent 端口装配与固定文件范围。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_architecture.py` | 修改并保留 | 回归边界：纯模块依赖方向。；模型能力和控制合同加入内圈导入守卫；纯领域冷导入保持可测。 |
| `tests/test_context_eval_integration.py` | 保留 | Context、Capability、Recovery、Evaluation 与 Acceptance 的固定回归。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_control_tower.py` | 修改并保留 | 回归边界：持久控制、记忆与受限项目工具。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_conversation_context.py` | 修改并保留 | 回归边界：有界上下文与 Compact revision 消费。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_decision_runtime.py` | 保留 | 回归边界：模型准入、收据和决定绑定。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_delivery_workflow.py` | 保留 | v0.24 交付闭环：终态补偿、验收、工作项、人工关注与受限测试 profile。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_domain.py` | 保留 | 回归边界：纯字节替换规则。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_durable_executor.py` | 保留 | 回归边界：独立 Durable Executor、同 Run 恢复与无进展观测。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_execution_graph.py` | 保留 | Execution Graph 只读投影测试。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_harness_deepening.py` | 保留 | Harness Engineering 四项深化的回归边界。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_information_semantics.py` | 保留 | 回归边界：信息粒度、变化、增益和授权语义。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_knowledge_views.py` | 保留 | 回归边界：Mental Model 是 materialized Memory view，Knowledge Page 只拥有树结构。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_long_run_soak.py` | 保留 | 回归边界：长任务浸泡工具的健康路径与 UNKNOWN no-replay。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_memory_lifecycle.py` | 保留 | 回归边界：Evidence-backed Memory、immutable revision、freshness 与受约束 Delta。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_mental_model_auto_refresh.py` | 保留 | 回归边界：Mental Model 自动后台 Refresh 复用 Core Run / DecisionRuntime / DurableExecutor。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_milvus_retrieval.py` | 修改并保留 | 回归边界：Milvus 派生索引、Hybrid hydration 与 Memory 渐进披露。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_models.py` | 保留 | 回归边界：统一模型决定解析。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_network_recovery.py` | 修改并保留 | 断网恢复的故障注入回归。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_observatory_ui.cjs` | 保留 | 当前前端行为/浏览器回归与夹具入口；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_personal_agent_foundation.py` | 保留 | 回归边界：长期意图和描述性 Trigger。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_platform_skeleton.py` | 修改并保留 | 回归边界：组合能力合同与成熟度。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_platform_web.py` | 修改并保留 | 回归边界：组件架构投影。；验证 Web/Workspace 同一实际组件地图，明确不登记占位 A2A/MCP/Browser。 |
| `tests/test_process_crash.py` | 保留 | 回归边界：真实子进程硬退出窗口。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_provider_keys.py` | 保留 | 回归边界：应用内 Provider API Key 安全存储与兼容回退。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_providers.py` | 保留 | 回归边界：固定供应商传输夹具。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_reconnect_ui.cjs` | 保留 | 当前前端行为/浏览器回归与夹具入口；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_replay_world.py` | 保留 | Replay World 回归：历史只覆盖已发生分支，候选策略不能从离线重放获得线上发布权限。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_runtime.py` | 保留 | 回归边界：精确文件效果、预算与恢复。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_schedule_web.py` | 保留 | 回归边界：本机计划 HTTP 与后台生命周期。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_security_performance.py` | 修改并保留 | 安全反例和延迟边界回归。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_session_statistics.py` | 修改并保留 | 会话统计的计量、持久恢复与本机 HTTP 回归。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_sota_route.py` | 保留 | SOTA Route 回归：只从已验收成功 Run 学习同条件下更省的可观察路径。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_state_boundaries.py` | 保留 | 回归边界：个人状态所有权与真实 SQL 故障回滚。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_statistics_ui.cjs` | 保留 | 当前前端行为/浏览器回归与夹具入口；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_task_benchmark.py` | 保留 | 回归边界：固定任务 Harness 及独立验收。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_v011_runtime_closure.py` | 修改并保留 | 回归边界：Control 竞争、Goal 准入和作用域。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_v012_retrieval_eval.py` | 修改并保留 | 回归边界：全候选召回与历史固定评测。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_v013_eval_routing.py` | 修改并保留 | 回归边界：固定知识路由和历史评测执行。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_v014_information_gain.py` | 修改并保留 | 回归边界：同题配对增益与成本语义。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_v015_evolution_control_plane.py` | 保留 | 回归边界：策略发布资格、版本固定与显式回退。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_v016_intent_correctness.py` | 保留 | 回归边界：算术/知识路由反例。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_v017_provider_context.py` | 修改并保留 | 回归边界：窗口、温度与旧设置升级。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_v0181_cache_observability.py` | 保留 | 回归边界：实际缓存计量与缺测显示。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_v018_goal_work_loop.py` | 保留 | 回归边界：跨会话/重启长期进度。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_v019_native_oauth.py` | 保留 | 回归边界：独立 OAuth 边界与安全存储。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_v020_recovery_runtime.py` | 保留 | 回归边界：持久游标、Driver Lease 与安全接管。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_v021_goal_scheduler.py` | 修改并保留 | 回归边界：计划机会原子准入及恢复。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_verified_agent.py` | 保留 | 回归边界：独立固定验收与 Agent 崩溃窗口。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_web.py` | 保留 | 回归边界：包资源、HTTP 绑定与第三栏 DOM。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_web_contract.py` | 保留 | 回归边界：真实本机 HTTP 合同、入口去重及跨站拒绝。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/test_workspace.py` | 修改并保留 | 回归边界：对话、资料、受管产物和实际恢复。；同步当前调用/固定夹具；保留仍证明业务或恢复不变量的回归。 |
| `tests/test_workspace_interactions_ui.cjs` | 保留 | 当前前端行为/浏览器回归与夹具入口；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `tests/ui_fixture_server.py` | 保留 | 浏览器回归专用 loopback 服务。；职责与当前入口/引用核对；未发现支持重写或删除的具体收益，保留并接受整体验证。 |
| `.gitattributes` | 新增 | Git archive 明确排除垃圾站与一次性 output。 |
| `MANIFEST.in` | 新增 | sdist 明确包含生产源码和当前资料，排除垃圾站/运行数据/缓存。 |
| `docs/DELIVERY.md` | 新增 | 把版本计划改写为当前验收、工作项、收尾和受限 test.run 合同。 |
| `docs/FILE_REVIEW.md` | 新增 | 逐文件处置记录 |
| `docs/REFINEMENT_REVIEW.md` | 新增 | Myth 沉淀期审查与改进 |
| `docs/evidence/refinement-2026-10-04.json` | 新增 | docs/evidence/refinement-2026-10-04.json |
| `scripts/validate_release.py` | 新增 | 真实 wheel/sdist/ZIP 排除检查，防止垃圾站或旧入口被构建清单带回。 |
| `src/myth/adapters/knowledge_store.py` | 新增 | 独立知识所有者；正文/分片原子提交，SQL 过滤作用域，派生向量回源核对。 |
| `src/myth/model_capabilities.py` | 新增 | 供应商中立模型能力合同，供上下文内圈和外圈 Provider 共同依赖。 |
| `tests/test_refinement.py` | 新增 | 新增真实 SQLite 故障窗口、并发读改写、来源摘要和 partial 发布资格回归。 |

机器可读清单与度量见 [refinement-2026-10-04.json](evidence/refinement-2026-10-04.json)。
