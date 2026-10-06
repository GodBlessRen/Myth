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

    # 正文Delta与remember都是来源变化；当前UI状态和后台due共用同一持久水位。
    def test_delta_marks_materialized_model_stale(self):
        source = self.memory.remember(
            kind="semantic", text="Initial architecture.", source_ref="delta:source"
        )
        model = self.views.create_model(name="Delta model", source_query="architecture")
        prepared = self.views.prepare_refresh(model["model_id"])
        self.views.commit_refresh(
            model["model_id"], content="Initial synthesis.",
            evidence_memory_ids=[source["memory_id"]],
            expected_model_revision=prepared["model_revision"],
            observed_change_seq=prepared["observed_change_seq"],
        )
        self.memory.apply_delta(
            source["memory_id"], [{"op": "replace_text", "text": "Changed architecture."}],
            expected_revision=source["revision"],
        )
        self.assertEqual(self.views.model(model["model_id"])["freshness"], "stale")

    # 其它项目的变化既不让模型误报stale，也不拒绝已准备的本项目刷新。
    def test_unrelated_scope_change_preserves_refresh_and_freshness(self):
        source = self.memory.remember(
            kind="semantic", text="Project architecture.", source_ref="isolation:source",
            scope_type="project", scope_id="project-a",
        )
        model = self.views.create_model(
            name="Isolated model", source_query="architecture",
            scope_type="project", scope_id="project-a",
        )
        prepared = self.views.prepare_refresh(model["model_id"])
        self.memory.remember(
            kind="semantic", text="Other project.", source_ref="isolation:other",
            scope_type="project", scope_id="project-b",
        )
        refreshed = self.views.commit_refresh(
            model["model_id"], content="Current synthesis.",
            evidence_memory_ids=[source["memory_id"]],
            expected_model_revision=prepared["model_revision"],
            observed_change_seq=prepared["observed_change_seq"],
        )
        self.memory.remember(
            kind="semantic", text="Changed other project.", source_ref="isolation:other",
            scope_type="project", scope_id="project-b",
        )
        self.assertEqual(refreshed["freshness"], "fresh")
        self.assertEqual(self.views.model(model["model_id"])["freshness"], "fresh")

    # 准备后来源移出scope，旧synthesis不能用“原scope没有新记录”骗过提交检查。
    def test_scope_migration_rejects_prepared_refresh(self):
        source = self.memory.remember(
            kind="semantic", text="Initial project source.", source_ref="migration:source",
            scope_type="project", scope_id="before",
        )
        model = self.views.create_model(
            name="Migrating source model", source_query="project source",
            scope_type="project", scope_id="before",
        )
        prepared = self.views.prepare_refresh(model["model_id"])
        self.memory.remember(
            kind="semantic", text="Moved project source.", source_ref="migration:source",
            scope_type="project", scope_id="after",
        )
        with self.assertRaisesRegex(ValueError, "source scope changed"):
            self.views.commit_refresh(
                model["model_id"], content="Old scope synthesis.",
                evidence_memory_ids=[source["memory_id"]],
                expected_model_revision=prepared["model_revision"],
                observed_change_seq=prepared["observed_change_seq"],
            )
        self.assertEqual(self.views.model(model["model_id"])["revision"], 1)

    # prepare 后先变别的项目再变本项目，旧synthesis仍必须拒绝，不能被limit=1遮挡。
    def test_out_of_scope_change_cannot_hide_later_refresh_conflict(self):
        source = self.memory.remember(
            kind="semantic", text="Project architecture.", source_ref="scope:source",
            scope_type="project", scope_id="project-a",
        )
        model = self.views.create_model(
            name="Scoped model", source_query="architecture",
            scope_type="project", scope_id="project-a",
        )
        prepared = self.views.prepare_refresh(model["model_id"])
        self.memory.remember(
            kind="semantic", text="Unrelated change.", source_ref="scope:outside",
            scope_type="project", scope_id="project-b",
        )
        self.memory.remember(
            kind="semantic", text="New project source.", source_ref="scope:inside",
            scope_type="project", scope_id="project-a",
        )
        with self.assertRaisesRegex(ValueError, "source scope changed"):
            self.views.commit_refresh(
                model["model_id"], content="Stale synthesis.",
                evidence_memory_ids=[source["memory_id"]],
                expected_model_revision=prepared["model_revision"],
                observed_change_seq=prepared["observed_change_seq"],
            )
        self.assertIsNone(self.views.model(model["model_id"])["content"])

    # Backing自身不算新底层证据，但也不能挡住更晚的真实source变化。
    def test_backing_change_cannot_hide_later_source_change(self):
        source = self.memory.remember(
            kind="semantic", text="Source architecture.", source_ref="backing:source"
        )
        model = self.views.create_model(name="Backing model", source_query="architecture")
        prepared = self.views.prepare_refresh(model["model_id"])
        refreshed = self.views.commit_refresh(
            model["model_id"], content="Architecture synthesis.",
            evidence_memory_ids=[source["memory_id"]],
            expected_model_revision=prepared["model_revision"],
            observed_change_seq=prepared["observed_change_seq"],
        )
        self.memory.remember(
            kind="semantic", text="Backing edited.",
            source_ref=f"mental-model:{model['model_id']}",
        )
        self.memory.remember(
            kind="semantic", text="Source changed.", source_ref="backing:source"
        )
        self.assertEqual(refreshed["freshness"], "fresh")
        self.assertTrue(self.views.model(model["model_id"])["is_stale"])

    # 大量派生模型不应抢占top-k后再被剔除，导致底层source永远无机会参与refresh。
    def test_derived_memories_do_not_starve_refresh_sources(self):
        source = self.memory.remember(
            kind="semantic", text="Architecture source.", source_ref="rank:source"
        )
        for index in range(24):
            self.memory.remember(
                kind="semantic", text="Architecture synthesized model.",
                source_ref=f"mental-model:rank-{index}",
            )
        model = self.views.create_model(name="Source model", source_query="architecture")
        prepared = self.views.prepare_refresh(model["model_id"])
        self.assertEqual([item["memory_id"] for item in prepared["sources"]], [source["memory_id"]])

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
