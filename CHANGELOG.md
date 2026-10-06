# Changelog

## 未发布 — 工具 Hook 首版

- 接入 `before_tool / after_tool / on_tool_error`：受信 Python 注册与固定 `.myth/hooks.json` 规则，按能力 glob/优先级运行，同次调用冻结计划与只读参数/结果。
- 前置拒绝/故障不签 Ticket；后置及错误观察不覆盖原结果或 UNKNOWN，已有 Ticket 的恢复/复用不重发 Hook。仓储核对身份后记录无业务正文的 `ConversationToolHook` Trace。
- 复用工具目录作参数形状/界限校验；扩展 API 增加 Hook 目录。按用户要求未新增/运行测试或其他执行验证；同步回调、接入范围及后续验收见 [Hook 说明](docs/TOOL_HOOKS.md)。

## 未发布 — Skill / MCP 首版接入

- 新增 `skill.list / skill.load`：只读 `.myth/skills/<id>/SKILL.md`，元数据发现、全文摘要与有界分页；不执行技能脚本或扩张权限。
- 新增 `mcp.servers / mcp.tools / mcp.call`：官方 SDK v1 的可选 stdio 适配器，固定本机配置/允许名单，本 Turn 的工具发现和输入 schema 核对；每次远端连接/调用先签 Ticket，收据缺失不自动重发。
- Workspace 注入扩展端口；只读 `/api/workspace/extensions` 返回目录/依赖可用性，已有工具观测展示真实结果。提供配置、Skill 和本机 MCP 服务示例。
- 按用户要求，本次没有新增或运行测试，也未运行语法、浏览器、构建或示例服务；后续验收与首版限制见 [扩展说明](docs/EXTENSIONS.md)。

## 未发布 — 22:56 续跑的事实与授权边界

- Turn 上下文在写事务外准备，提交核对版本；Scheduler 保留机会/预算/Goal 同连接原子提交。委派复用固定父 Ticket。
- Core 禁止 UNKNOWN 假完成和跨 Run/候选验收；test.run 要有实际执行测试的完成证据。
- OAuth 授权代次、一次性挑战与根目录安全槽隔离，OS 锁串行轮转；未知刷新不重放，明确零派发保留网络恢复。
- 修复 Memory Delta 水位、scope 迁移与派生来源检索；Web/SOTA/Eval 缺测保持未知，环境扫描提前剪枝私有目录。
- 当前 UI 底色更新为 `#FFFEF8` / `#0E100F`，原创 SVG 替代旧太极；同步设置/DOM 合同、中文输入与迟到响应保护。旧设计合同、资源和截图留档。
- 按用户最新指示优先推送 PR；完整视觉矩阵、新环境安装及全任务单验收仍待完成，见 [交付记录](docs/CONTINUATION_REVIEW.md)。

## 未发布 — Runtime Continuity Guard

- 吸收 Commerce Agents 的 Runtime follow-through 思路，但不引入平行框架：可恢复的效果工具失败后，模型首次 completion 会被 `CompletionGuard` 拒绝并收到结构化恢复 Observation；同能力后续真实成功自动闭合，若模型在提醒后明确重新判断阻塞则允许结束说明，避免死循环。
- Turn 准入新增确定性 Continuity Guard：基于持久消息身份/正文 digest、模型设置、Project 配置和 Current Facts 版本输出 `new / resume / catchup / rebuild`、稳定 reason code 与 `continuity epoch`；证明不了复用安全时 fail closed 到派生 Context 重建，不删除历史、不重放外部效果。
- Context Anchor 升级为 source-bound v2：每次增量复用先重新核对 covered raw-history digest；旧版/失配 Anchor 从真实消息重建，避免摘要自证。
- Memory 的 `user_asserted / verified` 当前状态单独形成 metadata-only facts digest，不让 query 相似度或 top-k recall 冒充 current authority；正文仍由 Memory 仓储拥有。
- 新写入消息原子保存 `content_digest`；Continuity 事件、Context report 与第三栏同时展示 action / reason / epoch / Current Facts 摘要，历史记录与当前事实保持分离。

## 未发布 — 可展开的工作台

