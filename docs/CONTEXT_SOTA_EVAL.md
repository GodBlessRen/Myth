# Context SOTA Evidence · 可复现四组对照

## 目标与证据层次

Model-Aware × Relevance-Aware × Causality-Aware 属于 Myth 通用 Context Engine。它们的实现必须同时通过三个互相独立的门禁：

1. **Runtime 安全**：Ticket 之前的超限拒绝；UNKNOWN 只能以权威 Receipt 核对；Causal Active Set 不压掉必要依赖；实际工具副作用不重复。
2. **真正的同题对照**：同一 suite、同一 Provider+Model、同一固定配置；使用不同临时持久 Workspace，真实运行 4 种 Harness 变体并用独立 Oracle 检查 Artifact/Tool/答案。
3. **成本与质量可靠性**：以每次 Model Attempt 的 Provider/Adapter 回传为准；缺测 Token、cache、时延绝不补零；分开记录用户可验收结果、成本向量、重复调用与未结算风险。

本目录中的 scripted Benchmark 只验证门禁 1 和门禁 2 的管线。**它不证明真实模型更可靠、更省钱或达到 SOTA。**

## 四组实验

| Arm | Compaction / Observation Recall / Action Fusion | Causal Guard | Relevance Ranking |
| --- | --- | --- | --- |
| `context-baseline` | 相同且开启 | 关闭 | 关闭 |
| `context-causal` | 相同且开启 | 开启 | 关闭 |
| `context-relevance` | 相同且开启 | 关闭 | 开启 |
| `context-full` | 相同且开启 | 开启 | 开启 |

真正的开关来自 `Workspace(evaluation_harness_mechanisms=...)`，在每个 Turn 准入时冻结到 Snapshot，再被 Context Compiler 使用。不是只换一个 Harness 名字。每个请求记录 `context_activation`、`run_ids`、唯一 Model Attempt、收据与 Request 对象。额外的 `context_ablation.pairs[*].mechanism_config_verified_in_requests` 检查组态是否被真实编译。

四个 Arm 在每个 case / repeat 内轮换执行顺序，避免固定让某一个版本总是先跑。**这不等于随机盲测或证明消除了远端时序/缓存偏差。**

## 一键复现（不需要密钥）

从仓库根目录，先安装 `python -m pip install -e .`。

```bash
# Discovery 全部十题 × 四组；替身 Token 是 fixture，不是 Provider 真实计量
python -m myth.cli task-benchmark --context-ablation --repeats 1 --output .runtime/benchmarks/context-discovery

# 独立声明的 heldout 七题 × 四组；仍是 scripted Fixture，不是实质模型盲测
python -m myth.cli task-benchmark --context-ablation --suite evals/context-heldout-v1.json --repeats 1 --output .runtime/benchmarks/context-heldout-fixture
```

`report.json` 与 `suite.json` 原子持久化到新目录；每个 Arm/题号/重复试次保留独立 SQLite、Ticket、Receipt、Context、Model Request/Response 与 Artifact 字节。CLI 筛题仍标记 `complete_suite=false`；断开/异常保留失败项。

## 真实模型 A/B

真实 Provider 仅在操作者**显式运行**时发起计费调用。使用固定的 Provider ID/准确模型名。例子（环境变量由当前 Myth 安全凭据解析）：

```bash
# 真实本地 Ollama
python -m myth.cli task-benchmark --context-ablation --provider ollama --model YOUR_INSTALLED_MODEL --repeats 1 --output .runtime/benchmarks/ollama-context-discovery

# 使用已配置 API Key 的真实远端 Provider
python -m myth.cli task-benchmark --context-ablation --provider openai --model YOUR_EXACT_MODEL --repeats 1 --output .runtime/benchmarks/openai-context-discovery

# 分开的测试集；不要用这些结果迭代同一候选后，再称其为“未见过”的 heldout
python -m myth.cli task-benchmark --context-ablation --suite evals/context-heldout-v1.json --provider openai --model YOUR_EXACT_MODEL --repeats 1 --output .runtime/benchmarks/openai-context-heldout
```

