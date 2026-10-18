# Context Governance：模型、相关性与因果证据

## 目标与事实边界

Context 是按预算给模型的**派生投影**；Run、Action、Attempt、Ticket、Receipt、Verification、Memory revision、文件/项目版本仍由原仓储拥有，不能由摘要修改。

Myth 目前采用三个互补维度：

1. **Model-Aware**：本地使用冻结的 `num_ctx`；远端 Web Send/Goal Schedule 只冻结有明确 Provider 来源、精确模型身份的公开窗口；adapter 按型号前缀推测的能力标记为 adapter-family-rule，不冒充供应商报告。仅来源通过双重核对时使用保守 UTF-8 预算 `min(256000,window-output-512-2048)`，否则退回 42,000 字节。Token/字节边界并非 Provider tokenizer 的精确计量，额外的协议包装仍可能增加 Token。
2. **Relevance-Aware**：仅对已通过来源/作用域准入的 Knowledge 与 Memory 计算有限长度的任务词面覆盖率，并采用同一可比优先级；相关性只决定候选顺序，不改变 `fact_level`、来源真实性、权限和执行状态。显式附件仍为 required。
3. **Causality-Aware**：Context 以 Causal Active Set（因果活跃集）为核心：同 Run 未结算的 Tool/Model Attempt、Recovery Cursor、UNKNOWN 资源占用和显式依赖链属于不可静默丢弃的工作集；已知终态失败只保留最近 8 项导航及其依赖闭包，较旧的历史提示写入带 digest 的归档计数，完整活动仍属于权威仓储。模型自述或事件先后不提供新的因果证明。

## 权威记录与投影关系

```text
SqliteWorkspaceRepository / DecisionRuntime / Core Runtime  [authoritative]
                      |
                      v
ConversationExecution.decide()   [recorded step, decision, dependencies]
                      |
                      v
Context Governance (pure)       [critical status / provenance / relevance]
                      |
                      v
Context Compiler                [required first / budget / selected+folded+dropped]
                      |
                      v
ModelRequest + Context Report   [bounded projection, not permission]
```

- 来源明确：活动 `state`、`result.failure`、`result.status`、`result.results` 与委派 `handoff.depends_on` 来自本轮已持久化/已核对的步骤投影。
- 显式依赖来自已记录的决定或交接合同。缺失的上游身份列在 `causal_missing_dependencies`，不据此编造前驱。
- TICKETED/UNKNOWN/PENDING/BLOCKED/INCONCLUSIVE 作为开放风险始终保留；已知 FAILED/ERROR/REJECTED/CANCELLED 作为历史问题只保留最近 8 条导航。较旧的问题不是“已修复”，只是离开 provider-visible 工作集，完整历史仍保存在原仓储。被活跃风险显式依赖的历史问题不会因为年代久远而退出闭包。
- 若旧工具步骤的结果仍写着 UNKNOWN，但同 Run 的工具操作账本已具有 RESOLVED 和持久结果，投影标记为 `historical_tool_report:UNKNOWN` 和 `runtime_tool:RESOLVED`；这只解除效果是否已结算的警报，**不代表语义验收成功**，也不用于清除并行子委派的独立 UNKNOWN。
- 完整 Observation 继续使用现有 `observation.read` 只能按 decision_id 精确回读**已结算**的工具 Observation；未结算 UNKNOWN 必须依据原 Runtime Ticket/Receipt 核对，不能凭摘要触发回放。Context Guard 不重新保存大对象、不重放外部效果。
- 无前端/供应商变化可以扩大 Capability、Ticket、作用域或完成验收。

## 控制实验

`FoundationEvalRunner` 现在真实支持以下增量消融开关：

| Harness mechanism | 关闭后具体行为 |
| --- | --- |
| `context_causal_guard` | 不额外生成关键状态 Guard；Runtime 本身的执行安全协议保持 |
| `context_relevance_ranking` | Knowledge 恢复旧 20,000 优先级、Memory 恢复旧 1,000 优先级 |

它们和既有 `context_compaction`、`observation_recall`、`action_fusion` 可以形成 full / one-mechanism / leave-one-out 变体。生产模式（没有 Evaluation 注入时）默认两者都启用。仅从变体标签不能推断已经产生效益：必须记录完整任务、实际启用效果、可验收产物、总费用、剩余恢复债务、Provider 真实用量、模型上下文缓存命中与失败案例。