- 奶油白与星空黑固定为 `#F8F4ED`、`#0E100F`，本地打包中文正文、宋体标题与拉丁字体；品牌使用水平双眼的水墨双鱼波形，真实等待采用微型太极。
- 三栏内部重组：导航按工作/资料/最近会话独立折叠，观测按概览/执行/资源切换并逐类折叠；真实问题目录直接定位消息。
- 专注模式收起两栏，退出恢复此前布局和草稿；支持键盘、减少动态效果与手机抽屉，保留全部 Runtime 事实及现有模型池。
- 增加离线资产白名单、安装包核对及布局无业务副作用验收；未知后端状态与内容保留原值。
- 消息正文与输入框两侧共享阅读尺度；子模型默认沿用主模型提供方，仅 Ollama 显示可调本地窗口与地址。
- 设置、对话与弹窗共用主题选择菜单和可编辑模型建议；支持键盘选择、同层关闭及动态目录更新。
- 主/子模型数值设置都有独立范围与含义说明，Thinking 采用模型原生选项；提供方切换恢复合法采样默认值，服务端独立拒绝越界值。
- 主/子模型按精确提供方和 ID 自动查询公开标价，显示来源、时间及缓存状态；未公布/未知价格不当成免费，合同费率仅作显式覆盖。报价在事务外解析并冻结到新 Turn，历史报价和重试身份不被目录刷新改写。

## v0.27.0 — 有界并行子任务

- 新增 `agent.parallel(tasks)`：一次提交最多三项独立任务，各工作线程使用私有 SQLite 连接和 Provider，复用共享子引擎；整批等待近似最慢任务加调度开销。
- 父批次与子工具 Ticket 同事务准入，子模型仍竞争父 Run 的原子预算；子结果按固定 ordinal 汇合，依赖必须先由主模型审核采用，图显示真实 fork/join 分支。
- 子恢复与模型请求去重只核对自己的请求作用域，避免把在途兄弟调用标为 UNKNOWN。零派发重连只续跑未完成项；已有收据及崩溃后的绑定无需新 Provider。
- 每项分别评分、审核元数据及解除拒收义务；整批返回不代表整批采用，失败/拒收费用继续记录。批次实测等待与子调用累计耗时分别表示，恢复缺测不补数。
- 批次上下文仅传有界导航，完整对象可回读；修复父 Stop 后子游标因通用终态 gate 返回空而继续规划的窗口，晚到收据照常保留。

## v0.26.0 — 共享子流程与可回读交接

- 子模型设置去掉槽位标题；用户能力选择只作为初值。主模型可指定槽位并判断实际能力，同类意见校准后续选择，三个同档强模型可互相替代。
- 子流程复用 `ConversationAgent`、Context 编译/Compact、控制安全点及模型/工具账本；1–8 步持久子游标只可分页读取显式输入。零派发断线按父调度重连，UNKNOWN 不重发。
- 标准交接信封绑定任务、上下文、正文和元数据摘要及顺序/依赖/替代身份；正文与公开元数据完整存储，默认语义摘要最多 1200 字符，`agent.result` 精确分页回读。
- 主模型内容评分与元数据审核分开；拒收正文从默认上下文移除，必须重新委派或用 `agent.resolve` 提供替代内容后才能完成。拒收花销继续记录。
- 执行图覆盖子步骤、输入回读及重试 Attempt，分别显示全部估算、已审核、待审核和有争议金额。计量缺测不补零，供应商新增公开统计保留，费用仍是配置标价估算。
- 修复模型 Ticket 后 `ValueError` 被当普通参数拒绝继续调用的窗口；崩溃恢复只消费既有收据，不调用 Provider。当前仍为串行单层，真实账号质量/账单未验证。

## v0.25.0 — 模型池与反馈路由

- 设置页配置 1 个主模型和最多 3 个子模型，按提供方、模型、能力档位、适用任务和生成参数冻结到 Turn；沿用安全凭据库。
- `agent.delegate` 按任务类别/难度选择最低满足档位；主模型通过 `agent.evaluate` 记录正确性、完整性、可用性及原因，未评分不得完成。
- 同类任务近期质量失败提高下一次所需档位；上下文/基础设施问题不作为能力降级证据。空池、已知调用失败或步骤不足时主模型接手，UNKNOWN 仍先核对。
- 新增 Claude Messages 与 Kimi Chat Completions 适配器；计量由供应商/Runtime 提供，费用是用户配置标价估算，缺项保持未知。
- Execution Graph 展示提供方、模型、Token、耗时、估算金额、路由与评分关联；唯一模型 Attempt 汇总避免父工具重复计价。
- 首版沿用单层隔离只读 worker、串行执行；协议/故障替身通过不代表真实账号或模型质量验证。

## v0.24.1 — 控制原子提交与委派恢复

- 控制命令、Turn/Core、Goal checkpoint 与事件同事务提交，状态写入归回各自仓储；安全点不再用旧快照覆盖终态。
- 控制响应固定自身 revision；Core 栅栏独立递增，模型/推理设置提交核对能力预检时的 revision。
- 委派先预留父工具额度、签发 Ticket，再调用子模型；模型完成而工具收据未发布时，重开只复用固定子结果。
- 移除 15 个无调用者 Protocol、未使用帮助函数/类型、旧知识读取入口及仓储别名；缺失 Goal 进度/验收合同明确报错，不合成空状态。
- 知识分片分页回归 Knowledge 仓储，统一知识展开入口及分页单位；补齐中文指导注释，更新安全、架构、路线图与发布验证文档。
- 全文件处置表覆盖本轮基线 234 个跟踪文件；原版 10 项故障回归全部失败，修改版全量 426 通过、1 跳过，前端 35 通过，Foundation 完整集 48/48。

