"""倒排候选索引的行为与安全回归：与旧全扫描精确同序，派生索引不成为事实来源。"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.platform.memory_lifecycle import MemoryDeltaError


class MemoryTermIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.memory = Workspace(self.runtime).memory

    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    def test_same_ranking_as_fullscan_across_scopes_kinds_cjk(self):
        """索引仅改变访问路径，不悄悄牺牲语义覆盖、中文 bigram、Scope 或 tie-break。"""
        rows = [
            ("alpha beta", "semantic", "global", None),
            ("alpha gamma", "episodic", "global", None),
            ("alpha beta gamma", "semantic", "project", "p1"),
            ("alpha secret", "semantic", "project", "p2"),
            ("数据库 索引 优化", "semantic", "session", "s1"),
            ("数据库 优化 alpha", "semantic", "global", None),
            ("alpha beta", "semantic", "session", "s2"),
            ("alpha_beta", "semantic", "global", None),
        ]
        for i, (body, kind, scope, sid) in enumerate(rows):
            self.memory.remember(kind=kind, text=body, source_ref=f"seed:{i}",
                                 scope_type=scope, scope_id=sid)
        for query, opts in (
            ("alpha beta", {}),
            ("alpha", {"project_id": "p1"}),
            ("alpha", {"project_id": "p2", "kinds": ["semantic"]}),
            ("数据库 优化", {"session_id": "s1"}),
            ("alpha_beta", {"exclude_source_prefix": "seed:1"}),
            ("alpha", {"exclude_source_prefix": "seed:%_"}),
        ):
            with self.subTest(query=query, opts=opts):
                indexed = self.memory.search_report(query, limit=6, **opts)
                legacy = self.memory._lexical_scan_report(query, limit=6, **opts)
                self.assertEqual(
                    [r["memory_id"] for r in indexed["memories"]],
                    [r["memory_id"] for r in legacy["memories"]],
                )
                self.assertEqual(indexed["retrieval"]["backend"], "memory-term-index")

    def test_index_avoids_fullscan_and_survives_restart(self):
        """同等可见结果的索引路径不得调用全库分页扫描，重启不必重建已有水位。"""
        for i in range(60):
            self.memory.remember(kind="semantic", text=f"document {i} alpha" if i == 57 else f"document {i}",
                                 source_ref=f"many:{i}")
        with patch.object(self.memory, "candidates", side_effect=AssertionError("fullscan forbidden")):
            result = self.memory.search_report("alpha", limit=3)
        self.assertEqual(result["retrieval"]["backend"], "memory-term-index")
        self.assertEqual(len(result["memories"]), 1)
        identity = result["memories"][0]["memory_id"]
        self.runtime.close()
        self.runtime = MythRuntime(self.root)
        self.memory = Workspace(self.runtime).memory
        with patch.object(self.memory, "candidates", side_effect=AssertionError("fullscan forbidden")):
            again = self.memory.search_report("alpha", limit=3)
        self.assertEqual([x["memory_id"] for x in again["memories"]], [identity])

    def test_delta_revoke_and_batch_rollback_keep_index_atomic(self):
        """正文替换、撤销和整批失败与倒排项同事务，绝不能返回旧内容或未提交文本。"""
        row = self.memory.remember(kind="semantic", text="before edit", source_ref="seed:delta")
        self.assertEqual(len(self.memory.search_report("before")["memories"]), 1)
        self.memory.apply_delta(row["memory_id"], [{"op": "replace_text", "text": "after edit"}],
                                expected_revision=1)
        self.assertEqual(self.memory.search_report("before")["memories"], [])
        self.assertEqual(len(self.memory.search_report("after")["memories"]), 1)
        with self.assertRaises(MemoryDeltaError):
            self.memory.apply_actions([
                {"op": "UPDATE", "memory_id": row["memory_id"], "expected_revision": 2,
                 "operations": [{"op": "replace_text", "text": "uncommitted"}]},
                {"op": "UPDATE", "memory_id": row["memory_id"], "expected_revision": 1,
                 "operations": [{"op": "replace_text", "text": "stale update"}]},
            ])
        self.assertEqual(self.memory.search_report("uncommitted")["memories"], [])
        self.assertEqual(len(self.memory.search_report("after")["memories"]), 1)
        self.memory.revoke(row["memory_id"])
        self.assertEqual(self.memory.search_report("after")["memories"], [])

    def test_direct_sql_write_marks_index_dirty_and_falls_back(self):
        """旧脚本/手工 SQL 绕开 owner 写入时，触发器保证不能从旧索引漏召回。"""
        self.memory.remember(kind="semantic", text="legacy seed", source_ref="seed:legacy")
        with self.runtime.store.tx() as db:
            db.execute(
                "INSERT INTO workspace_memories(memory_id,kind,text,source_ref,scope_type,scope_id) "
                "VALUES (?,?,?,?,?,?)",
                ("mem_direct_insert", "semantic", "direct candidate", "legacy:direct", "global", None),
            )
        result = self.memory.search_report("direct", limit=3)
        self.assertEqual(result["retrieval"]["backend"], "memory-lexical-fallback")
        self.assertTrue(result["retrieval"]["degraded"])
        self.assertEqual(result["memories"][0]["memory_id"], "mem_direct_insert")
        self.runtime.close()
        self.runtime = MythRuntime(self.root)
        self.memory = Workspace(self.runtime).memory
        index_result = self.memory.search_report("direct", limit=3)
        self.assertEqual(index_result["retrieval"]["backend"], "memory-term-index")
        self.assertEqual(index_result["memories"][0]["memory_id"], "mem_direct_insert")


if __name__ == "__main__":
    unittest.main()
