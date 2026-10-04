"""回归边界：Milvus 派生索引、Hybrid hydration 与 Memory 渐进披露。
测试使用内存替身，不安装/启动 Milvus；真实服务连通性属于可选 Adapter 集成验证。
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.platform.retrieval import reciprocal_rank_scores


class FakeVectorIndex:
    """只模拟向量候选身份/版本；正文和权限必须由被测 SQLite 仓储重新 hydration。"""

    def __init__(self):
        self.knowledge = {}
        self.memories = {}

    def status(self):
        return {"backend": "milvus", "configured": True, "healthy": True}

    def sync_knowledge(self, rows):
        for row in rows:
            self.knowledge[row["record_id"]] = dict(row)
        return {"received": len(rows), "upserted": len(rows), "skipped": 0}

    def sync_memories(self, rows):
        for row in rows:
            self.memories[row["record_id"]] = dict(row)
        return {"received": len(rows), "upserted": len(rows), "skipped": 0}

    def search_knowledge(self, query, *, limit=64):
        rows = list(self.knowledge.values())[:limit]
        return [
            {
                "record_id": row["record_id"],
                "source_version": row["source_version"],
                "distance": 0.9 - index * 0.01,
                "rank": index + 1,
            }
            for index, row in enumerate(rows)
        ]

    def search_memories(self, query, *, limit=64):
        rows = list(self.memories.values())[:limit]
        return [
            {
                "record_id": row["record_id"],
                "source_version": row["source_version"],
                "distance": 0.9 - index * 0.01,
                "rank": index + 1,
            }
            for index, row in enumerate(rows)
        ]


class MilvusRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.fake = FakeVectorIndex()
        self.workspace.vector_index = self.fake
        self.workspace.repository.vector_index = self.fake
        self.workspace.memory.vector_index = self.fake
        self.repo = self.workspace.repository

    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    def test_rrf_fuses_rankings_without_comparing_raw_scores(self):
        scores = reciprocal_rank_scores((("a", "b"), ("b", "c")))
        self.assertGreater(scores["b"], scores["a"])
        self.assertGreater(scores["b"], scores["c"])

    def test_vector_only_knowledge_hit_is_hydrated_from_current_sqlite_source(self):
        doc = self.repo.import_document(
            {"title": "architecture", "content": "alpha beta gamma"}
        )
        report = self.repo.search_report("meaning-never-in-source", limit=3)
        self.assertEqual(report["retrieval"]["backend"], "lexical+milvus")
        self.assertEqual(report["sources"][0]["document_id"], doc["id"])
        self.assertEqual(report["sources"][0]["content"], "alpha beta gamma")
        self.assertIn("hybrid_score", report["sources"][0])

    def test_stale_vector_knowledge_version_is_rejected(self):
        doc = self.repo.import_document({"title": "v1", "content": "first"})
        key = next(iter(self.fake.knowledge))
        self.fake.knowledge[key]["source_version"] = "stale-digest"
        # 防止 rebuild 覆盖故意注入的陈旧版本，模拟远端索引残留。
        self.workspace.repository.vector_index.sync_knowledge = lambda rows: {
            "received": len(rows),
            "upserted": 0,
            "skipped": len(rows),
        }
        report = self.repo.search_report("semantic-only", limit=3)
        self.assertEqual(report["sources"], [])
        self.assertGreaterEqual(report["retrieval"]["vector_stale_rejected"], 1)
        self.assertEqual(self.repo.document(doc["id"])["content"], "first")

    def test_memory_search_returns_l0_then_resolves_same_revision_to_l2(self):
        row = self.workspace.memory.remember(
            kind="semantic",
            text="The remembered architecture decision keeps SQLite authoritative. " * 20,
            source_ref="decision:vector-boundary",
        )
        views = self.workspace.memory.search_views("semantic-only", limit=3)
        self.assertEqual(views[0]["memory_id"], row["memory_id"])
        self.assertEqual(views[0]["resolution"], "L0")
        self.assertLess(len(views[0]["text"]), len(row["text"]))

        full = self.workspace.memory.resolve(row["memory_id"], resolution="L2")
        self.assertEqual(full["resolution"], "L2")
        self.assertEqual(full["text"], row["text"])
        self.assertEqual(full["source_ref"], views[0]["source_ref"])
        self.assertEqual(full["provenance_ref"], "decision:vector-boundary")

    def test_revoked_memory_stale_vector_hit_cannot_reenter_context(self):
        row = self.workspace.memory.remember(
            kind="semantic",
            text="remembered only through vector similarity",
            source_ref="decision:revoked",
        )
        self.workspace.memory.revoke(row["memory_id"])
        report = self.workspace.memory.search_report("semantic-only", limit=3)
        self.assertEqual(report["memories"], [])
        self.assertGreaterEqual(report["retrieval"]["vector_stale_rejected"], 1)

    def test_memory_timeline_is_navigation_not_source_rewrite(self):
        ids = []
        for index in range(4):
            ids.append(
                self.workspace.memory.remember(
                    kind="episodic",
                    text=f"episode-{index}",
                    source_ref=f"run:{index}",
                )["memory_id"]
            )
        timeline = self.workspace.memory.timeline(ids[2], radius=1)
        self.assertEqual([m["memory_id"] for m in timeline["memories"]], ids[1:4])
        for item in timeline["memories"]:
            self.assertTrue(item["source_ref"].startswith("memory:"))
            self.assertEqual(item["resolution"], "L0")


if __name__ == "__main__":
    unittest.main()
