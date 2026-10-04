"""回归边界：Milvus 派生索引、Hybrid hydration 与 Memory 渐进披露。
测试使用内存替身，不安装/启动 Milvus；真实服务连通性属于可选 Adapter 集成验证。
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.conversation import conversation_request
from myth.platform.retrieval import reciprocal_rank_scores


class FakeVectorIndex:
    """只模拟向量候选身份/版本；正文和权限必须由被测 SQLite 仓储重新 hydration。"""

    # 初始化纯内存候选索引；替身不模拟真实 Milvus 网络/一致性。
    def __init__(self):
        self.knowledge = {}
        self.memories = {}

    # 返回固定健康投影供装配测试；不证明真实服务可用。
    def status(self):
        return {"backend": "milvus", "configured": True, "healthy": True}

    # 保存知识 source version，供 hydration 回归构造候选。
    def sync_knowledge(self, rows):
        for row in rows:
            self.knowledge[row["record_id"]] = dict(row)
        return {"received": len(rows), "upserted": len(rows), "skipped": 0}

    # 保存 Memory revision，供 revoke/freshness 回归构造候选。
    def sync_memories(self, rows):
        for row in rows:
            self.memories[row["record_id"]] = dict(row)
        return {"received": len(rows), "upserted": len(rows), "skipped": 0}

    # 按插入顺序返回知识候选；排序质量不属于本替身证明范围。
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

    # 按插入顺序返回 Memory 候选；真实 embedding 质量另做集成评测。
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


# 固定 Milvus 派生索引与渐进 Memory 的本地不变量；不把替身结果宣传为真实服务验证。
class MilvusRetrievalTests(unittest.TestCase):
    # 为每个测试创建独立 Runtime，并只在被测仓储上注入 Vector Adapter 替身。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.fake = FakeVectorIndex()
        self.workspace.vector_index = self.fake
        self.workspace.repository.knowledge.vector_index = self.fake
        self.workspace.memory.vector_index = self.fake
        self.repo = self.workspace.repository

    # 关闭 SQLite/临时目录，避免测试间共享权威状态。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 证明 Hybrid 只融合排名，不要求 lexical score 与向量距离处于同一数值空间。
    def test_rrf_fuses_rankings_without_comparing_raw_scores(self):
        scores = reciprocal_rank_scores((("a", "b"), ("b", "c")))
        self.assertGreater(scores["b"], scores["a"])
        self.assertGreater(scores["b"], scores["c"])

    # 证明纯向量命中最终正文仍来自当前 SQLite chunk，而非 Milvus metadata。
    def test_vector_only_knowledge_hit_is_hydrated_from_current_sqlite_source(self):
        doc = self.repo.knowledge.import_document(
            {"title": "architecture", "content": "alpha beta gamma"}
        )
        report = self.repo.knowledge.search_report("meaning-never-in-source", limit=3)
        self.assertEqual(report["retrieval"]["backend"], "lexical+milvus")
        self.assertEqual(report["sources"][0]["document_id"], doc["id"])
        self.assertEqual(report["sources"][0]["content"], "alpha beta gamma")
        self.assertIn("hybrid_score", report["sources"][0])

    # 证明陈旧 digest 的远端向量候选不能重新进入当前知识结果。
    def test_stale_vector_knowledge_version_is_rejected(self):
        doc = self.repo.knowledge.import_document({"title": "v1", "content": "first"})
        key = next(iter(self.fake.knowledge))
        self.fake.knowledge[key]["source_version"] = "stale-digest"
        # 防止 rebuild 覆盖故意注入的陈旧版本，模拟远端索引残留。
        self.workspace.repository.knowledge.vector_index.sync_knowledge = lambda rows: {
            "received": len(rows),
            "upserted": 0,
            "skipped": len(rows),
        }
        report = self.repo.knowledge.search_report("semantic-only", limit=3)
        self.assertEqual(report["sources"], [])
        self.assertGreaterEqual(report["retrieval"]["vector_stale_rejected"], 1)
        self.assertEqual(self.repo.knowledge.document(doc["id"])["content"], "first")

    # 证明 Memory 初始召回保持 L0，显式升级到 L2 时仍绑定同一 memory revision。
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

    # 证明已 revoke Memory 即使仍残留向量记录也会被权威 active/revision 检查拒绝。
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

    # 证明 timeline 只导航邻近 Memory，所有返回仍保留各自稳定 source_ref。
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

    # 证明 Context 指标统计的是预算选择后的实际交付量，而不是只复述召回数量。
    def test_context_report_separates_retrieved_from_delivered_memory(self):
        snapshot = {
            "messages": [{"role": "user", "content": "current"}],
            "memory": [
                {
                    "memory_id": f"m{index}",
                    "kind": "semantic",
                    "text": ("old-memory-" + str(index) + " ") * 500,
                    "source_ref": f"memory:m{index}@1",
                    "provenance_ref": f"run:{index}",
                    "revision": 1,
                    "resolution": "L0",
                }
                for index in range(8)
            ],
        }
        request = conversation_request(
            {
                "provider": "ollama",
                "model": "test",
                "max_output_tokens": 512,
                "num_ctx": 8192,
                "temperature": 0.0,
            },
            snapshot,
            snapshot["messages"],
            [],
        )
        report = request.context_report
        self.assertEqual(report["retrieved"]["memory"], 8)
        self.assertEqual(
            report["delivered"]["memory"],
            len([ref for ref in report["selected"] if ref.startswith("memory:")]),
        )
        self.assertLessEqual(report["delivered"]["memory"], report["retrieved"]["memory"])



if __name__ == "__main__":
    unittest.main()
