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

当前执行**单层、有界并行**。`agent.delegate` 用于一个子任务；多个互不依赖的任务一次调用 `agent.parallel`，最多三个工作线程，各自装配数据库连接与供应商，父游标在汇合点等待一次。三个槽位是候选配置上限，同一配置也可承担三个独立任务；不代表整个 Runtime 的全局线程上限。

```json
{"tasks":[
  {"task":"核对材料 A","context":"材料 A","profile_id":"slot-1"},
  {"task":"核对材料 B","context":"材料 B","profile_id":"slot-2"},
  {"task":"核对材料 C","context":"材料 C","profile_id":"slot-3"}
]}
```

输入全部校验后，父批次及所有子工具 Ticket 一次短事务准入；三项批次占四个工具额度，任一准入失败整体回滚，模型尚未派发。模型和输入工具仍使用父预算，写事务只串行提交账本，网络调用不持有数据库事务。无可用模型的项明确回退主模型；返回结果逐项审核，评分完成前不提示继续扩张新批次。

每项保持稳定 delegation_id、父步骤 sequence、批次 batch_id 和 ordinal。结果按 `(sequence, ordinal)` 汇合，不按到达先后拼接。depends_on 仍只能引用主模型已经采用的旧结果，依赖任务须待审核后另行派发；拒收用 replaces 重派或主模型补做。单层仍禁止子模型递归。

一次未中断的批次等待约为 `max(t1,t2,t3) + 装配/汇合开销`；整体任务还包括主模型派发、审核和汇总。批次汇合等待期间父模型不另开规划游标。当前无需异步 Future ID、轮询模型或在主上下文注入到达顺序。

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

并行批次默认每项最多 300 字符摘要导航，共同 Context 编译器可再折叠到 100 字符，并明确 summary_truncated。完整摘要可用 agent.result(field=trace) 回读，正文/公开元数据各有不可变对象；裁剪不表示完整验收。主模型默认接收有界结果；旧观察沿用共同折叠/回读，经验可按预算裁剪，路由仍查询持久评分。拒收正文从默认投影移除，身份、评分、费用和审计回读保留。全文、摘要、审核意见是不同事实，模型不得拿摘要当完整验收。

## 评分与学习

agent.evaluate 明确填写三项 0–100 分、accepted/failure_kind/reason、主判断 capability_tier、metadata_verdict 和固定 metadata_digest。内容采用与元数据采信独立：可以拒收答案同时采信费用，或采用内容而标记计量 incomplete/disputed。每个任务只记一次评分，仍是 **model_judgment**，不升级成独立 Verification。

- 主模型可指定低初值槽位检验能力；默认选择满足当前判断的最低能力候选，同档稳定排序。
- 经验绑定提供方、模型、窗口、Thinking、温度、步数及实际输出额度。读取最近 200 条评分，同类别取最近 5 条；主判断覆盖初值，较易任务质量失败也限制更难任务，难题失败不直接否定简单任务。
- 同类拒收/均分低于 70 避开该配置，可选另一同档模型；无可用模型由主模型完成。上下文/运行故障不作为能力评价，已知不可用槽位本轮排除。关闭学习则按初值路由。
- 所有返回子任务须评分；拒收后必须用 replaces 重派并采用替代结果，或 agent.resolve 保存主模型独立补做的正文与来源，才能停止。

这是有界类别经验规则，没有模型训练、向量语义相似检索或自动策略 Promote。

## 花销与故障

Token、缓存/推理统计及厂商扩展由响应提供；耗时由 Runtime 在 invoke 边界实测，含网络/排队/生成，不能冒充 TTFT 或纯推理时间。子调用累计耗时仍可相加，批次 parallel.wall_ms 则是当前 Driver 执行片段的实测等待（wall_ms_scope=current_driver_segment），不能冒充跨断线/重启的总历时；仅凭收据恢复时保持未报告。缺测保持未报告，不由主模型补数字。元数据可完整回读，审核绑定报告摘要，不能重写收据。

费用按配置的每百万 Token 单价估算；USD/CNY 分开，不计缓存折扣，不是账单或现金预算。每个 Attempt 只计一次，父工具不重复计价。执行图保存全部已发生估算和已审核/待审核/有争议分项；拒收、失败、重派及评分费用均保留。无价格或用量时金额未知，审核通过也不能把缺测变零。厂商金额等扩展保留在报告，当前不猜测非标准字段的账单口径。

零派发断线保留原合同，使用父持久重连调度；已知终结失败交回主模型。Ticket 后无确定收据的异常（包括 ValueError）进入 UNKNOWN，先核对，不能换模型绕过。Pause/Stop 影响全部子游标未来安全点，已有调用仍记录；父 Turn 已终止后，子安全点仍核对持久 Stop。兄弟子调用各自收据落定后才上交父恢复，已成功项不重跑。模型完成但游标/父工具未提交时，恢复只消费已有收据和固定输入，不请求 Provider。子检查点对象先发布、事件 CAS 后提交；崩溃可留无引用准备对象，不留部分游标。

实现：adapters/parallel_delegation.py 拥有有界派发/汇合，adapters/delegation.py 固定合同与审核，adapters/subagent_runtime.py 装配共享引擎视图，platform/handoff.py 做纯投影；父 Workspace 仓储拥有检查点/评分，platform/observability.py 投影图与费用。

验证：test_parallel_delegation.py 使用真实账本和可控 Provider，覆盖三个同时在途、乱序交接、同模型并发、共享预算竞争、全部 Ticket 回滚、多步兄弟恢复隔离、Pause/Stop、收据间崩溃、只重试失败项、UNKNOWN 不重发、长正文导航及主循环逐项审核。既有模型池/交接/控制/恢复回归与全量 Python/Node、发布包检查仍保留；替身不能证明真实厂商质量或排队延迟。

250/500/750ms 延迟替身对照通过同一 Runtime 比较串行三个工具与一次并行工具；测试用三方屏障证明重叠，不用易受机器负载影响的墙钟阈值代替并发正确性。计时结果与当前版本全量验证保存在本机 output/parallel-python-tests.log。

v0.27.0 本机 Python 3.13 全量 478 项（跳过 1，其余通过）、Node 35 项通过；编译、中文说明、凭据扫描、发布包和安装后 HTTP 通过。最后一轮延迟替身实测串行 1806ms、并行 911ms（批次片段 890ms），等待减少约 50%；这是本机调度对照，不是厂商生成速度承诺。

Usage 结构依据：[DeepSeek Responses](https://api-docs.deepseek.com/guides/responses_api/)、[Claude Messages](https://platform.claude.com/docs/en/api/messages/create)、[Kimi Chat Completions](https://platform.moonshot.ai/docs/api/chat)。