亦可在合并到 `main` 后从 GitHub Actions **Context A/B (real provider, opt-in)** 手动运行。只有手动 `workflow_dispatch` 才会请求收费模型；只允许从 `main` 发起；需预先配置匹配 Provider 的 GitHub Actions Secret。工作流对缺失 Secret、无效 Provider/模型在启动计费试次前显式拒绝。为了避免泄露原始模型输入/凭据，Action 只上传 `report.json`/`suite.json`，完整收据证据要在受信本地运行并自行保存。

真实运行可能产生费用；7 题 × 4 Arm × 重复次数，每次最多 `max_steps=6` 次模型调用，跨 Goal 场景还包括前置轮次。建议先单题筛查，再执行完整 Discovery 和独立 Heldout；单题结果不具备发布资格。

## 结果语义

- `summary`：每组 pass@k、pass^k、失败分类、覆盖分母。
- `context_ablation.pairs`：同题同次的四种变体结果；baseline/full 的通过-失败翻转；只有两边都报告成本时才有配对 delta。
- `context_ablation.quality`：improved / regressed / both_pass / both_fail；**不是**文学、开放问答的语义质量统计。
- `context_ablation.safety`：新增 UNKNOWN、人类接管和更多重复工具调用风险；重复调用并不必然等于重复副作用，但需要人工检查。
- `context_ablation.cost`：所有配对均有 Provider/Adapter 计量时才计算总 input/output tokens、provider wall time 的差额；缺测时总差额为 `null`，保留 `paired_samples`。
- `context_ablation.ready_for_separate_heldout_review`：仅在真实 Provider、完整四组每组均有可归属的有效调用/成本证据（并至少一题真实启用 Context）、full Arm 在固定集合上全部通过独立 Oracle、无质量/安全回退、共同实测成本全部不恶化且至少一项改善时才可能为真；它仅意味着**可以进入独立 Heldout 复核**。
- `context_ablation.promotion_eligible`：**恒为 false**；该小集合没有权威自动发布资格。发布必须复用 Myth 的显式 Evaluation/Policy Promote 治理，不能绕过用户授权。

`Provider` 的 `input_tokens` 是派发后计量，不是预调接口的精确 tokenizer。当前 Context 预算继续使用保守软字节预算；`context_cost_calibration` 是实测历史比例，不能据此无条件扩容。若真实 Token 窗口预检仍缺测，必须保持原 fallback。

## FRAMEBREAKER · 冻结态模型材料反证

先前四臂 Context 实验只证明配置生效，不能证明开关在当前任务里真的改变了
模型可见信息。现在每次**实际模型决策前**，仅对四臂实验在**同一 State、
Settings、Activities、Control** 上进行四次纯 Context 编译（影子编译），
比较去掉本地 `context_report` 后的规范模型请求 SHA-256。

- `context_activation[].material_probe` 保存四臂摘要、实际 Arm 一致性及四方向差分；不保存额外 Prompt 原文，不派发影子请求，也不创建 Ticket/Receipt。
- `context_ablation.falsification.frozen_compiler_materiality` 按模型机会统计观测覆盖、无差异机会，以及按**独立 Case**去重的 Causality/Relevance 材料变化。影子编译失败为 `UNVERIFIED`，不妨碍原正常执行。
- 原始请求对象由内容寻址仓库存放。离线复核可重新计算**实际请求**的模型可见摘要并检查报告自洽；其他三份反事实请求摘要仍属于本机 Compiler 记录，非可独立核对的 Provider wire capture。
- 本阶段**不修改** `ready_for_separate_heldout_review` / Promote 条件；`material_intervention_verified` 仍为 `null`，`causal_attribution=false`。观察到请求字节变化，不代表该变化改善独立任务 Oracle，更不意味着确认神经元因果解释。

