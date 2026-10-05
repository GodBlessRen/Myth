# 模型池

设置页配置一个主模型、最多三个子模型槽位。主模型决定是否委派，Runtime 按任务要求和历史反馈选择子模型；没有合适子模型则由主模型自行完成。

首版沿用**串行、单层、只读、单次生成**的隔离 worker。三个槽位是候选配置上限，不是三个并行线程。子模型只看到显式任务、上下文和来源，不继承主对话、工具、Memory 或写权限。

## 配置与使用

1. 在“设置 → 模型池 · 主模型”配置提供方与模型。
2. 添加子模型，填写模型名、轻量/标准/高能力档位。档位由用户设定，品牌不决定档位。
3. “生成参数与价格”可限制任务类别、输出 Token、Thinking 和本地窗口；不选类别表示全部适用。
4. 检查连接、保存设置。配置只影响后续 Turn，执行中的请求和路由合同保持不变。

API Key 按提供方共用，保存在系统凭据库。支持 Ollama、OpenAI、Myth ChatGPT OAuth、DeepSeek、Claude、Kimi；Claude/Kimi 新增适配器只做过协议替身验证。Claude 首版采用 Messages 强制结构化工具输出，Thinking 仅支持默认/关闭；Kimi 支持默认或 enabled/disabled。模型名称和可用性以账号目录为准。

主模型的委派提案示例：

```json
{
  "task": "从给定记录提取日期和负责人",
  "context": "仅本子任务需要的记录",
  "task_type": "extract",
  "difficulty": "easy",
  "expected_output": "日期、负责人及缺失项",
  "source_refs": []
}
```

类别为 general/extract/summarize/code/reason/review，难度为 easy/medium/hard。两者由主模型提出，本地校验。默认 general/medium。

## 路由与学习

```text
主模型任务提案 → 配置/类别/档位过滤 → 同类历史反馈 → 固定路由合同
  → 父工具 Ticket → 子模型 Ticket → 子模型收据 → 主模型评分 → 汇总
```

- 首先选择满足难度的最低档位；同档按稳定槽位 ID 排序。
- 读取最近 200 条已结算评分，按类别、难度、模型及生成配置匹配；换模型、窗口或实际输出额度不沿用旧评分。
- 最近同类质量评分未通过或均分低于 70，下次所需档位升到失败配置之上。最高档仍不合适则主模型接手。不会自动探索未配置模型。
- 上下文不足、基础设施错误不参与能力升级。已知调用失败的槽位在本轮不再选择；新 Turn 可重新尝试。
- 可以关闭反馈调整，恢复按手动档位路由；历史评分仍保留。此处是有界经验规则，不是模型训练、语义相似检索或自主修改策略。
- 剩余步骤不足以评分和汇总时不启动子任务。子调用仍受父 Run 的总 Token/调用预算约束，输出上限取子设置与父分配的较小值。

`agent.evaluate` 由主模型给正确性、完整性、可用性分别打 0–100 分，附 accepted、failure_kind 和理由。评分绑定本轮真实子结果的摘要、模型身份和 rubric 版本，每个子任务只记一次。完成守卫要求所有成功返回的子任务均已评分。**模型评分与独立 Verification 分开**；低分结果需要主模型修正或重新委派。

## 计量和执行图

子模型提供结果、覆盖范围、来源和未完成项。Runtime 从持久调用收据附加提供方、模型、Attempt、输入/输出 Token、实测毫秒及估算金额，模型正文不能填写计量。

费用 = `(input_tokens × 输入单价 + output_tokens × 输出单价) / 1,000,000`。价格按每百万 Token 配置，可选 USD/CNY，留空保持未知；未计缓存折扣，不是账单金额或现金预算。不同币种分开汇总；失败调用也计入。总费用按唯一模型调用统计，父工具包装收据不重复计价。主模型中途换成其他模型后，原模型单价不套用到新模型。

Execution Graph 显示父子调用、提供方、路由原因、Token、耗时、费用和评分关联。来源始终是持久调用/工具事实，不用模型文本补画执行事实。

## 故障与实现入口

已知未派发/已知失败可以交回主模型。派发后超时或断线进入 UNKNOWN，先核对；不能为“自动回退”把同一不明请求发给另一模型。子收据已写而父工具收据未写时，重启从原收据补结果，不再调用 Provider。

| 入口 | 职责 |
| --- | --- |
| `platform/model_pool.py` | 配置、路由、经验身份、估算价格 |
| `adapters/workspace_store.py` | 设置与评分操作的持久所有者、重复评分事务检查 |
| `adapters/conversation_execution.py` | 派发、收据元数据、评分参数校验及恢复 |
| `workspace.py` / `providers/messages.py` | 提供方装配 / Claude 与 Kimi 协议 |
| `platform/completion.py` / `observability.py` | 未评分完成守卫 / 执行图与总价投影 |
| `webui/model-pool.js` | 模型池配置表单，凭据单独进入认证接口 |

验证入口：`test_model_pool.py`、`test_messages_providers.py`、`test_delegation_boundaries.py`，以及全量 Python/Node、真实浏览器、wheel 静态资源与安装包 HTTP 验证。远端模型质量与实际账单仍需配置真实账号后测量。

2026-10-05 验证记录（基于 main `fea2e4a`，v0.25.0）：Python 全量 444 项、跳过 1 项，其余通过；Node 35 项通过；中文说明与凭据扫描通过。wheel/sdist 构建、发布内容检查及安装后 HTTP 验证通过。浏览器验证了三个槽位上限、保存/刷新、390px 双主题与无横向溢出，以及协议替身驱动的低分升级、评分、执行图费用汇总。以上不包含真实 Claude/Kimi 账户生成或质量评测。

协议依据：[Claude Messages](https://platform.claude.com/docs/en/api/messages/create)、[Kimi Chat Completions](https://platform.moonshot.ai/docs/api/chat)。