## v0.24.0 — 深化、瘦身与原子边界

- 知识正文/分片/检索拆为独立 SqliteKnowledgeRepository；模型能力合同移入供应商中立内圈。
- 移除无使用者的 Kernel/ControlPlane/abort 别名、旧库迁移/回填、旧凭据格式和占位组件；旧评测、历史诊断与画面移入 `.trash/`。
- 当前数据库显式格式版本；逐句事务 DDL、并发首次 WAL 初始化与同快照格式核对，旧实验库原样拒绝。
- 修复未准入步骤可完成任务、重复结果覆写/游标退回、并发工作项序号冲突/字段丢失、验收摘要核对与写入分离等问题。
- 筛选评测不再具发布资格，未知题号明确拒绝；活跃回归统一当前固定集。
- 重写宪法与开发地图，替换无内容中文套话；新增逐文件处置记录、故障回归和性能对照。
- wheel/sdist/Git 源码包排除垃圾站，CI 增加真实构建及安装后 HTTP 检查。


## 未发布 — Durable Mental Model Auto Refresh

- Mental Model 新增显式 opt-in 自动刷新 policy；冻结 Provider/Model/Thinking/Context/Output 设置，未来全局设置不倒写已配置 policy。
- 新增 durable refresh occurrence：以 `model_id + source_change_seq` 去重，最小刷新间隔合并突发 Memory 变化。
- 自动刷新复用 Core Run、模型预算与 DecisionRuntime 的 Intent/Ticket/Receipt/UNKNOWN，不创建第二套模型调用协议。
- 每个 occurrence 新增 owner/heartbeat/lease，与 Durable Executor 全局 lease 形成两级租约；过期可接管同一 Run，不能新建替代机会。
- Provider Ticket 后结果不明时 occurrence=UNKNOWN、Core Run=RECOVERING，并阻断该 Mental Model 后续自动派发。
- synthesis 期间来源发生变化时旧结果标记 SUPERSEDED/CANCELLED，不发布过期 materialized view。
- 上一版 Mental Model 正文只作为演进 baseline，Evidence 仍必须引用本轮 admitted 的底层 Memory。
- Durable Executor 复用同一 worker/并发上限驱动 Refresh 与 Goal/Conversation 工作，不增加隐藏 daemon。


## 未发布 — Controlled Evaluation 深化

- Evaluation 新增持久 `harness_id + harness_mechanisms`，同一固定 Task 可比较 baseline / full / one-mechanism / leave-one-out。
- Eval Ledger 新增受控 Task × Harness × Mechanism attribution；只有完整消融证据才标记 supported benefit/harm，缺证据保持 insufficient。
- Foundation Eval Runner 可在 disposable Workspace 中实际切换 `context_compaction / observation_recall / action_fusion` 并批量记录 discovery Run；未知机制拒绝伪消融。
- Context economics 支持同单位 upfront cost、outstanding debt、breakeven requests 和 projected net saving；缺测 debt 继续保持 N/A，接近窗口上限时安全保护优先。

## 未发布 — Context / Evaluation 深化

- 把 SoL-Pi 可长期复用的机制继续吸收到现有 Myth 骨架，不新增平行 Runtime：State/Context 分离、exact Observation recall、grounded Compact seed、deterministic successor、来源绑定验证、Context 投影选择、Capability 可达性、bounded recovery、capability floor 与 held-out eval。
- 新增 `observation.read`：按当前 Run 已结算 decision/field 精确分页回读原 Tool Observation，绑定 source digest，不重跑 Tool。
- `project.patch_exact` 融合 deterministic diff successor；mutation 与 successor 状态分开，source precondition 变化时 successor 显式 SKIPPED，不开放任意 shell。
- Context 直接比较 normal / compact 的真实 provider-visible 投影，在已结算语义边界与窗口压力下按滞回选择模式；`ConversationContextCompiled` 与 Runtime Observatory 展示 Context mode、reason、实测节约和 Capability 可达性。
- Sub-Agent 只共享 bounded context + admitted source/evidence refs，不继承完整父聊天历史。
- Evaluation 的 capability-floor + Pareto efficiency gate 直接接入现有 Candidate → ELIGIBLE → Promote 路径；逐题机制事件持久进入 Eval Ledger，供 task×policy outcome attribution；held-out identity boundary 与 Discover/Harden 实验合同继续留在现有 Evaluation/Evolution。
- 架构宪法固定 State ≠ Context、来源绑定、失败回原路径、provider-visible 计量、hysteresis、representation transition ≠ semantic transition 等不变量。