由此可以识别「开关打开但输入没变化」的空干预，以及真正改变请求材料的 Case，
下一阶段应据此筛选最有辨别力的真实 Provider 配对实验，而不是扩大样本量掩盖空干预。

## The Last Mile：Case-Clustered 与双阶段复核

单次 `input_tokens` 下降不再足以通过研究候选门槛。`context_ablation.paired_significance` 将同一 Case 的全部重复试次视作**一个**比较单元，事先指定 `input_tokens` 为唯一显著性主指标，使用单侧精确符号检验（Exact Sign Test）：

- 每个 Case 必须有三次及以上完整的四 Arm 配对；至少六个非平手 Case；
- 单侧 `p <= 0.05`，且候选在聚合成本向量上 Pareto 不劣；
- 独立 Oracle 的 Full Arm 必须全部通过，不得出现新增 UNKNOWN / 接管 / 重复工具调用；
- 同 Case 的多次重复**不能**冒充多个独立 Case；测试仅假设不同 Case 近似独立。若实际任务高度相关，显著性不能直接推断到新任务。

完成两个真实 Provider 目录后，使用以下**只读**命令复核：

```bash
# 分别运行完整 Discovery 和声明的 held-out；推荐 repeats>=3
python -m myth.cli task-benchmark --context-ablation --provider ollama --model YOUR_PINNED_MODEL --repeats 3 --output .runtime/benchmarks/discovery-real
python -m myth.cli task-benchmark --context-ablation --suite evals/context-heldout-v1.json --provider ollama --model YOUR_PINNED_MODEL --repeats 3 --output .runtime/benchmarks/heldout-real

# 只读取目录中的 suite.json、report.json、每个 Trial 的 .runtime 证据目录；不调用模型。
python -m myth.cli task-benchmark-review --discovery .runtime/benchmarks/discovery-real --heldout .runtime/benchmarks/heldout-real
```

复核重新计算每组成本、逐次对照和统计量，核对 Suite 内容摘要、Case 全格覆盖、源码摘要、Provider/模型/设置、声明的分区以及两组 Case 不相交。它还以只读 SQLite 打开每个 Trial 的 `runtime.db`，核对 Run 状态、模型 Ticket、已结算模型 Attempt、`model-receipts/` 收据、请求/响应 SHA-256 对象、实际冻结的 Context 开关，以及 Token/耗时聚合；仅有一个空 `.runtime` 目录不足以通过。对于 Ollama，还要求两边模型权重 digest 可读取且相同。缺失、篡改或成本分母不完整时 `HOLD`（CLI 退出码 1）；条件全部满足时为 `READY_FOR_MANUAL_REVIEW`（退出码 0），**不执行 Promote，`promotion_eligible=false`**。

公开 held-out 题不等于秘密盲测；现有报告目录可被拥有写权限者整体改写，SHA-256 不是数字签名。对 ChatGPT / OpenAI 等没有稳定权重 digest 的托管模型，复核会保持 `HOLD`，直至模型版本能通过独立可信证据确定。即便 Runtime 原始对象、Receipt 和 SQLite 彼此一致，也不等于外部 Provider 真实身份或计费记录已获第三方独立认证；拥有整个目录写权限的人仍可同时伪造这几份本地证据。此步骤只提升**工程可审查性**，不宣称已证实跨模型、跨任务或跨时间的 SOTA。

## SOTA-LEVEL 的真正晋级条件

候选必须在多个真实 Provider/固定模型版本上，经过版本固定的 Discovery 与独立、未用于调参的 Final 数据集，提供每个 Case/Arm/Repeat 的原始证据、足够样本数量、置信区间或有解释的统计不确定性、任务质量不下降、成本/延迟 Pareto 不劣、缓存覆盖完整，以及故障注入后 UNKNOWN 无盲目重试的实测记录。

若没有 Provider Credential、模型版本记录、人工语义验收或足够独立样本，报告结论只能是 **ENGINEERING VERIFIED / SOTA UNPROVEN**，不得将成功的模拟实验或漂亮的单次运行升级为 SOTA 冠军。
