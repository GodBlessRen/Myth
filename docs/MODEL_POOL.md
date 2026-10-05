# 模型池

一个主模型、最多三个子模型。槽位没有预设角色标题，三个均可配置强模型；“初始能力”只提供起点，主模型根据任务、实际结果与经历判断能力。提供方共用系统凭据库，配置冻结到 Turn，在途任务不跟随设置变化。

支持 Ollama、OpenAI、Myth ChatGPT OAuth、DeepSeek、Claude、Kimi。更多设置包括备注、类别、1–8 步上限、输出 Token、Thinking、本地窗口和可选标价；不选类别表示全部适用。Claude 使用 Messages 强制结构化输出，Thinking 当前仅默认/关闭；Kimi 默认或 enabled/disabled。目录连通不证明生成质量。

## 主子协作

```text
主模型提案 → 冻结合同 → 父工具 Ticket → 共同 ConversationAgent 子游标
  → 子模型/输入工具 Ticket + Receipt → 完整对象 + 有界交接
  → 主模型内容评分 / 元数据审核 → 采用，或重派 / 主模型补做 → 汇总
```

主子使用同一个应用循环、Context 编译/Compact、安全点控制、错误处理、断线调度和预算账本；隔离的是输入、权限、游标与完成策略。子模型仅见显式任务、输入预览及分享来源，可用 input.read 分页展开固定输入；不继承父历史、项目指令或 Memory，不能写入、递归或提问，结果不写用户 Memory。

当前执行**串行、单层**。三个是候选槽位上限，不表示三个并发线程。每个子任务有稳定 delegation_id、父消费 sequence、已采用结果的 depends_on 和拒收结果的 replaces。依赖先审核，消费按持久父步骤排序；不能按到达时间拼接或用旧任务覆盖新任务。本版不宣称已实现并行等待/乱序调度。

## 交接：schema 信封，自然语言内容

agent.delegate 提供 task/context/expected_output/source_refs、task_type/difficulty，可加 profile_id/depends_on/replaces。Runtime 固定模型、输入摘要、来源、步数和额度后执行；所有子调用仍花父 Run 的预算。

| 返回项 | 权威来源与读取方式 |
| --- | --- |
| 正文 | 子模型 claim 完整存入不可变对象；信封含 content_ref/digest/chars |
| 默认摘要 | 子模型 summary，最多 1200 字符；没有摘要时短正文完整返回，长正文明确标为 exact_excerpt，不假装语义摘要 |
| 覆盖与缺口 | 子模型 goal_coverage/evidence_refs/remaining；来源须在委派范围内，缺口由主模型处理 |
| 元数据 | 全部子 Attempt 的公开供应商报告、原始 Usage 扩展、响应引用、Runtime 实测毫秒；隐藏推理与凭据不入交接 |
| 流程 | 固定版本信封、依赖/替代关系、子检查点、父模型/工具收据 |

agent.result(delegation_id, field, offset, max_chars, expected_digest) 回读 content、metadata 或 trace；每页最多 6000 字符，返回 next_offset、总长度、摘要及来源引用。只允许本 Run 已结算结果，跨 Run 与版本错配拒绝。全文和元数据不会为了上下文预算而从权威对象中截断。

主模型默认接收有界结果；旧观察沿用共同折叠/回读，经验可按预算裁剪，路由仍查询持久评分。拒收正文从默认投影移除，身份、评分、费用和审计回读保留。全文、摘要、审核意见是不同事实，模型不得拿摘要当完整验收。

## 评分与学习

agent.evaluate 明确填写三项 0–100 分、accepted/failure_kind/reason、主判断 capability_tier、metadata_verdict 和固定 metadata_digest。内容采用与元数据采信独立：可以拒收答案同时采信费用，或采用内容而标记计量 incomplete/disputed。每个任务只记一次评分，仍是 **model_judgment**，不升级成独立 Verification。

- 主模型可指定低初值槽位检验能力；默认选择满足当前判断的最低能力候选，同档稳定排序。
- 经验绑定提供方、模型、窗口、Thinking、温度、步数及实际输出额度。读取最近 200 条评分，同类别取最近 5 条；主判断覆盖初值，较易任务质量失败也限制更难任务，难题失败不直接否定简单任务。
- 同类拒收/均分低于 70 避开该配置，可选另一同档模型；无可用模型由主模型完成。上下文/运行故障不作为能力评价，已知不可用槽位本轮排除。关闭学习则按初值路由。
- 所有返回子任务须评分；拒收后必须用 replaces 重派并采用替代结果，或 agent.resolve 保存主模型独立补做的正文与来源，才能停止。

这是有界类别经验规则，没有模型训练、向量语义相似检索或自动策略 Promote。

## 花销与故障

Token、缓存/推理统计及厂商扩展由响应提供；耗时由 Runtime 在 invoke 边界实测，含网络/排队/生成，不能冒充 TTFT 或纯推理时间。缺测保持未报告，不由主模型补数字。元数据可完整回读，审核绑定报告摘要，不能重写收据。

费用按配置的每百万 Token 单价估算；USD/CNY 分开，不计缓存折扣，不是账单或现金预算。每个 Attempt 只计一次，父工具不重复计价。执行图保存全部已发生估算和已审核/待审核/有争议分项；拒收、失败、重派及评分费用均保留。无价格或用量时金额未知，审核通过也不能把缺测变零。厂商金额等扩展保留在报告，当前不猜测非标准字段的账单口径。

零派发断线保留原合同，使用父持久重连调度；已知终结失败交回主模型。Ticket 后无确定收据的异常（包括 ValueError）进入 UNKNOWN，先核对，不能换模型绕过。Pause/Stop 影响未来安全点，已有调用仍记录。模型完成但游标/父工具未提交时，恢复只消费已有收据和固定输入，不请求 Provider。子检查点对象先发布、事件 CAS 后提交；崩溃可留无引用准备对象，不留部分游标。

实现：adapters/delegation.py 固定合同与审核，adapters/subagent_runtime.py 装配共享引擎视图，platform/handoff.py 做纯投影；父 Workspace 仓储拥有检查点/评分，platform/observability.py 投影图与费用。

验证：test_subagent_handoff.py、test_model_pool.py、test_delegation_boundaries.py 覆盖大正文、公开元数据、共享子步骤/Compact、Pause、重连、收据间崩溃、顺序/依赖/替代、经验与成本；另有全量 Python/Node、浏览器及安装包 HTTP 检查。替身不能证明真实账号质量或实际账单。

2026-10-05 本机记录：main 04a7f2a 起点；Python 3.13 全量 458 项（跳过 1 项，其余通过），Node 35 项通过，中文说明/凭据扫描通过。v0.26.0 wheel/sdist 内容及安装后 HTTP 检查通过。浏览器验证三槽位均可配强模型、无槽位标题、步骤参数保存/刷新、390px 双主题无横向溢出，以及拒收后的补做、评分/元数据审核和费用投影。设计扫描的奶油配色/旧输入指示器保留既有产品约束，未借本次修改重设计其他页面。

Usage 结构依据：[DeepSeek Responses](https://api-docs.deepseek.com/guides/responses_api/)、[Claude Messages](https://platform.claude.com/docs/en/api/messages/create)、[Kimi Chat Completions](https://platform.moonshot.ai/docs/api/chat)。