## 未发布 — Historical Replay World

- 新增实验性 Replay World：把同一 SOTA Route `comparison_key` 下的 eligible PASSED Action Path 合并成共享前缀树，让历史从日志升级为可计算的“已实现搜索空间”。
- 候选策略只能沿历史真实出现过的边离线重放；越出历史覆盖时明确返回 `UNOBSERVED`，不调用模型/工具、不补造 counterfactual outcome。
- Replay 终点直接引用真实历史 Run 的已测量 metrics；`ReplayLab` 只汇总覆盖与命中历史，不定义神秘总分、`ELIGIBLE` 或自动 Promote。
- 固定 EvalSuite、paired calibration 与显式 Promote 继续作为策略发布链；本次不新增数据库表、不修改线上执行路径、不保存或反推隐藏 CoT。

## 未发布 — Mental Model / Knowledge Page

- 新增 Mental Model：作为 Memory Domain 内的 materialized view，保存 source query / scope / backing Memory / refresh watermark；正文继续复用 Semantic Memory，不新建第二套内容真相。
- Memory revision/revoke 新增单调 change sequence；Mental Model 用 scope-aware watermark 判断 stale，不用“时间看起来新”冒充 freshness。
- refresh 固定为 prepare → synthesis → commit：模型调用在 SQLite 事务外，提交时重新核对 model revision 与 scope watermark；源数据中途变化则拒绝发布旧 synthesis。
- 禁止 Mental Model 把自身 backing Memory 作为下一次刷新来源，减少 synthetic self-feedback / prose drift。
- 新增 Knowledge Page 树：folder/page 只拥有层级、顺序与 mental_model_id；正文仍由 backing Mental Model/Memory 持有。
- Workspace 暴露 mental_models / knowledge_pages 发现性入口，两者指向同一 Knowledge Views 深模块，不复制状态。

## 未发布 — Evidence-backed Memory Lifecycle

- Memory 当前 revision 支持显式 Evidence；Memory-linked Evidence 在提交时固定 source revision，来源更新/撤销后确定性标记 stale，外部 provenance 无版本水位时保持 untracked。
- 更新、撤销都会留下 immutable revision snapshot；旧 revision 的正文与 Evidence 不再借用可变当前表。
- 新增受约束 Memory Delta：只允许 replace_text / add_evidence / remove_evidence，expected_revision 不匹配或任一操作非法时整批失败；空 Delta 不制造 revision。
- Progressive Disclosure 保持不变：L0/L1 只暴露 proof_count/freshness，L2 才展开完整 Evidence；Memory 仍不授予权限、不等同 Verification。
- 现有 SQLite 继续作为权威源，Milvus 继续只是可重建派生索引；本次不新增 Runtime Layer、不替换 MemoryStore。

## 未发布 — Harness Engineering Deepening

- 已知参数/权限/合同/Information Control 失败统一保存为 **Structured Failure Observation**：稳定 `category/code/capability/retryable/expected/hint` 与兼容 `error` 文本并存，已知拒绝不制造 Tool Receipt 或 UNKNOWN。
- Conversation 新增 **Verify-on-Stop**：`request_completion` 在停止前核对 remaining、durable evidence 引用和最近已执行 verifier；不满足条件时返回 Observation 并继续同一 Agent Loop。
- 长会话新增 **Incremental Context Anchor**：Turn 准入时对变旧消息做确定性增量抽取，最近 8 条历史继续原文投影；Anchor 有 lineage/digest，完整消息仍保存在 durable store。
- Conversation Tool Catalog 超阈值后启用 **Progressive Tool Disclosure**：常用工具 + `tool.search/tool.describe` 默认可见，搜索/描述结果在下一步解锁专门能力；猜中隐藏 tool 仍在 Ticket 前拒绝，失败偷调不会自动解锁。
- 新增四项纯策略与 Conversation 集成回归，保持 Capability/Ticket/Receipt、UNKNOWN/RECONCILE、Acceptance、Sub-Agent 隔离等既有边界不变。

## 未发布 — Eval Reliability Evidence

- 固定日常任务的重复试次新增 `pass@k`（Capability）与 `pass^k`（Reliability），不再用单一平均通过率替代稳定性。
- 对两个指标同时报告 Wilson 95% 区间，并显式列出 mixed outcome / all-failed / incomplete cases；未跑满 k 次不进入可靠性分母。
- Benchmark 汇总新增 `model_calls_per_success` 与 failure taxonomy；计量不完整时保持 `None`，不把未知成本补成零。
- 架构宪法加入 **Evidence Before Score**：质量结论必须可追溯到 Case、Execution、Verification 与 grader/oracle 身份，单次漂亮 Run 不构成发布证据。
## 未发布 — Live Information Control v1

