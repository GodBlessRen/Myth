"""SOTA Semantic Contract 的本地证据回归：使用真实 SQLite + Memory 事务与冻结版本。

单元测试不证明远端事实正确、LLM 语义推断或真实 Milvus 质量；只有明示 JSON 结构的确定性约束被验证。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from myth.conversation import TOOL_CATALOG, validate_tool_arguments
from myth.platform.capabilities import default_capabilities
from myth.platform.memory_lifecycle import MemoryDeltaError
from myth.platform.semantic_contract import (
    evaluate_json_mapping,
    normalize_contract,
    value_violations,
)
from myth.platform.tool_discovery import search_tools, visible_tool_ids
from myth.runtime import MythRuntime
from myth.strategies.information_control import InformationControlAction, LiveInformationController
from myth.workspace import Workspace


# SemanticContractTests：外部调用只通过 Workspace.semantics 和 Memory 公共接口，保护真正的存储行为。
class SemanticContractTests(unittest.TestCase):
    # setUp：每例独立运行目录，SQLite 不共享 Revision、水位或 scope。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.memory = self.workspace.memory
        self.semantics = self.workspace.semantics

    # tearDown：关闭连接与目录，避免各用例交叉污染证据。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # _source：以明确 JSON 对象创建现有 Memory 来源；不发明第二种证据身份。
    def _source(self, document, *, ref="semantic:source", scope_type="global", scope_id=None):
        return self.memory.remember(
            kind="semantic",
            text=json.dumps(document, ensure_ascii=False),
            source_ref=ref, scope_type=scope_type, scope_id=scope_id,
        )

    # _contract：构造明确字段映射及有限约束，返回调用者可自主调整的结构。
    def _contract(self, source_ids, *, term="finance.net_revenue", unit="USD", minimum=0):
        return {
            "term_id": term,
            "definition": "Net revenue from the admitted structured source",
            "value_type": "number",
            "unit": unit,
            "mappings": [
                {"source_memory_id": source_id, "pointer": "/net",
                 "unit_pointer": "/currency" if unit is not None else None}
                for source_id in source_ids
            ],
            "constraints": [{"kind": "min", "value": minimum}],
        }

    # 已有 Memory revision 及单位来源即可得结构化数值，但绝不升级为 verified 或自动发布。
    def test_term_mapping_extracts_typed_value_without_fact_promotion(self):
        source = self._source({"net": 120.5, "currency": "USD"})
        proposed = self.semantics.propose(self._contract([source["memory_id"]]))
        self.assertEqual(proposed["status"], "ready")
        self.assertFalse(proposed["verified"])
        self.assertFalse(proposed["release_eligible"])
        self.assertEqual(proposed["fact_level"], "context")
        self.assertEqual(proposed["source_refs"], [f"memory:{source['memory_id']}@1"])
        value = self.semantics.evaluate("finance.net_revenue")
        self.assertEqual(value["status"], "resolved")
        self.assertEqual(value["value"], 120.5)
        self.assertEqual(value["unit"], "USD")
        self.assertFalse(value["verified"])
        self.assertEqual(self.semantics.resolve("finance.no_such_term")["status"], "not_found")

    # Evidence 版本失效后不自动沿用新值；明确 CAS 重提案才允许重新固定来源。
    def test_source_revision_change_requires_explicit_cas_rebinding(self):
        source = self._source({"net": 9, "currency": "USD"})
        contract = self._contract([source["memory_id"]])
        proposal = self.semantics.propose(contract)
        self.memory.apply_delta(
            source["memory_id"],
            [{"op": "replace_text", "text": '{"net":15,"currency":"USD"}'}],
            expected_revision=1,
        )
        stale = self.semantics.evaluate("finance.net_revenue")
        self.assertEqual(stale["status"], "stale")
        self.assertIsNone(stale["value"])
        updated = self.semantics.propose(contract, expected_revision=proposal["revision"])
        self.assertEqual(updated["revision"], proposal["revision"] + 1)
        self.assertIn(f"memory:{source['memory_id']}@2", updated["source_refs"])
        self.assertEqual(self.semantics.evaluate("finance.net_revenue")["value"], 15)
        with self.assertRaises(MemoryDeltaError):
            self.semantics.propose(contract, expected_revision=proposal["revision"])
        with self.assertRaises(MemoryDeltaError):
            self.semantics.propose(contract)

    # 有作用域来源不允许升级成 global term；同项目定义也不能跨项目或匿名读取。
    def test_private_source_cannot_become_global_mapping_or_leak(self):
        source = self._source(
            {"net": 7}, ref="semantic:project-only",
            scope_type="project", scope_id="p1",
        )
        contract = self._contract([source["memory_id"]], unit=None)
        with self.assertRaisesRegex(MemoryDeltaError, "narrower scope"):
            self.semantics.propose(contract)
        good = self.semantics.propose(contract, scope_type="project", scope_id="p1")
        self.assertEqual(good["status"], "ready")
        self.assertEqual(self.semantics.resolve("finance.net_revenue")["status"], "not_found")
        self.assertEqual(self.semantics.resolve("finance.net_revenue", project_id="p2")["status"], "not_found")
        self.assertEqual(
            self.semantics.evaluate("finance.net_revenue", project_id="p1")["value"], 7,
        )
        self.assertEqual(self.semantics.browse("net", project_id="p2")["terms"], [])
        self.assertEqual(self.semantics.browse("net")["terms"], [])
        self.assertEqual(len(self.semantics.browse("net", project_id="p1")["terms"]), 1)

    # 多来源数值不一致时，不选择相似度高或排名靠前的值来冒充唯一真相。
    def test_conflicting_independent_mappings_fail_closed(self):
        first = self._source({"net": 12}, ref="semantic:a")
        second = self._source({"net": 13}, ref="semantic:b")
        contract = self._contract([first["memory_id"], second["memory_id"]], unit=None)
        self.semantics.propose(contract)
        resolved = self.semantics.evaluate("finance.net_revenue")
        self.assertEqual(resolved["status"], "conflict")
        self.assertIsNone(resolved["value"])
        self.assertEqual(resolved["reason"], "independent_mappings_disagree")

    # 类型、界限和单位都是可执行条件；布尔值不隐式当数字，超过界限拒绝产出。
    def test_type_constraint_and_unit_failures(self):
        wrong_unit = self._source({"net": 18, "currency": "EUR"})
        self.semantics.propose(self._contract([wrong_unit["memory_id"]]))
        checked = self.semantics.evaluate("finance.net_revenue")
        self.assertEqual(checked["status"], "invalid")
        self.assertIsNone(checked["value"])

        bool_value = self._source({"net": True}, ref="semantic:boolean")
        proposed = self.semantics.propose(
            self._contract([bool_value["memory_id"]], unit=None),
            expected_revision=1,
        )
        self.assertEqual(proposed["revision"], 2)
        self.assertEqual(self.semantics.evaluate("finance.net_revenue")["status"], "constraint_violation")
        self.assertEqual(self.semantics.evaluate("finance.net_revenue")["violations"], ["value_type_mismatch"])

    # 无效术语、违反默认事实等级的附加字段、坏 JSON Pointer 与矛盾阈值必须先于写入拒绝。
    def test_unknown_fields_selectors_and_impossible_constraints_are_rejected(self):
        source = self._source({"net": 4})
        contract = self._contract([source["memory_id"]], unit=None)
        for payload in (
            {**contract, "verified": True},
            {**contract, "term_id": "NoNamespace"},
            {**contract, "constraints": [{"kind": "min", "value": 10}, {"kind": "max", "value": 1}]},
            {**contract, "mappings": [{**contract["mappings"][0], "pointer": "/a/~2unsafe"}]},
            {**contract, "unit": "USD"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.semantics.propose(payload)
        self.assertEqual(self.semantics.resolve("finance.net_revenue")["status"], "not_found")

    # RFC6901 转义按纯数据路径解释；聚合只计算有界数组，不支持模型任意表达式执行。
    def test_rfc6901_pointer_and_finite_aggregates(self):
        source = self._source({"a/b": {"~name": [2, 3, 4]}})
        contract = self._contract([source["memory_id"]], unit=None)
        contract["mappings"][0]["pointer"] = "/a~1b/~0name"
        contract["mappings"][0]["aggregation"] = "sum"
        self.semantics.propose(contract)
        resolved = self.semantics.evaluate("finance.net_revenue")
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["value"], 9)
        normalized = normalize_contract(contract)
        self.assertEqual(
            evaluate_json_mapping({"a/b": {"~name": [2, 3, 4]}},
                                  normalized, normalized["mappings"][0]), 9,
        )
        self.assertEqual(value_violations(float("inf"), normalized), ["value_type_mismatch"])

    # 普通 Memory 修改不能偷偷把一个合法 term 的证据换成新 Mapping 而不更新引用。
    def test_contract_document_tampering_is_not_accepted_as_authoritative(self):
        source = self._source({"net": 3}, ref="semantic:tamper-source")
        contract = self._contract([source["memory_id"]], unit=None)
        initial = self.semantics.propose(contract)
        root_id = initial["memory_ref"].split("@")[0].split(":", 1)[1]
        tampered = dict(contract)
        tampered["mappings"] = [{
            "source_memory_id": "mem_" + ("b" * 32), "pointer": "/net",
            "unit_pointer": None,
        }]
        self.memory.apply_delta(
            root_id,
            [{"op": "replace_text", "text": json.dumps(tampered, ensure_ascii=False)}],
            expected_revision=1,
        )
        checked = self.semantics.resolve("finance.net_revenue")
        self.assertEqual(checked["status"], "invalid")
        self.assertEqual(checked["reason"], "contract_identity_or_encoding_changed")

    # Agent 工具可发现但不默认占用系统 Prompt；真实执行仍经过现有 Ticket/信息预算。
    def test_semantic_tools_registered_deferred_and_budgeted(self):
        registry = default_capabilities()
        self.assertIn("semantics.resolve", registry.executable_ids())
        self.assertIn("semantics.browse", TOOL_CATALOG)
        self.assertNotIn("semantics.resolve", visible_tool_ids(TOOL_CATALOG, []))
        matches = search_tools(
            TOOL_CATALOG, {key: key for key in TOOL_CATALOG}, "semantics resolve",
        )
        self.assertIn("semantics.resolve", [item["capability_id"] for item in matches])
        validate_tool_arguments("semantics.resolve", {"term_id": "finance.net_revenue"})
        with self.assertRaises(ValueError):
            validate_tool_arguments("semantics.resolve", {"term_id": "finance.net_revenue", "verified": True})
        policy = LiveInformationController()
        self.assertEqual(policy.action_for("semantics.browse"), InformationControlAction.SEEK)
        self.assertEqual(policy.action_for("semantics.resolve"), InformationControlAction.EXPAND)
        self.assertIs(self.workspace.execution.semantic_catalog, self.semantics)


if __name__ == "__main__":
    unittest.main()