需要的固定实验包括：

- 无关 Knowledge 与相关 Memory 的预算竞争；
- 长任务压缩时的 UNKNOWN、已知失败、跨步骤显式依赖与并行子结果；
- 同 Run 中途模型切换：旧 Profile 不得扩大新模型窗口；
- 崩溃/重启/晚到收据：不因 Context 优化重复外部效果；
- 多次不同模型、同条件 baseline，统计质量、Token、时延与重复轨迹的分布；
- 有真实用户效果的反事实对照：移除某来源是否引起下一步决策或独立验收退化。

## 当前明确限制

- 这是 **deterministic causal evidence guard**，不是因果发现算法或已证明的 SOTA；对显式依赖图的覆盖取决于上游确有持久记录，不能从相邻步骤猜测因果边。
- 词面覆盖率不是语义检索、学习的效用估计或因果效应。长期应在独立固定任务集上检验它与交叉编码器/Embedding 的质量和开销权衡。
- 当前只将特别重要的执行导航作为 required，不自动将所有 Memory 标为权威事实；超大最新 Observation 和用户本轮必需输入仍可能在模型请求前触发显式预算拒绝。
- 远端 Profile 来自预检声明，可能过时或不完整；实际 Context Token 占用仍需 Provider 侧测量。网页绕过预检、离线夹具或模型身份变更则保守降级。
- 当前缺少真实远端 Provider 和长期任务的完整对照测量；CI PASS 只能证明固定回归，没有资格宣称已经达到 SOTA。

## 工程验收

单元回归：`python -m unittest discover -s tests -p test_context_governance.py -v`。

完整门禁和任务对照：见 `AGENTS.md` 与 `docs/TASK_BENCHMARK.md`。失败、缺测、UNKNOWN 必须记录，不能剔除分母；候选通过完整集后仍需 held-out 验证和显式 Promote。

## 固定机制消融：不以替身冒充真实模型实验

`evals/context-governance-v1.json` 现有七项可执行 ContextCompiler 检查，涵盖：未结算 Tool/预算、显式依赖闭包、Knowledge/Memory 选择、清洁状态阴性对照、预算耗尽 fail-closed。它们都是确定性 `0 model_calls` 的 **Harness Fixture**，只验证架构不变量与选择差异；不测真实回答质量、长时间运行或真实节约成本。

完整 Suite：
```bash
python -m myth.cli eval --suite evals/context-governance-v1.json
```

全关/单项/全开受控对照：
```bash
python -m myth.cli eval-controlled --suite evals/context-governance-v1.json --mechanism context_causal_guard --mechanism context_relevance_ranking
```

对照结果的 `prompt_bytes` 仅是实际编译的 UTF-8 字节，不是 Provider 报告的 Token；针对缺测或明确预算拒绝不填入伪造的 token 数。发布前仍必须在多模型真实 Provider 上运行固定 Task/held-out 集并配对比较成功率、总计费、时延和无盲重试不变量。

使用 `--record` 可以将四组 Discovery 结果写入本机 Evaluation Ledger 并生成逐题机制归因；未指定时只标准输出 JSON，不产生业务 Run、Ticket 或外部模型调用。命令不能把这个固定 Harness Fixture 升级成真实 Provider SOTA 证据。

## Causal Active Set v2：审计口径与停止条件

Guard 与 Inspector 分别暴露 `causal_active_risk_count`（开放效果/审核）、`causal_recent_issue_count`（最多 8 条近期已知故障）、`causal_archived_issue_count` 和 `causal_archived_issue_digest`（不属于已解决证明）。Guard 的 `critical_count` 是活跃风险 + 近期已知故障；其 `records` 还包含所有可确认的显式依赖祖先，故可能大于该计数。

硬约束不设置数量上限：当某 Run 的未结算执行状态超出 Context 预算时，编译失败并等待 Runtime 人工/自动核对，**绝不裁掉最老的 UNKNOWN 以腾出 Token**。归档只针对已知终态的历史提示，不能对没有受信运行收据的未知副作用使用时间窗口。

当前上下文窗口仍为保守 UTF-8 字节估计，而非 tokenizer 精确计数。SOTA 判定必须额外包含真实 Provider 的 `input_tokens`、缓存字段覆盖率、任务成功率、Latency、UNKNOWN Reconcile 无重复效果的跨模型 A/B；仅七道确定性 Fixture 通过不可作为领先证据。
