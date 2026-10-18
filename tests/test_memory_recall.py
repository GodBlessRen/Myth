"""多探针召回的安全边界：作用域、来源版本、预算及 fail-closed。

固定 SQLite Runtime 和模拟的检索路径，不把词面相关性冒充答案验证。
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.conversation import validate_tool_arguments
from myth.platform.memory_recall import build_recall_plan, parse_memory_ref, rank_probe_rows
from myth.runtime import MythRuntime
from myth.workspace import Workspace


# RecallContractTests：纯合同检查不需要启动数据库，必须拒绝不受限探针与输入提权。
class RecallContractTests(unittest.TestCase):
    # 回归 test_probe_normalization_and_deduplication：固定输入与可观察结果，不以模型自述取代验收。
    def test_probe_normalization_and_deduplication(self):
        plan = build_recall_plan(" Original ", probes=["original", "counterexample"])
        self.assertEqual(plan.queries, ("Original", "counterexample"))
        with self.assertRaises(ValueError):
            build_recall_plan("x", probes=["a", "b", "c", "d"])
        with self.assertRaises(ValueError):
            build_recall_plan("x", limit=True)
        with self.assertRaises(ValueError):
            build_recall_plan("x", required_refs=["memory:guess@1"])
        with self.assertRaises(ValueError):
            build_recall_plan("x", probes=(item for item in ["a"]))

    # 回归 test_rank_fusion_preserves_identity_and_does_not_claim_probability：固定输入与可观察结果，不以模型自述取代验收。
    def test_rank_fusion_preserves_identity_and_does_not_claim_probability(self):
        rows = rank_probe_rows([
            [{"memory_id": "a", "revision": 1}, {"memory_id": "b", "revision": 1}],
            [{"memory_id": "b", "revision": 1}, {"memory_id": "a", "revision": 1}],
        ])
        self.assertEqual({item["memory_id"] for item in rows}, {"a", "b"})
        self.assertNotIn("confidence", rows[0])

    # 回归 test_tool_contract_rejects_unknown_and_excessive_probes：固定输入与可观察结果，不以模型自述取代验收。
    def test_tool_contract_rejects_unknown_and_excessive_probes(self):
        validate_tool_arguments("memory.recall", {"query": "source", "probes": ["a"]})
        with self.assertRaises(ValueError):
            validate_tool_arguments("memory.recall", {"query": "x", "probes": ["a"] * 4})
        with self.assertRaises(ValueError):
            validate_tool_arguments("memory.recall", {"query": "x", "permission": "admin"})


# RecallStoreTests：每个用例只用独立 SQLite 工作区验证作用域、版本与失败原因。
class RecallStoreTests(unittest.TestCase):
    # 回归 setUp：固定输入与可观察结果，不以模型自述取代验收。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.memory = self.workspace.memory

    # 回归 tearDown：固定输入与可观察结果，不以模型自述取代验收。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 回归 test_anchored_multisearch_and_visibility：固定输入与可观察结果，不以模型自述取代验收。
    def test_anchored_multisearch_and_visibility(self):
        global_row = self.memory.remember(
            kind="semantic", text="ORBIT plan old", source_ref="source:orbit",
        )
        private_row = self.memory.remember(
            kind="episodic", text="ORBIT private", source_ref="source:private",
            scope_type="session", scope_id="session-a",
        )
        required = f"memory:{global_row['memory_id']}@{global_row['revision']}"
        self.assertEqual(parse_memory_ref(required), (global_row["memory_id"], 1))
        report = self.memory.recall_report(
            "no matching tokens", probes=["ORBIT plan", "ORBIT"],
            required_refs=[required], limit=2, session_id="session-b",
        )
        self.assertEqual(report["evidence_gate"]["status"], "anchored")
        self.assertFalse(report["evidence_gate"]["answer_verified"])
        self.assertIn(global_row["memory_id"], [x["memory_id"] for x in report["memories"]])
        self.assertNotIn(private_row["memory_id"], [x["memory_id"] for x in report["memories"]])
        self.assertEqual(len(report["retrieval"]["probes"]), 3)

    # 回归 test_revision_changes_fail_closed_and_do_not_mutate_history：固定输入与可观察结果，不以模型自述取代验收。
    def test_revision_changes_fail_closed_and_do_not_mutate_history(self):
        row = self.memory.remember(
            kind="semantic", text="Old decision", source_ref="source:revision",
        )
        ref = f"memory:{row['memory_id']}@{row['revision']}"
        before = self.memory.current_change_seq()
        self.memory.apply_delta(
            row["memory_id"],
            [{"op": "replace_text", "text": "New decision"}],
            expected_revision=1,
        )
        report = self.memory.recall_report(
            "decision", required_refs=[ref],
        )
        self.assertEqual(report["evidence_gate"]["status"], "references_unavailable")
        self.assertEqual(report["evidence_gate"]["invalid_refs"][0]["reason"], "revision_changed")
        self.assertFalse(report["evidence_gate"]["answer_verified"])
        self.assertEqual(self.memory.revision_snapshot(row["memory_id"], 1)["text"], "Old decision")
        self.assertEqual(len(self.memory.changes_since(before)), 1)

    # 回归 test_missing_and_revoked_anchors_are_explicit：固定输入与可观察结果，不以模型自述取代验收。
    def test_missing_and_revoked_anchors_are_explicit(self):
        missing = "memory:mem_" + "0" * 32 + "@1"
        initial = self.memory.recall_report("anything", required_refs=[missing])
        self.assertEqual(initial["evidence_gate"]["invalid_refs"][0]["reason"], "missing")
        row = self.memory.remember(kind="semantic", text="Visible fact", source_ref="source:revoke")
        ref = f"memory:{row['memory_id']}@1"
        self.memory.revoke(row["memory_id"])
        report = self.memory.recall_report("Visible fact", required_refs=[ref])
        self.assertEqual(report["evidence_gate"]["invalid_refs"][0]["reason"], "unavailable")

    # 回归 test_stale_linked_provenance_fails_even_if_revision_is_unchanged：固定输入与可观察结果，不以模型自述取代验收。
    def test_stale_linked_provenance_fails_even_if_revision_is_unchanged(self):
        source = self.memory.remember(kind="episodic", text="Time A", source_ref="run:a")
        derived = self.memory.remember(
            kind="semantic", text="Time A derived", source_ref="derived:a",
            evidence=[{"source_memory_id": source["memory_id"]}],
        )
        ref = f"memory:{derived['memory_id']}@1"
        self.memory.apply_delta(source["memory_id"], [
            {"op": "replace_text", "text": "Time B"},
        ], expected_revision=1)
        report = self.memory.recall_report("derived", required_refs=[ref])
        self.assertEqual(report["evidence_gate"]["invalid_refs"][0]["reason"], "stale_evidence")

    # 回归 test_no_required_sources_never_claims_verified_answer：固定输入与可观察结果，不以模型自述取代验收。
    def test_no_required_sources_never_claims_verified_answer(self):
        self.memory.remember(kind="semantic", text="Keyword candidate", source_ref="source:keyword")
        report = self.memory.recall_report("Keyword")
        self.assertEqual(report["evidence_gate"]["status"], "unverified")
        self.assertFalse(report["evidence_gate"]["answer_verified"])

    # 回归断言：候选在检索与出报告之间发生撤销，不得把旧命中当成当前权威记忆返回。
    def test_recall_hydration_rejects_candidate_changed_during_search(self):
        row = self.memory.remember(
            kind="semantic", text="Old recalled fact", source_ref="source:race-recall",
        )
        self.memory.revoke(row["memory_id"])
        stale_search = {
            "memories": [row],
            "retrieval": {"backend": "fixture", "matched": 1},
        }
        with patch.object(self.memory, "search_report", return_value=stale_search):
            report = self.memory.recall_report("Old recalled fact")
        self.assertEqual(report["memories"], [])
        self.assertTrue(report["retrieval"]["snapshot_validated"])
        self.assertEqual(report["retrieval"]["candidate_rejected_after_search"], 1)

    # 回归断言：普通候选即使 revision 未改变，底层来源更新也要阻止失效派生正文流回上下文。
    def test_recall_hydration_rejects_stale_linked_memory(self):
        source = self.memory.remember(
            kind="episodic", text="Source first", source_ref="source:linked",
        )
        derived = self.memory.remember(
            kind="semantic", text="Derived old", source_ref="derived:linked",
            evidence=[{"source_memory_id": source["memory_id"]}],
        )
        self.memory.apply_delta(
            source["memory_id"],
            [{"op": "replace_text", "text": "Source corrected"}],
            expected_revision=1,
        )
        with patch.object(self.memory, "search_report", return_value={
            "memories": [derived], "retrieval": {"backend": "fixture"},
        }):
            report = self.memory.recall_report("Derived old")
        self.assertEqual(report["memories"], [])
        self.assertEqual(report["retrieval"]["candidate_rejected_after_search"], 1)


    # 三跳链 A->B->C 中 C 的撤销必须使 A 在 Recall 阶段被拒绝，不得只检查直接 B。
    def test_transitive_revocation_invalidates_grandchild_recall(self):
        source = self.memory.remember(
            kind="episodic", text="deep source", source_ref="closure:source",
        )
        middle = self.memory.remember(
            kind="semantic", text="middle conclusion", source_ref="closure:middle",
            evidence=[{"source_memory_id": source["memory_id"]}],
        )
        derived = self.memory.remember(
            kind="semantic", text="final conclusion", source_ref="closure:derived",
            evidence=[{"source_memory_id": middle["memory_id"]}],
        )
        self.memory.revoke(source["memory_id"])
        fresh = self.memory.freshness(derived["memory_id"])
        self.assertTrue(fresh["is_stale"])
        self.assertEqual(fresh["stale_sources"][0]["reason"], "revoked")
        self.assertEqual(
            fresh["stale_sources"][0]["path"],
            [derived["memory_id"], middle["memory_id"], source["memory_id"]],
        )
        report = self.memory.recall_report(
            "final conclusion",
            required_refs=[f"memory:{derived['memory_id']}@1"],
        )
        self.assertEqual(report["evidence_gate"]["status"], "references_unavailable")
        self.assertEqual(report["evidence_gate"]["invalid_refs"][0]["reason"], "stale_evidence")

    # 现有直接/间接来源即使未变更自身 revision，传递性依赖失效也不能复活。
    def test_support_closure_fails_closed_on_cycles(self):
        from myth.platform.memory_lifecycle import evaluate_support_closure

        graph = {
            "a": ({"active": 1, "revision": 1, "scope_type": "global", "scope_id": None},
                  [{"source_memory_id": "b", "source_revision": 1}]),
            "b": ({"active": 1, "revision": 1, "scope_type": "global", "scope_id": None},
                  [{"source_memory_id": "a", "source_revision": 1}]),
        }
        report = evaluate_support_closure(
            "a", graph["a"][0], graph["a"][1], load=lambda key: graph[key],
        )
        self.assertEqual(report["stale_sources"][0]["reason"], "dependency_cycle")
        self.assertEqual(report["stale_sources"][0]["path"], ["a", "b", "a"])

    # 恶意或意外的超深证据链不可绕过校验预算后被标记 fresh。
    def test_support_closure_budget_exhaustion_is_invalid(self):
        from myth.platform.memory_lifecycle import evaluate_support_closure

        # 虚拟无限依赖链：无需构造大型数据库，即可验证深度预算越界必定拒绝。
        def load(key):
            index = int(key[1:])
            return (
                {"active": 1, "revision": 1, "scope_type": "global", "scope_id": None},
                [{"source_memory_id": f"m{index+1}", "source_revision": 1}],
            )

        report = evaluate_support_closure(
            "root", {"scope_type": "global", "scope_id": None},
            [{"source_memory_id": "m0", "source_revision": 1}],
            load=load, max_depth=3,
        )
        self.assertEqual(report["stale_sources"][0]["reason"], "depth_limit")


if __name__ == "__main__":
    unittest.main()
