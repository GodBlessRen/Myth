# Semantic Contract：Evidence-pinned Term / Mapping / Constraint

Myth 将 EvoOntology 的可浏览术语/确定性映射、Semantica 的来源与约束、Hindsight 的 Memory Revision/Truth Maintenance 收敛为一个**小的深模块**。不是复制三套框架，也不是在 Runtime 内建立第二个知识图数据库。

## 运行边界

```text
operator / trusted local workflow   [write; explicit proposal only]
           |
           v
SemanticCatalog.propose (bounded canonical Term/Mapping/Constraint)
           |
           v
Memory.apply_actions ADD / UPDATE CAS
  + immutable Memory revision + Evidence source revision + scope
           |
           v
  SQLite authority / Truth Maintenance
           |
       read snapshot
           |
           +-- semantics.browse  [SEEK / discover bounded terms]
           |
           +-- semantics.resolve [EXPAND / deterministic typed JSON evaluation]
                    |
                    +-- pointer, aggregation, type, declared-unit check
                    +-- constraint + independent-source equality
                    +-- failure: invalid / stale / conflict / constraint_violation
```

**单一写入者：** SemanticCatalog 不直接更新 Memory 表、不建独立 schema、不创建另一套 revision/验证所有者。Memory 同事务拒绝来源作用域穿透、撤销、旧 revision、循环及预算不足。语义合同写入的是 `semantic` 用途、`context` 事实等级的 Memory；定义/映射与来自 JSON 的结果不是客观事实认证。

**纯语义：** `platform/semantic_contract.py` 只解析严格 `myth.semantic-contract/v1` 形状和有界 RFC6901 JSON Pointer，不执行 Python/SQL/正则表达式。类型为 `number/string/boolean`，数字不能从 bool 偷换；可执行有限数组的 `sum/avg/count`，支持 `min/max/enum` 约束。数字单位必须通过 `unit_pointer` 从结构化来源逐字相等验证；没有声明单位时不声称单位已验证。

**读模型：** 相同术语精确选择 `session → project → global`；更具体定义即使 stale 也不默默回退到另一个含义。读取使用同一 SQLite WAL 快照；若原始 JSON、Scope、Evidence、Revision 或 Mapping 不成立，工具返回拒绝状态，不产出新的数值。多来源结果不一致返回 `conflict`，绝不选择分数最高的一个冒充共识。

## 最小使用示例

```python
import json
from pathlib import Path

from myth.runtime import MythRuntime
from myth.workspace import Workspace

with MythRuntime(Path("./myth-operator-workspace")) as runtime:
    ws = Workspace(runtime)
    source = ws.memory.remember(
        kind="semantic",
        text=json.dumps({"net": 125, "currency": "USD"}),
        source_ref="operator:revenue-fixture",
    )
    contract = ws.semantics.propose({
        "term_id": "finance.net_revenue",
        "definition": "Net revenue from the explicitly admitted JSON source",
        "value_type": "number",
        "unit": "USD",
        "mappings": [{
            "source_memory_id": source["memory_id"],
            "pointer": "/net",
            "unit_pointer": "/currency",
        }],
        "constraints": [{"kind": "min", "value": 0}],
    })
    assert contract["fact_level"] == "context"
    result = ws.semantics.evaluate("finance.net_revenue")
    assert result["status"] == "resolved"
    assert result["value"] == 125
    assert result["verified"] is False
```

更改原始来源后，这条语义映射会因 Evidence 的 source revision 过期而失效。要明确重新绑定，受信操作者提供 `expected_revision=contract["revision"]` 重提案；CAS 冲突不会重放覆盖。普通模型**没有**写合同工具；对话里的 `semantics.browse` / `semantics.resolve` 通过原 Capability、Ticket/Receipt 和 SEEK/EXPAND 信息预算执行，工具采用按需发现以避免长期扩大 Prompt。

## 能力边界与验收

- 这不是通用本体推理器、自然语言 SQL 转换器、SHACL/OWL 引擎或因果识别系统；只支持**已经有结构化 JSON 来源**的显式 Term/Mapping/Constraint。
- 数值计算是确定性的，但 `resolved` **不等于** `verified`。合同状态本身不能替代 Verification、Eval Ledger、held-out 或 Evolution 的显式 Promote。
- 原始 Memory 仍可作为历史读取，scope-safe stale 被拒绝用于语义结果；不存在新证据时不可补造结论。
- `browse` 为至多 256 条当前合同记录的有界查询，报告 `exhausted`。这不是全库 Ontology Completeness 保证。
- 执行 `python -m unittest discover -s tests -p test_semantic_contract.py -v` 验证多来源冲突、CAS 幂等、scope、单位、类型和旧证据拒绝；发布需要在**同一 head SHA** 完成全量跨平台 CI、Browser 和 Release。
- 真实 Provider、远端数据库适配器、时态查询、性能/Token 基准及语义正确率仍未在这个模块里得到验证。

**离线固定任务对照已经落地**：见 [Semantic Contract Evaluation](SEMANTIC_EVAL.md)。同一 JSON Pointer 的裸选择器与带 Evidence/约束的合同在 16 个预先固定 Oracle Case 上作配对验证；离线结果不是实际 LLM 质量，未来仍必须按独立 Provider A/B 补真实 tokens/质量/生产延迟。原计划中的：在真实结构化 Memory 问答中比较有/无显式 Mapping 的事实错误率、证据引用、token、p95 延迟与冷启动成本；按已存在的 Evaluation 与人工 Promote 协议决定未来扩展。
