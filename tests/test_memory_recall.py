"""多探针召回的安全边界：作用域、来源版本、预算及 fail-closed。

固定 SQLite Runtime 和模拟的检索路径，不把词面相关性冒充答案验证。
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.conversation import validate_tool_arguments
from myth.platform.memory_recall import build_recall_plan, parse_memory_ref, rank_probe_rows
from myth.runtime import MythRuntime
from myth.workspace import Workspace


class RecallContractTests(unittest.TestCase):
    def test_probe_normalization_and_deduplication(self):
        plan = build_recall_plan(" Original ", probes=["original", "counterexample"])
        self.assertEqual(plan.queries, ("Original", "counterexample"))
        with self.assertRaises(ValueError):
            build_recall_plan("x", probes=["a", "b", "c", "d"])
        with self.assertRaises(ValueError):
            build_recall_plan("x", limit=True)
        with self.assertRaises(ValueError):
            build_recall_plan("x", required_refs=["memory:guess@1"])

    def test_rank_fusion_preserves_identity_and_does_not_claim_probability(self):
        rows = rank_probe_rows([
            [{"memory_id": "a", "revision": 1}, {"memory_id": "b", "revision": 1}],
            [{"memory_id": "b", "revision": 1}, {"memory_id": "a", "revision": 1}],
        ])
        self.assertEqual({item["memory_id"] for item in rows}, {"a", "b"})
        self.assertNotIn("confidence", rows[0])

    def test_tool_contract_rejects_unknown_and_excessive_probes(self):
        validate_tool_arguments("memory.recall", {"query": "source", "probes": ["a"]})
        with self.assertRaises(ValueError):
            validate_tool_arguments("memory.recall", {"query": "x", "probes": ["a"] * 4})
        with self.assertRaises(ValueError):
            validate_tool_arguments("memory.recall", {"query": "x", "permission": "admin"})


class RecallStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.memory = self.workspace.memory

    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

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

    def test_missing_and_revoked_anchors_are_explicit(self):
        missing = "memory:mem_" + "0" * 32 + "@1"
        initial = self.memory.recall_report("anything", required_refs=[missing])
        self.assertEqual(initial["evidence_gate"]["invalid_refs"][0]["reason"], "missing")
        row = self.memory.remember(kind="semantic", text="Visible fact", source_ref="source:revoke")
        ref = f"memory:{row['memory_id']}@1"
        self.memory.revoke(row["memory_id"])
        report = self.memory.recall_report("Visible fact", required_refs=[ref])
        self.assertEqual(report["evidence_gate"]["invalid_refs"][0]["reason"], "unavailable")

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

    def test_no_required_sources_never_claims_verified_answer(self):
        self.memory.remember(kind="semantic", text="Keyword candidate", source_ref="source:keyword")
        report = self.memory.recall_report("Keyword")
        self.assertEqual(report["evidence_gate"]["status"], "unverified")
        self.assertFalse(report["evidence_gate"]["answer_verified"])


if __name__ == "__main__":
    unittest.main()
