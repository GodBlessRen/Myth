"""Memory Action Last Mile：单事务、版本核对、补偿幂等与索引故障。

测试只验证真实 SQLite 本地提交合同；不冒充远端 Provider、Milvus 或端到端答案质量。
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.domain import IdentityConflict
from myth.platform.memory_lifecycle import MemoryDeltaError, normalize_memory_actions
from myth.runtime import MythRuntime
from myth.workspace import Workspace


# MemoryActionBatchTests：所有输入走公共 Memory Store 接口，验证同一写事务的结果和异常回滚。
class MemoryActionBatchTests(unittest.TestCase):
    # 每条测试独立持久目录，避免变化水位与历史 revision 混杂。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.memory = self.workspace.memory

    # 完整释放 SQLite 与临时目录，保证下次测试使用全新数据库。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # ADD/UPDATE/DELETE 必须形成一个完整决定；各项 immutable revision 与流水状态一致。
    def test_atomic_batch_and_immutable_revisions(self):
        updated = self.memory.remember(
            kind="semantic", text="Policy old", source_ref="decision:policy",
        )
        deleted = self.memory.remember(
            kind="episodic", text="Old episode", source_ref="source:retire",
        )
        before = self.memory.current_change_seq()
        result = self.memory.apply_actions([
            {"op": "ADD", "kind": "semantic", "source_ref": "decision:new", "text": "New fact"},
            {"op": "UPDATE", "memory_id": updated["memory_id"], "expected_revision": 1,
             "operations": [{"op": "replace_text", "text": "Policy new"}]},
            {"op": "DELETE", "memory_id": deleted["memory_id"], "expected_revision": 1},
        ])
        self.assertEqual(result["status"], "COMMITTED")
        self.assertEqual(result["count"], 3)
        self.assertEqual(len(self.memory.changes_since(before)), 3)
        self.assertEqual(self.memory.revision_snapshot(updated["memory_id"], 1)["text"], "Policy old")
        self.assertEqual(self.memory.revision_snapshot(updated["memory_id"], 2)["text"], "Policy new")
        self.assertFalse(bool(self.memory.get(deleted["memory_id"])["active"]))
        self.assertEqual(self.memory.revision_snapshot(deleted["memory_id"], 2)["active"], 0)
        self.assertTrue(all(row["revision"] > 0 for row in result["changes"]))
        self.assertEqual(self.runtime.store.db.execute("PRAGMA user_version").fetchone()[0], 1)

    # 后一个 CAS 失败时，前一个 ADD 的行、历史快照和变化水位必须全都不存在。
    def test_stale_second_action_rolls_back_first(self):
        row = self.memory.remember(
            kind="semantic", text="Stable", source_ref="source:baseline",
        )
        before = self.memory.current_change_seq()
        with self.assertRaises(MemoryDeltaError):
            self.memory.apply_actions([
                {"op": "ADD", "kind": "semantic", "text": "Never committed",
                 "source_ref": "source:rolled-back"},
                {"op": "UPDATE", "memory_id": row["memory_id"],
                 "expected_revision": 99,
                 "operations": [{"op": "replace_text", "text": "Impossible"}]},
            ])
        self.assertEqual(self.memory.current_change_seq(), before)
        self.assertEqual(self.memory.get(row["memory_id"])["text"], "Stable")
        self.assertEqual(self.memory.search("Never committed"), [])

    # 后端在已写入第二项时失败，应撤销全部业务字段和水位，不能留下部分成功。
    def test_change_watermark_failure_rolls_back_entire_batch(self):
        old = self.memory.remember(
            kind="semantic", text="Old text", source_ref="source:rollback",
        )
        before = self.memory.current_change_seq()
        counter = [0]
        original = self.memory._record_change

        # 第二次水位持久化注入磁盘故障；必须让第一项一起回滚。
        def fail_second(db, memory_id, *, scope=None):
            counter[0] += 1
            if counter[0] == 2:
                raise RuntimeError("simulated disk failure")
            return original(db, memory_id, scope=scope)

        with patch.object(self.memory, "_record_change", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "simulated disk failure"):
                self.memory.apply_actions([
                    {"op": "ADD", "kind": "semantic", "text": "Partial",
                     "source_ref": "source:partial"},
                    {"op": "UPDATE", "memory_id": old["memory_id"],
                     "expected_revision": 1,
                     "operations": [{"op": "replace_text", "text": "Broken"}]},
                ])
        self.assertEqual(self.memory.current_change_seq(), before)
        self.assertEqual(self.memory.get(old["memory_id"])["text"], "Old text")
        self.assertEqual(self.memory.search("Partial"), [])
        with self.assertRaises(KeyError):
            self.memory.revision_snapshot(old["memory_id"], 2)

    # 同一 ADD 不能覆盖已有来源； UPDATE/DELETE 的 CAS 也不能双重执行。
    def test_replay_fails_closed_without_incrementing_revision(self):
        row = self.memory.remember(kind="semantic", text="Before", source_ref="source:replay")
        mutation = [{"op": "UPDATE", "memory_id": row["memory_id"],
                     "expected_revision": 1,
                     "operations": [{"op": "replace_text", "text": "After"}]}]
        self.memory.apply_actions(mutation)
        after = self.memory.current_change_seq()
        with self.assertRaises(MemoryDeltaError):
            self.memory.apply_actions(mutation)
        self.assertEqual(self.memory.current_change_seq(), after)
        self.assertEqual(self.memory.get(row["memory_id"])["revision"], 2)
        add = [{"op": "ADD", "kind": "semantic", "text": "Once", "source_ref": "source:once"}]
        self.memory.apply_actions(add)
        after_add = self.memory.current_change_seq()
        with self.assertRaises(MemoryDeltaError):
            self.memory.apply_actions(add)
        self.assertEqual(self.memory.current_change_seq(), after_add)

    # 重复 DELETE 使用旧 revision 明确冲突；普通人工 revoke 再调用也不能制造新 revision。
    def test_revoke_cas_and_idempotent_manual_revoke(self):
        row = self.memory.remember(kind="semantic", text="Remove", source_ref="source:delete")
        delete = [{"op": "DELETE", "memory_id": row["memory_id"], "expected_revision": 1}]
        self.memory.apply_actions(delete)
        before = self.memory.current_change_seq()
        with self.assertRaises(MemoryDeltaError):
            self.memory.apply_actions(delete)
        manual = self.memory.revoke(row["memory_id"])
        self.assertEqual(manual["revision"], 2)
        self.assertEqual(self.memory.current_change_seq(), before)

    # 跨 Scope 的 Memory-linked evidence 不得写入更宽的全局来源，也不允许 UPDATE 借引用泄漏。
    def test_private_provenance_cannot_cross_scope(self):
        secret = self.memory.remember(
            kind="semantic", text="Private", source_ref="source:private",
            scope_type="session", scope_id="private-session",
        )
        before = self.memory.current_change_seq()
        with self.assertRaises(MemoryDeltaError):
            self.memory.apply_actions([
                {"op": "ADD", "kind": "semantic", "text": "Public",
                 "source_ref": "source:public",
                 "evidence": [{"source_memory_id": secret["memory_id"]}]},
            ])
        public = self.memory.remember(
            kind="semantic", text="Public before", source_ref="source:public",
        )
        with self.assertRaises(MemoryDeltaError):
            self.memory.apply_actions([
                {"op": "UPDATE", "memory_id": public["memory_id"], "expected_revision": 1,
                 "operations": [{"op": "add_evidence", "evidence": {
                     "source_memory_id": secret["memory_id"],
                 }}]},
            ])
        self.assertEqual(self.memory.get(public["memory_id"])["revision"], 1)
        self.assertEqual(self.memory.current_change_seq(), before + 1)

    # 模型批量提案永不授予 verified 事实等级；bool revision、重复对象与无限流都拒绝。
    def test_bounded_contract_and_authority_floor(self):
        with self.assertRaises(MemoryDeltaError):
            normalize_memory_actions([
                {"op": "ADD", "kind": "semantic", "text": "Guess",
                 "source_ref": "model:guess", "fact_level": "verified"},
            ])
        with self.assertRaises(MemoryDeltaError):
            normalize_memory_actions([
                {"op": "DELETE", "memory_id": "id", "expected_revision": True},
            ])
        with self.assertRaises(MemoryDeltaError):
            normalize_memory_actions(({"op": "ADD"} for _ in range(2)))
        with self.assertRaises(MemoryDeltaError):
            normalize_memory_actions([
                {"op": "UPDATE", "memory_id": "id", "expected_revision": 1,
                 "operations": [{"op": "replace_text", "text": "One"}]},
                {"op": "DELETE", "memory_id": "id", "expected_revision": 2},
            ])
        self.assertEqual(self.memory.apply_actions([])["status"], "NOOP")
        self.assertEqual(self.memory.current_change_seq(), 0)

    # 远端 Milvus 派生写入失败不能抹除已经提交的 SQLite 事实，投影单独报告 degraded。
    def test_vector_sync_failure_does_not_invalidate_commit(self):
        # BrokenVector：通过 Memory 的唯一投影接口模拟可重建索引宕机。
        class BrokenVector:
            # 网络写异常只用于断言事务不会回滚；该替身不模拟真实 Milvus 性能。
            def sync_memories(self, payload):
                raise OSError("simulated remote index unavailable")

        self.memory.vector_index = BrokenVector()
        result = self.memory.apply_actions([
            {"op": "ADD", "kind": "semantic", "text": "SQLite wins",
             "source_ref": "source:durable"},
        ])
        self.assertEqual(result["status"], "COMMITTED")
        self.assertTrue(result["vector_projections"][0]["degraded"])
        self.assertEqual(result["vector_projections"][0]["reason"], "OSError")
        self.assertEqual(self.memory.get(result["changes"][0]["memory_id"])["text"], "SQLite wins")

    # 第二个 Runtime 连接不能重放已经提交的 CAS，模拟崩溃恢复后旧工作进程再续跑。
    def test_second_runtime_replay_is_rejected(self):
        row = self.memory.remember(kind="semantic", text="First", source_ref="source:race")
        action = [{"op": "UPDATE", "memory_id": row["memory_id"],
                   "expected_revision": 1,
                   "operations": [{"op": "replace_text", "text": "Second"}]}]
        self.memory.apply_actions(action)
        with MythRuntime(self.root) as other:
            mirror = Workspace(other).memory
            with self.assertRaises(MemoryDeltaError):
                mirror.apply_actions(action)
            self.assertEqual(mirror.get(row["memory_id"])["revision"], 2)

    # 空操作也必须先校验原 revision，避免过期的请求假装通过而使调用方丢失更新。
    def test_stale_empty_delta_is_not_a_success(self):
        row = self.memory.remember(kind="semantic", text="Anchor", source_ref="source:empty")
        with self.assertRaises(MemoryDeltaError):
            self.memory.apply_delta(row["memory_id"], [], expected_revision=100)
        self.assertEqual(self.memory.get(row["memory_id"])["revision"], 1)


# EpisodeIdempotenceTests：固定重复结算的业务不变量而非仅测试 SQLite 唯一键。
class EpisodeIdempotenceTests(unittest.TestCase):
    # 每次新建完整工作区，使 Episode 的回滚观察覆盖真实仓储。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.memory = Workspace(self.runtime).memory

    # 关闭共享连接后删除测试工作区，不影响生产用户数据。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 记忆补偿至少发生两次时，事实/水位应完全不变，依赖它的派生 Evidence 仍 fresh。
    def test_duplicate_run_episode_keeps_revision_and_freshness(self):
        first = self.memory.record_episode("episode-test", "Question", "Answer")
        dependent = self.memory.remember(
            kind="semantic", text="Learned answer", source_ref="derived:episode-test",
            evidence=[{"source_memory_id": first["memory_id"]}],
        )
        watermark = self.memory.current_change_seq()
        second = self.memory.record_episode("episode-test", "Question", "Answer")
        self.assertEqual(first, second)
        self.assertEqual(self.memory.current_change_seq(), watermark)
        self.assertEqual(self.memory.freshness(dependent["memory_id"])["status"], "fresh")

    # Turn 准入冻结项目范围；事后更改 Session 项目也不能改变同一 Run 的历史经历归属。
    def test_episode_scope_uses_frozen_turn_project(self):
        workspace = Workspace(self.runtime)
        repository = workspace.repository
        old_project = repository.create_project({"name": "original"})
        new_project = repository.create_project({"name": "moved"})
        repository.save_settings({
            "provider": "ollama", "model": "test", "ollama_url": "http://127.0.0.1:11434",
            "max_steps": 6, "max_output_tokens": 512, "thinking": False,
        })
        session = repository.create_session("scope", old_project["id"])
        turn = repository.create_turn(session["id"], "Question", "request-frozen-episode")
        repository.update_session(session["id"], {"project_id": new_project["id"]})
        entry = self.memory.record_episode(turn["run_id"], "Question", "Answer")
        self.assertEqual(entry["scope_type"], "project")
        self.assertEqual(entry["scope_id"], old_project["id"])
        replay = self.memory.record_episode(turn["run_id"], "Question", "Answer")
        self.assertEqual(replay["memory_id"], entry["memory_id"])
        self.assertEqual(replay["revision"], 1)

    # Run 身份相同但回答不同，不能覆盖历史；不把另一段答案悄悄写成新的 revision。
    def test_conflicting_episode_is_rejected(self):
        first = self.memory.record_episode("episode-conflict", "Question", "Original")
        with self.assertRaises(IdentityConflict):
            self.memory.record_episode("episode-conflict", "Question", "Different")
        self.assertEqual(self.memory.get(first["memory_id"]), first)


if __name__ == "__main__":
    unittest.main()