- 把现有信息工具接成 bounded live loop，不新增 Tool 或强制 Layer：`knowledge.search / project.search / project.list` 作为 SEEK，`knowledge.resolve / knowledge.read / project.read` 作为 EXPAND，模型停止取信息并继续任务即 KEEP。
- 新增 `LiveInformationController`，在 Tool Ticket 前执行 Novelty、分页 Progress、总量/动作/单来源 Budget 准入；精确重复、停滞分页、耗尽视图和过度信息获取均作为已知拒绝，不进入 UNKNOWN。
- Controller 不建新数据库表；从 durable activities 重建本轮状态，崩溃恢复后预算和重复检测继续成立。
- 已准入信息结果附带小型 `information_control` 投影；Web session 和 Runtime Context 区展示 SEEK/EXPAND 数量、拒绝数与返回字节，不伪造 Information Gain 分数。
- Offline Information Gain 暂不参与 live admission；先保留为固定 Eval 的策略证据，避免未校准数值控制线上执行。
- 新增纯策略、集成与 Observatory 回归，验证重复 SEEK 不产生第二个 Tool Ticket / tool_calls 消耗，以及分页必须沿 continuation 前进。

## 未发布 — Adaptive Sub-Agent v1

- 新增 `agent.delegate`：主 LLM 在正常 Agent Loop 中自行判断是否需要委派，不引入强制 Supervisor 或固定 Multi-Agent 层。
- 第一版 Child 为只读隔离 worker，只接收显式 task / bounded context / 已准入 source refs；不继承完整父对话、Memory、工具目录，不可写入、调用工具、再次委派或向用户提问。
- Child 使用同一父 Run 的 durable model Ticket / receipt / budget 账本和稳定 request key；返回 contracted result 作为 Observation，最终验收与交付仍归父 Agent / Runtime。
- Runtime 模型调用投影新增 request key，便于区分普通决策与 `subagent:` 调用；Multi-Agent Strategy 成熟度提升为 connected。
- 增加上下文隔离与递归委派拒绝回归测试；架构宪法记录 “Context Isolation + Contracted Return” 不变量。
- Runtime Observatory 新增实验性 `Execution Graph`：只从既有 model/decision/operation 持久事实投影 Parent → Tool → Sub-Agent 关系；不新增 Core、状态机或授权语义，无法映射的模型调用保持 `unmapped`。

## 未发布 — 前端工作台重构

- 完整替换工作台视觉与布局，提供奶油白、星空黑及跟随系统主题；对话、项目、知识、会话、Goal 与计划、设置和 Runtime 统一简体中文与响应式控件。
- 保留完整 Runtime 观测及最新 Provider 能力，Turn 完成与验收状态分开显示；连接目录、草稿与异步证据按各自身份隔离。
- 新增快捷命令、抽屉/弹窗键盘焦点管理与增量渲染；轮询不重建等值消息、Goal 或最近会话节点。
- 设计取舍、实际截图与验证范围记录于历史 `UI_REDESIGN.md`，现已移入垃圾站。

## 未发布 — v0.25 SOTA Route

- 新增 **SOTA Route** 成功路径账本：只有 `COMPLETED + Acceptance PASSED` 的 Run 才能进入同条件效率比较。
- 同任务、同模型设置、同冻结 Context / Knowledge / Memory / Goal / Policy 条件比较；本地项目额外冻结允许文本源码 SHA-256 状态摘要，环境不完整时明确 `NOT_COMPARABLE`。
- 不使用单一神秘总分；基础比较保留 model/tool calls、steps、Token、write bytes，多方都实测时再比较 work time、changed lines、human attention。
- 新 Turn 自动冻结历史 **SOTA Route hint**；只作为效率 prior，不扩大权限、不跳过验收/测试。
- 当前路径明显超过历史成功路径时产生 **Drift**，下一次模型决策收到 Replan 提示，但不自动停止。
- Runtime 第三栏新增 SOTA Route：Current vs Champion、Action Path、Drift 与 Compare scope；原有可观测面保持不变。
- 路径账本只保存可观察工具序列和小型定位字段，不保存/推断隐藏 Chain-of-Thought，也不复制源码大参数。
- OpenAI/ChatGPT 在供应商实际返回时记录 **Reasoning Cost / Reasoning Summary / Action Path**；公开摘要可进入 Champion 经验提示，隐藏 CoT 保持 unavailable，不反推。
- 设计与边界见 [SOTA Route](docs/SOTA_ROUTE.md)。


## 未发布 — v0.24 交付闭环

