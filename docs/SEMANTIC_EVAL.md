# Semantic Contract Evaluation · The Last Mile

这份评测衡量**可执行合同的可靠性增量**，不是使用真实 LLM 的知识问答排行榜。冻结数据文件：`evals/semantic-contract-v1.json`。它包含 **16 个独立 Case**，其中 10 个是拒绝危险/错误结果的安全用例；每一题在代码执行之前就固定 Oracle、源数据、映射和故障注入。

## 被测路线与公平性

| Arm | 给定的信息 | 真正执行的行为 | 刻意没有测量 |
| --- | --- | --- | --- |
| Bare selector baseline | 与候选完全相同的 JSON 来源、**相同的确切 JSON Pointer 和聚合操作** | 直接取值并在多来源时选首项；不验证来源 Revision、作用域/撤销、单位、约束 | 原始 Memory 检索召回率、LLM 选字段能力 |
| Semantic Contract candidate | 上述相同来源 + 明确声明、Memory 绑定的 Term/Mapping/Constraint | SQLite WAL 快照内核对版本/作用域/来源闭包；验证类型、单位、范围、多来源一致性，失败时拒绝提供值 | 独立事实真伪、LLM 理解、端到端用户满意度 |

选择这种**强字段选择器**作为基线，是为了不让模型知道字段名的差异混进质量对照。对比中的增益只归因于本模块新增的来源/约束校验，而不是营销意义的“Agent 准确率”。

## 固定研究协议

1. 在 `SemanticAblationRunner` 初始化时校验 Suite ID、版本、Case 身份、Oracle 形状与字段；计算 SHA-256，输出留存此身份。
2. 每个 Case 在**独立新建的真实 SQLite Workspace** 中建立来源、引用与 Semantic Contract。先建立声明，再应用指定的 revision 更新/撤销，防止“先看结果再换来源”。
3. 两个 Arm 在**同一来源状态**下运行，按固定 Seed 交替 AB/BA，默认每 Case 重复 3 次。统计时仍以 Case 为独立单位；重复只用于描述局部耗时。
4. 独立预期来自 JSON `expected`，Runner 不从输出推导期望。逐 Case 使用现成的 `EvalVerdict` 与 `EvalObservation`，错误/未执行不被删除。
5. 记录完整分母、PASS/FAIL、安全回归、候选胜负/平手、危险结果数；额外记录本机 warm-query `p50_ms/p95_ms` 与建模准备 `setup_ms`。这不是生产负载 p95。
6. **真实模型 Token、供应商价格、端到端 LLM 延迟均报告为 null**；离线脚本根本没有 Provider，不应把缺测伪装成零成本。报告不输出由这份基线无法证明的因果显著性或外部泛化胜率。
7. 两臂都能通过 `SqliteEvaluationLedger.record()` 保存到已有 `evaluation_runs/evaluation_observations`；强制 `evaluation_partition=discovery`、`release_gate.passed=false`，没有候选进入生产 `information_resolution` 控制器。

覆盖集：无约束数值，sum/avg/count，字符串/布尔枚举，min/max 违例，单位不匹配，bool→number 错误，双来源冲突，来源 revision 变化、撤销、上游依赖撤销，JSON Pointer 缺失，损坏 JSON。安全 Case 必须保留完整分母、记录错误发布和 `safety_regressions`。

## 复现命令

安装 Myth 后在仓库根目录执行：

```bash
python scripts/eval_semantic_contract.py --repeats 3 --seed 17 --output semantic-eval-result.json
python -m unittest discover -s tests -p 'test_semantic_evaluation.py' -v
```

脚本默认只在临时 SQLite 运行且向标准输出返回完整 JSON；指定 `--output` 时采用**禁止覆盖**的创建方式。显式传入 `--record-root ./research-workspace` 才会把逐题观测另存到该实验 Workspace 的 Evaluation Ledger；它不创建或发布策略。

筛选题只供诊断，`--case-id s01-scalar` 的退出码为 1 且 `complete_suite=false`。任意 candidate Case FAIL / 安全用例泄漏 / 结果不完整也必须非零退出。一次完整验证应保存 SHA、Case 输出、两臂成本字段、CI 精确提交哈希，不得只截图一个百分比。

## 下一阶段真实 Agent A/B 的资格边界

当真实 Provider 可用时，需要另一份**先冻结、独立采样的任务集**，再比较启用/隐藏 `semantics.browse` 与 `semantics.resolve` 的两条 Agent 路线。控制模型/思考档位、上下文、温度、工具权限、检索预算，固定来源/期望，不允许模型把 Oracle 看到。每 Case 多次交错随机运行，收集真实 Provider receipts 中的 `input_tokens/output_tokens/reasoning_tokens`、`cost`（缺项就是 null）、真实 `p95`、引用准确率、冲突识别率和完整结局。按**独立 Case 聚类**分析，不拿重复 trials 当样本量。候选不能降低安全 floor；无法独立判定的 Case 记 `INCONCLUSIVE`。

这份离线消融**不是**上述真实实验；它不能让 `Semantic Contract` 自动进入 Evolution Promote，也不能暗示比 EvoOntology/Hindsight/Semantica 更强。Myth 当前 Evolution Controller 只接纳 `information_resolution` 策略候选；扩展发布域必须另有充分业务需求和独立评测，而不是为演示新功能降低已有门槛。

**终局原则：Evidence 驱动改进；未测得的收益保持未知；小而深的模块比又一层抽象更可靠。**
