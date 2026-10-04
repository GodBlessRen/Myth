"""回归边界：Mental Model 是 materialized Memory view，Knowledge Page 只拥有树结构。
测试固定 prepare -> synthesis -> commit、水位 freshness、无自我喂养和原子树创建；不依赖真实 LLM/Milvus。
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.workspace import Workspace


# KnowledgeViewTests：高阶记忆必须复用现有 Memory authority，而不是产生第二套事实数据库。
class KnowledgeViewTests(unittest.TestCase):
    # 每个用例使用独立 Runtime；knowledge_views 与 memory 共用同一 SQLite 状态所有权。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.memory = self.workspace.memory
        self.views = self.workspace.knowledge_views

    # 关闭本地资源，防止 change watermark 和树节点跨测试泄漏。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 新 Mental Model 只是“持续回答什么问题”的定义；未刷新前不伪造正文。
    def test_model_starts_unmaterialized_and_prepare_reads_memory(self):
        source = self.memory.remember(
            kind="semantic",
            text="Myth keeps SQLite authoritative and Milvus derived.",
            source_ref="decision:storage",
        )
        model = self.views.create_model(
            name="Storage architecture",
            source_query="SQLite Milvus",
        )
        self.assertEqual(model["freshness"], "unmaterialized")
        self.assertIsNone(model["content"])

        prepared = self.views.prepare_refresh(model["model_id"])
        self.assertEqual(prepared["model_revision"], 1)
        self.assertEqual(prepared["sources"][0]["memory_id"], source["memory_id"])
        self.assertEqual(prepared["sources"][0]["resolution"], "L1")

    # 成功刷新把 synthesis 写成 backing Semantic Memory，并将证据固定到 source revisions。
    def test_refresh_materializes_backing_memory_and_becomes_fresh(self):
        source = self.memory.remember(
            kind="semantic",
            text="Evidence and freshness are first-class memory state.",
            source_ref="decision:evidence",
        )
        model = self.views.create_model(
            name="Memory architecture",
            source_query="Evidence freshness",
        )
        prepared = self.views.prepare_refresh(model["model_id"])

        refreshed = self.views.commit_refresh(
            model["model_id"],
            content="Myth memory is evidence-backed and freshness-aware.",
            evidence_memory_ids=[source["memory_id"]],
            expected_model_revision=prepared["model_revision"],
            observed_change_seq=prepared["observed_change_seq"],
        )

        self.assertEqual(refreshed["freshness"], "fresh")
        self.assertFalse(refreshed["is_stale"])
        self.assertEqual(refreshed["revision"], 2)
        self.assertEqual(refreshed["content"]["fact_level"], "context")
        self.assertEqual(refreshed["content"]["proof_count"], 1)
        self.assertTrue(
            refreshed["content"]["provenance_ref"].startswith("mental-model:")
        )

    # 来源更新后 Mental Model 只变 stale，不自动调用模型或覆盖旧 materialized content。
    def test_source_change_marks_model_stale_without_auto_refresh(self):
        source = self.memory.remember(
            kind="semantic",
            text="Current project vector store is Milvus.",
            source_ref="decision:vector",
        )
        model = self.views.create_model(
            name="Vector choice",
            source_query="Milvus vector",
        )
        prepared = self.views.prepare_refresh(model["model_id"])
        refreshed = self.views.commit_refresh(
            model["model_id"],
            content="Milvus is the current vector adapter.",
            evidence_memory_ids=[source["memory_id"]],
            expected_model_revision=prepared["model_revision"],
            observed_change_seq=prepared["observed_change_seq"],
        )
        old_text = refreshed["content"]["text"]

        self.memory.remember(
            kind="semantic",
            text="Milvus remains the vector adapter; SQLite remains authoritative.",
            source_ref="decision:vector",
        )

        stale = self.views.model(model["model_id"], resolution="L2")
        self.assertTrue(stale["is_stale"])
        self.assertEqual(stale["freshness"], "stale")
        self.assertEqual(stale["content"]["text"], old_text)

    # prepare 之后 scope 发生任何新变化时旧 synthesis 不可发布，防止物化视图覆盖成过期状态。
    def test_refresh_rejects_if_scope_changes_after_prepare(self):
        source = self.memory.remember(
            kind="semantic",
            text="Initial architecture note.",
            source_ref="note:initial",
        )
        model = self.views.create_model(
            name="Architecture summary",
            source_query="architecture note",
        )
        prepared = self.views.prepare_refresh(model["model_id"])

        self.memory.remember(
            kind="semantic",
            text="A newer architecture note arrived.",
            source_ref="note:new",
        )

        with self.assertRaisesRegex(ValueError, "source scope changed"):
            self.views.commit_refresh(
                model["model_id"],
                content="This synthesis was prepared before the new note.",
                evidence_memory_ids=[source["memory_id"]],
                expected_model_revision=prepared["model_revision"],
                observed_change_seq=prepared["observed_change_seq"],
            )
        self.assertEqual(self.views.model(model["model_id"])["revision"], 1)

    # Mental Model 的上一版 backing Memory 不能重新进入自己的 refresh sources，避免自我强化。
    def test_refresh_does_not_feed_back_its_own_materialized_memory(self):
        source = self.memory.remember(
            kind="semantic",
            text="Project values deterministic runtime boundaries.",
            source_ref="decision:deterministic",
        )
        model = self.views.create_model(
            name="Runtime principles",
            source_query="deterministic runtime",
        )
        prepared = self.views.prepare_refresh(model["model_id"])
        refreshed = self.views.commit_refresh(
            model["model_id"],
            content="Deterministic boundaries remain a project principle.",
            evidence_memory_ids=[source["memory_id"]],
            expected_model_revision=prepared["model_revision"],
            observed_change_seq=prepared["observed_change_seq"],
        )

        again = self.views.prepare_refresh(model["model_id"])
        source_ids = {item["memory_id"] for item in again["sources"]}
        self.assertNotIn(refreshed["backing_memory_id"], source_ids)

    # Knowledge Page 只保存 mental_model_id；目录树读取正文时仍来自同一 backing Memory。
    def test_knowledge_page_tree_references_model_without_copying_content(self):
        folder = self.views.create_folder("Project")
        created = self.views.create_page_with_model(
            name="Architecture",
            source_query="Myth architecture",
            parent_id=folder["node_id"],
        )

        page_row = self.runtime.store.db.execute(
            "SELECT * FROM workspace_knowledge_pages WHERE node_id=?",
            (created["page"]["node_id"],),
        ).fetchone()
        self.assertNotIn("content", dict(page_row))
        self.assertEqual(
            page_row["mental_model_id"], created["mental_model"]["model_id"]
        )
        tree = self.views.tree()
        self.assertEqual(tree[0]["name"], "Project")
        self.assertEqual(tree[0]["children"][0]["name"], "Architecture")

    # 同级重名失败必须回滚整次 page+model 创建，不留下孤儿 Mental Model。
    def test_page_with_model_creation_is_atomic_on_tree_conflict(self):
        self.views.create_page_with_model(
            name="Root page",
            source_query="first question",
        )
        before = self.runtime.store.db.execute(
            "SELECT COUNT(*) AS n FROM workspace_mental_models"
        ).fetchone()["n"]

        with self.assertRaises(sqlite3.IntegrityError):
            self.views.create_page_with_model(
                name="Root page",
                source_query="second question",
            )

        after = self.runtime.store.db.execute(
            "SELECT COUNT(*) AS n FROM workspace_mental_models"
        ).fetchone()["n"]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