- 新增 durable finalization obligation：回答已提交而 Memory / Goal 未收尾时，重启后补齐派生投影，不重新调用模型。
- 普通 Conversation 新增 Acceptance Ledger（UNVERIFIED / PASSED / FAILED / INCONCLUSIVE），绑定当前回答与产物摘要；Runtime 第三栏新增 Delivery 区。
- 新增持久 Work item / plan revision / evidence / human attention 计量，为跨阶段项目工作建立可检查身份。
- `test.run` 首次进入 executable：只运行用户显式 `trusted_project=true` 的 Python unittest profile；无任意 shell，并明确不宣称 OS 级网络隔离。
- 详细边界与 0–12 周阶段映射记录于历史 `DELIVERY_WORKFLOW_V024.md`，现已移入垃圾站；当前合同见 [DELIVERY](docs/DELIVERY.md)。


## 未发布 — 会话统计

- Runtime 第三栏新增整段会话的模型/工具累计用时、调用级平均 TTFT、端到端 TPS；原有最新 Turn 观测区保留。
- 工具单调时钟毫秒随收据发布、结算入库，恢复/重复读取不重新计时；旧表增量迁移，缺测不回填估算。
- TPS 仅配对成功调用的输出与同一调用耗时；缺测显示未报告，部分耗时标注覆盖。口径与验证见 [会话统计](docs/SESSION_STATISTICS.md)。

## 未发布 — 持久断网恢复

- Conversation/Goal 和浏览器读取使用 1、2、4、8、16、32、60 秒退避，之后每分钟一次；Run/计划的失败次数及 UTC 截止时间保存到 SQLite。
- 明确派发前断连发布零用量失败收据；Runtime 原子结算并释放当前请求键，下次仍须正常准入新 Ticket。超时/重置/不完整响应保留 UNKNOWN，不自动重发。
- 恢复复用同一 Run、步骤、上下文和工具结果；连接探测不刷新业务进度，已有本地工具决定可继续，离线仍支持 Pause/Stop。
- 探测移到带 Driver 心跳的独立线程，worker 独立续租并按重连截止时间唤醒；浏览器首次加载失败也可恢复。
- 新增两小时虚拟时钟断网、真实进程退出、真实 HTTP 已接收后丢响应与前端计时回归。证据边界见 [断网恢复说明](docs/NETWORK_RECOVERY.md)。

## 未发布 — 安全与性能审查

- ChatGPT 登录 URL 移除 ID Token；登录/刷新/退出共用跨进程状态锁，刷新派发前记录 pending，退出取消旧登录机会。
- 系统凭据库使用有界分块和发布清单，支持 Windows 长令牌、旧记录迁移、轮换及中断后清理；无明文 fallback。
- OIDC 增加规范 JWT 编码、RSA 2048-bit、azp/subject 绑定检查；PyJWT 最低版本提升到 2.14.0。
- 携带凭据的 HTTP 禁止重定向；错误和结果脱敏，响应/SSE/Git 输出有界，Web 半开请求限时并拒绝歧义长度头。
- 解析 Responses SSE 完成事件后立即返回；记录传输首输出 delta 时间，缺失 usage 保持未知；已知 4xx 失败不再误标 UNKNOWN。
- 项目读取复核链接实际路径；搜索剪枝私有/依赖目录，Git diff 排除敏感文件并禁用外部 diff/textconv/fsmonitor。
- 后台 worker 从可信安装目录加载；策略发布、回退与证据不可变校验在写事务内完成。
- 会话查询补索引，Memory 全扫描只保留 top-k，公开模型目录短时缓存减少重复 preflight。
- 增加安全反例、合成系统凭据 smoke、固定本地开销对照及不回显匹配值的历史秘钥模式扫描；当时结果记录于已归档的 `SECURITY_PERFORMANCE_AUDIT.md`，当前边界见 [SECURITY](SECURITY.md)。

## v0.23 — Long-run Soak + Worked Time

- Assistant 回复下方新增“用时 X分 X秒 / X小时 X分 X秒”，基于服务端持久消息时间计算整轮 wall-clock；运行中同步显示当前已处理时长。
- Runtime 对每次 `provider.invoke` 增加 `provider_wall_ms` 实测，并在第三栏显示聚合 `Model wall`；明确区分整轮 Worked time 与模型/provider 调用耗时。
- Web 的 `driver_active` 改为读取持久 Driver Lease，而不是只看当前 Web 进程线程集合，独立 Durable Executor 在页面上不再被误显示为 detached。
- 新增 `scripts/soak_long_run.py`：一个输入、一个 Run、最多 30 个工具 checkpoint，可配置 120–180 分钟真实浸泡；使用本地确定性 Provider，不访问真实模型。
- soak harness 支持 post-Ticket ambiguous provider fault 注入；必须进入 `UNKNOWN / RECONCILE`，后续 Executor tick 验证 no-replay。
- CI 只运行秒级 quick soak，真实 2–3 小时结果必须通过同一脚本显式执行，不能把 quick test 冒充长跑证据。

