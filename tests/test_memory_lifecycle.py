"""回归边界：Evidence-backed Memory、immutable revision、freshness 与受约束 Delta。
这些测试只证明本地确定性合同；不把 Memory 证据冒充 Verification，也不依赖真实 Milvus/LLM。
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.platform.memory_lifecycle import MemoryDeltaError
from myth.runtime import MythRuntime
from myth.workspace import Workspace


# MemoryLifecycleTests：固定 Hindsight 精华在 Myth Memory Domain 内的兼容行为，不增加新的 Runtime Layer。
class MemoryLifecycleTests(unittest.TestCase):
    # 每个测试使用独立 SQLite Runtime；Milvus 保持可选且不参与这些权威状态断言。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.memory = self.workspace.memory

    # 关闭 SQLite 与临时目录，避免 revision/evidence 在测试间串扰。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 外部 provenance 没有版本水位时保留 untracked，但仍计入 proof_count；不伪造 fresh。
    def test_external_provenance_is_evidence_without_fake_freshness(self):
        row = self.memory.remember(
            kind="semantic",
            text="SQLite remains authoritative.",
            source_ref="decision:sqlite-authority",
        )

        compact = self.memory.resolve(row["memory_id"], resolution="L0")
        full = self.memory.resolve(row["memory_id"], resolution="L2")

        self.assertEqual(compact["proof_count"], 1)
        self.assertEqual(compact["freshness"], "untracked")
        self.assertFalse(compact["is_stale"])
        self.assertEqual(full["evidence"][0]["evidence_ref"], "decision:sqlite-authority")
        self.assertEqual(full["freshness_report"]["external_evidence"], 1)

    # Observation 引用另一个 Memory 时固定 source revision；来源更新后确定性变 stale。
    def test_memory_linked_evidence_becomes_stale_when_source_revision_changes(self):
        source = self.memory.remember(
            kind="episodic",
            text="User selected Milvus as the vector adapter.",
            source_ref="run:milvus-choice",
        )
        observation = self.memory.remember(
            kind="semantic",
            text="The project prefers Milvus for dense retrieval.",
            source_ref="observation:vector-preference",
            evidence=[
                {
                    "source_memory_id": source["memory_id"],
                    "quote": "Milvus",
                    "relevance": "supports vector adapter preference",
                }
            ],
        )

        before = self.memory.freshness(observation["memory_id"])
        self.assertEqual(before["status"], "fresh")

        self.memory.remember(
            kind="episodic",
            text="User selected Milvus, while keeping SQLite authoritative.",
            source_ref="run:milvus-choice",
        )

        after = self.memory.freshness(observation["memory_id"])
        self.assertEqual(after["status"], "stale")
        self.assertEqual(after["stale_sources"][0]["reason"], "revision_changed")

    # Delta 只允许有限操作；应用后旧 revision 仍可读且没有 prose drift。
    def test_delta_updates_one_revision_and_preserves_immutable_snapshot(self):
        row = self.memory.remember(
            kind="semantic",
            text="Memory retrieval is lexical.",
            source_ref="decision:retrieval",
        )
        old = self.memory.revision_snapshot(row["memory_id"], 1)

        updated = self.memory.apply_delta(
            row["memory_id"],
            [
                {
                    "op": "replace_text",
                    "text": "Memory retrieval is lexical plus vector RRF.",
                },
                {
                    "op": "add_evidence",
                    "evidence": {
                        "evidence_ref": "commit:milvus-hybrid",
                        "relevance": "implementation evidence",
                    },
                },
            ],
            expected_revision=1,
        )

        self.assertEqual(updated["revision"], 2)
        self.assertEqual(old["text"], "Memory retrieval is lexical.")
        current = self.memory.revision_snapshot(row["memory_id"], 2)
        self.assertEqual(current["text"], "Memory retrieval is lexical plus vector RRF.")
        self.assertEqual(
            [item["evidence_ref"] for item in current["evidence"]],
            ["commit:milvus-hybrid", "decision:retrieval"],
        )

    # 无操作 Delta 是机械 no-op；不会为了“重新总结”制造新 revision。
    def test_empty_delta_is_mechanical_noop(self):
        row = self.memory.remember(
            kind="semantic",
            text="No change is still a meaningful result.",
            source_ref="decision:no-op",
        )
        same = self.memory.apply_delta(
            row["memory_id"], [], expected_revision=row["revision"]
        )
        self.assertEqual(same["revision"], row["revision"])
        self.assertEqual(self.memory.changes_since(1), [])

    # 水位写失败必须回滚已经写入的正文、证据和snapshot，不能留下“新正文/旧freshness”。
    def test_change_record_failure_rolls_back_delta_revision(self):
        row = self.memory.remember(
            kind="semantic", text="Stable.", source_ref="delta:rollback"
        )
        before = self.memory.current_change_seq()
        evidence = self.memory.evidence(row["memory_id"])
        with patch.object(self.memory, "_record_change", side_effect=RuntimeError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "disk full"):
                self.memory.apply_delta(
                    row["memory_id"], [{"op": "replace_text", "text": "Uncommitted."}],
                    expected_revision=1,
                )
        self.assertEqual(self.memory.get(row["memory_id"]), row)
        self.assertEqual(self.memory.evidence(row["memory_id"]), evidence)
        self.assertEqual(self.memory.current_change_seq(), before)
        with self.assertRaises(KeyError):
            self.memory.revision_snapshot(row["memory_id"], 2)

    # Delta 的新 revision 必须与变化水位同事务提交；否则后台物化视图会永久错认 fresh。
    def test_delta_records_revision_in_change_watermark(self):
        row = self.memory.remember(
            kind="semantic", text="Old source.", source_ref="decision:delta-watermark"
        )
        before = self.memory.current_change_seq()
        updated = self.memory.apply_delta(
            row["memory_id"], [{"op": "replace_text", "text": "New source."}],
            expected_revision=row["revision"],
        )
        changes = self.memory.changes_since(before)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["memory_id"], updated["memory_id"])
        self.assertEqual(changes[0]["revision"], updated["revision"])

    # 先出现别的项目变化不能占掉本项目的 limit=1；limit 约束可见结果而非原始全库行。
    def test_change_limit_applies_after_scope_filter(self):
        before = self.memory.current_change_seq()
        self.memory.remember(
            kind="semantic", text="Other project.", source_ref="scope:other",
            scope_type="project", scope_id="other",
        )
        visible = self.memory.remember(
            kind="semantic", text="Current project.", source_ref="scope:current",
            scope_type="project", scope_id="current",
        )
        changes = self.memory.changes_since(before, project_id="current", limit=1)
        self.assertEqual([item["memory_id"] for item in changes], [visible["memory_id"]])

    # 同一来源转移 scope 要让旧范围和新范围各自失效；历史revision仍保持不可变。
    def test_scope_move_invalidates_both_old_and_new_scopes(self):
        row = self.memory.remember(
            kind="semantic", text="Project source.", source_ref="scope:move",
            scope_type="project", scope_id="before",
        )
        watermark = self.memory.current_change_seq()
        moved = self.memory.remember(
            kind="semantic", text="Moved source.", source_ref="scope:move",
            scope_type="project", scope_id="after",
        )
        for scope_id in ("before", "after"):
            with self.subTest(scope_id=scope_id):
                changes = self.memory.changes_since(watermark, project_id=scope_id)
                self.assertTrue(any(item["memory_id"] == moved["memory_id"] for item in changes))
        self.assertEqual(row["memory_id"], moved["memory_id"])
        self.assertEqual(self.memory.revision_snapshot(row["memory_id"], 1)["text"], "Project source.")

    # 任一 Delta 操作非法时整批失败，正文/revision/evidence 都不部分写入。
    def test_invalid_delta_fails_closed_without_partial_revision(self):
        row = self.memory.remember(
            kind="semantic",
            text="Stable memory.",
            source_ref="decision:stable",
        )
        before_evidence = self.memory.evidence(row["memory_id"])

        with self.assertRaises(MemoryDeltaError):
            self.memory.apply_delta(
                row["memory_id"],
                [
                    {"op": "replace_text", "text": "Should not commit."},
                    {"op": "remove_evidence", "evidence_ref": "missing:evidence"},
                ],
                expected_revision=1,
            )

        current = self.memory.get(row["memory_id"])
        self.assertEqual(current["revision"], 1)
        self.assertEqual(current["text"], "Stable memory.")
        self.assertEqual(self.memory.evidence(row["memory_id"]), before_evidence)
        with self.assertRaises(KeyError):
            self.memory.revision_snapshot(row["memory_id"], 2)

    # 撤销来源会让依赖 Observation 变 stale，同时来源自身形成新的历史 revision。
    def test_revoked_source_marks_dependent_observation_stale(self):
        source = self.memory.remember(
            kind="episodic",
            text="temporary fact",
            source_ref="run:temporary",
        )
        observation = self.memory.remember(
            kind="semantic",
            text="derived observation",
            source_ref="observation:temporary",
            evidence=[{"source_memory_id": source["memory_id"]}],
        )

        revoked = self.memory.revoke(source["memory_id"])

        self.assertEqual(revoked["revision"], 2)
        self.assertFalse(bool(revoked["active"]))
        self.assertFalse(bool(self.memory.revision_snapshot(source["memory_id"], 2)["active"]))
        freshness = self.memory.freshness(observation["memory_id"])
        self.assertEqual(freshness["status"], "stale")
        self.assertEqual(freshness["stale_sources"][0]["reason"], "revoked")


if __name__ == "__main__":
    unittest.main()