## v0.22 — Detached Durable Executor

- Conversation / Goal 的已准入长任务改由独立 Durable Executor 驱动，Web 只负责确保 worker 存在；关闭页面或 Web 进程不再主动停止任务。
- worker 使用 SQLite 全局短租约；每个 Run 继续复用既有 Driver Lease / generation / heartbeat，同一个 `run_id` 在租约过期后从 durable Execution Cursor 接管，不创建替代 Run。
- 普通 Turn 与 Goal Wake-up 共用同一恢复路径；`UNKNOWN / RECONCILE` 永不自动派发，避免 ambiguous provider/tool effect 被重复执行。
- Runtime Observatory 新增 Executor heartbeat、last durable progress 与 suspected no-progress；明确区分“worker 活着 / Driver 活着 / checkpoint 真正推进”。
- 新增独立 worker CLI：`myth --root <root> worker`；Web 启动时可自动拉起 detached worker。当前仍不是操作系统级开机服务，也不是分布式 worker。
- 增加 Web 生命周期外同 Run 恢复、UNKNOWN no-replay、Goal due admission 与 heartbeat-not-progress 回归测试。

## v0.21.1 — 中文工程指导与准入原子性

- 宪法强制简体中文指导性注释；生产源码、前端、测试与维护脚本补职责/协作/字段/恢复说明，CI 增加说明覆盖守卫。
- Goal 与初始进度共同创建；对话/计划的个人状态写入通过所有者加入同连接准入事务，旧进度缺失不嵌套提交。
- 独立精确文件入口的 Run/账号/Action/Attempt/预留一起提交，准备或资源失败不留下空 Run。
- 两条应用共用独立本机锁；公开入口按需导出，保留旧类身份；同摘要对象发布失败仅在核对完全一致字节后复用。
- 旧固定评测和诊断工具归档；删除重复 Goal 绑定、三处无用导入及可重建旧包镜像；历史回归/迁移/收据保留。
- 完整审阅、清理清单和验证范围记录于历史 `ANNOTATION_AUDIT_V0211.md`，现已移入垃圾站。

## v0.21 — Goal Wake-up and Measured Daily Tasks

- 增加显式一次性 Timer / 固定间隔计划，模型设置在创建时固定，Web 服务每两秒检查到期工作。
- 计划请求去重；Wakeup / Turn / Goal link / admission checkpoint 共用事务；两个连接不能重复认领同一次机会。
- 停机错过的重复时段合并为一次；会话/Goal 忙、暂停、等待或断连时保留计划并延后检查。
- 提交后 Driver 中断由原 Run 恢复；UNKNOWN 不自动重放；旧 Goal checkpoint 不覆盖新 Run。
- 增加「目标与计划」工作台；窄屏 Runtime 入口保留全部观测事实，修复 390px 对话溢出。
- `task-benchmark` 保存 10 个固定日常任务 × 重复试次 × Myth/simple-loop 的完整数据库和独立字节验收；替身与真实 provider 分开标记。
- 真实任务暴露的 PatchContractError 改为 Ticket 前已知拒绝，模型可纠正；补齐步数耗尽及未决收据的 Goal checkpoint。
- CI 扩为 Windows/Linux × Python 3.12/3.13；具体实测边界见 docs/archive/VALIDATION_V021.md。

## v0.20 — Recovery-first Agent Runtime

- Conversation Run 新增 durable Execution Cursor：step / phase / checkpoint / recovery state。
- Web Driver 改为 durable Lease + heartbeat，不再只依赖进程内 `active=set()`。
- Driver 消失且没有不确定外部效果时进入 `INTERRUPTED / RESUME`。
- 已发 Ticket / provider 调用结果不明时保持 `UNKNOWN / RECONCILE`，不盲目 replay。
- 新 Driver 在 lease 失效后接管，并重新经过 normal recovery gate。
- Runtime Observatory 新增 Recovery 区，显示 checkpoint、phase、Driver 与 lease。
- Session UI 标记“可恢复 / 需核对”，支持“从断点继续”。
- 增加跨 Runtime restart、lease expiry、safe resume、UNKNOWN no-replay 回归测试。


## v0.19 — Native Sign in with ChatGPT

- 移除 Myth 对 Pi OAuth / Pi CLI 的认证依赖。
- 按 OpenAI OSS Sign in with ChatGPT 合同实现动态 client registration、PKCE S256、state、OIDC nonce 与 exact loopback callback。
- ID token 验证 signature / issuer / audience / expiry / nonce；返回 client_id 与注册身份绑定。
- access / refresh / ID token 只进入系统安全凭据库；无明文凭据文件 fallback。
- refresh token rotation 跨线程/进程串行；logout 尝试远端 revoke 并始终清除本地凭据。
- ChatGPT plan Responses 使用 `store:false + stream:true`，只在 `response.completed` 后确认成功。
- Web/CLI 新增 login / status / logout；callback query 不进入本地日志。
- 旧 `pi-openai` 设置迁移为 `chatgpt`，旧 durable Run 会收到明确迁移错误。


## v0.18.1 — Cache Observability

- OpenAI Responses 的 provider-reported cached input tokens 写入 durable model usage。
- Runtime Observatory 的 Tokens 区显示 Prompt Cache hit token 与命中率。
- Provider 不提供缓存计量时明确显示 N/A，不从 keep-alive / KV cache / 相似上下文推测。
- cache hit rate 定义为 `cached_input_tokens / input_tokens`。

Myth 只记录已经落地并进入主线的高价值变化。详细提交历史以 Git 为准。

## v0.18 — Goal-first Personal Work Loop

- 长期 Goal 增加 durable work state：
  `current_state / progress_note / next_action / waiting_for / last_run / revision`。
- Conversation 在真实终态写 Goal checkpoint。
- 同一 Goal 可跨 Session / restart 继续，并把 checkpoint 固定进新 Turn Snapshot。
- 第三栏 Runtime Observatory 固定保留：
  Goal / Execution Flow / Trajectory / Tokens / Context / Tools / Control / Budget。
- UI observability identity 加入回归测试。

## v0.17 — Provider Context Hardening

- ModelRequest 增加 `num_ctx` / temperature。
- Ollama 显式传递 `num_ctx` / temperature / keep_alive。
- Ollama 本地 Context budget 从 `num_ctx - output - reserve` 推导。
- provider-confirmed context truncation 记录为 durable FAILED，而非 UNKNOWN。
- ambiguous post-Ticket transport failure 继续保持 UNKNOWN。

## v0.16 — Intent Correctness

- 收紧 deterministic arithmetic grammar。
- 日期 / 版本 / 分数 / 百分比 / 电话形状默认回退 Agent。
- strong / weak knowledge cue 分级。
- calculator rejection 写入 `RouteFallback` 后安全回退。
- foundation-v4 增加 36 条 Intent adversarial cases。

## v0.15 — Evidence-driven Evolution Control Plane

- versioned Cost Model Registry。
- Gain Calibration Matrix。
- durable Policy Candidate Registry。
- complete-suite release evidence。
- explicit Promote / Rollback。
- Active Policy 只影响未来 Turn，历史 Turn 不倒写。

## v0.14 — Paired Evaluation + Information Gain

- Eval Ledger 持久化。
- baseline / candidate paired comparison。
- Information Gain 只从同 case 的 paired Verdict evidence 估计。
- 成本默认保留为向量，显式权重后才计算 gain-per-cost。

## v0.13 — Executable Evaluation + Conservative Routing

- 固定 EvalSuite -> Runner -> Observation -> Report -> Release Gate。
- `myth eval` CLI。
- conservative `local_retrieval` route。
- L0 / L1 / L2 Information Resolution 接入 Turn admission。

## v0.12 — Retrieval Correctness Foundation

- Knowledge 去掉 rank 前 10,000 chunk 静默截断。
- Memory 去掉最近 500 条隐式 recall 上限。
- candidate coverage diagnostics。
- project.search cursor / max_files。
- fixed-digest L0 / L1 / L2 knowledge resolution。
- foundation-v1。

## v0.11 — Runtime Closure

- Control revision 跨 SQLite 连接原子分配。
- Goal admission 与 request identity 绑定。
- scoped Episodic Memory。
- `knowledge.read`。
- bounded deterministic arithmetic fast path。

## v0.10 — Context Continuity

- ContextCompiler 与 bounded projection。
- context selected / folded / dropped evidence。
- Compact / Pause 连续性加强。

## v0.9 — Core / Domains / Strategies

- 从固定“层级栈”重构为：
  Core + Domains + Strategies + Ports / Adapters。
- Goal / Trigger / Personal State 进入持久化边界。
- Stop 成为产品术语。

## v0.8 — Product Control

- Steer / Pause / Resume / Stop。
- Model / Thinking switch。
- Compact。
- durable Memory revision。
- project.search / diff.preview / git.status / git.diff。

## v0.7 — Agent Workbench UI

- 三栏工作台。
- Runtime Inspector / Execution Spine。
- 暖纸张 / 墨色 / 克制橙视觉系统。

## Earlier

v0.1–v0.6 主要完成 Durable Runtime、exact verification、conversation workspace 与 breadth-first platform skeleton。需要逐提交考古时直接查看 Git history。
