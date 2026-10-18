"""Mental Model 深化回归：Hindsight 风格 Full/Delta/Dry Run、不变发布和权威 CAS。"""

from pathlib import Path
import tempfile
import unittest

from myth.runtime import MythRuntime
from myth.workspace import Workspace


class MentalModelDeepRefreshTests(unittest.TestCase):
    """真实 SQLite 上验证补丁、预览、空变更和证据修订；不模拟模型事实真实性。"""

    def setUp(self):
        """创建隔离 Memory/Knowledge 权威 Store 及模型来源。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.memory = self.workspace.memory
        self.views = self.workspace.knowledge_views
        self.source = self.memory.remember(kind="semantic", text="Alpha source evidence",
                                           source_ref="source:alpha")
        self.model = self.views.create_model(name="Deep refresh", source_query="Alpha source")

    def tearDown(self):
        """关闭 SQLite 再删除临时目录，不能跨测试保留水位。"""
        self.runtime.close()
        self.tmp.cleanup()

    def materialize(self, text="Alpha is supported"):
        """按实际公开接口完成首次 Full 刷新，返回当前来源固定模型。"""
        plan = self.views.prepare_refresh(self.model["model_id"])
        return self.views.commit_refresh(
            self.model["model_id"], content=text,
            evidence_memory_ids=[self.source["memory_id"]],
            expected_model_revision=plan["model_revision"],
            observed_change_seq=plan["observed_change_seq"],
        )

    def test_dry_run_is_read_only_and_identical_to_commit_admission(self):
        """预览使用来源水位与 Scope 校验，但不产生模型正文、revision 或变化水位。"""
        plan = self.views.prepare_refresh(self.model["model_id"])
        before = self.memory.current_change_seq()
        preview = self.views.commit_refresh(
            self.model["model_id"], content="Alpha preview",
            evidence_memory_ids=[self.source["memory_id"]],
            expected_model_revision=plan["model_revision"],
            observed_change_seq=plan["observed_change_seq"],
            dry_run=True,
        )
        self.assertEqual(preview["status"], "DRY_RUN")
        self.assertTrue(preview["would_publish"])
        self.assertEqual(preview["content"], "Alpha preview")
        self.assertEqual(self.views.model(self.model["model_id"])["revision"], 1)
        self.assertEqual(self.memory.current_change_seq(), before)

    def test_noop_moves_observed_watermark_without_fabricating_memory_revision(self):
        """其它无关来源变化使模型 stale，但相同正文和支持无需再造新版本。"""
        original = self.materialize()
        backing = original["backing_memory_id"]
        self.memory.remember(kind="semantic", text="Unrelated detail", source_ref="unrelated:new")
        prepared = self.views.prepare_refresh(self.model["model_id"])
        before = self.memory.current_change_seq()
        same = self.views.commit_refresh(
            self.model["model_id"], content="Alpha is supported",
            evidence_memory_ids=[self.source["memory_id"]],
            expected_model_revision=prepared["model_revision"],
            observed_change_seq=prepared["observed_change_seq"],
        )
        self.assertEqual(same["revision"], 2)
        self.assertEqual(same["backing_memory_id"], backing)
        self.assertEqual(self.memory.get(backing)["revision"], 1)
        self.assertEqual(self.memory.current_change_seq(), before)
        self.assertEqual(same["freshness"], "fresh")

    def test_delta_exact_patch_preserves_history_and_requires_unique_match(self):
        """受约束差分修改不因重复子串猜测替换位置，旧 Memory Revision 保留。"""
        self.materialize("Alpha supports the stable plan.")
        prepared = self.views.prepare_refresh(self.model["model_id"])
        candidate = self.views.commit_refresh(
            self.model["model_id"], content="",
            mode="delta", delta_operations=[
                {"op": "replace_exact", "old_text": "stable", "new_text": "verified"}],
            evidence_memory_ids=[self.source["memory_id"]],
            expected_model_revision=prepared["model_revision"],
            observed_change_seq=prepared["observed_change_seq"],
        )
        self.assertEqual(candidate["content"]["text"], "Alpha supports the verified plan.")
        self.assertEqual(candidate["revision"], 3)
        backing = candidate["backing_memory_id"]
        self.assertEqual(self.memory.revision_snapshot(backing, 1)["text"],
                         "Alpha supports the stable plan.")
        self.assertEqual(self.memory.revision_snapshot(backing, 2)["text"],
                         "Alpha supports the verified plan.")

        now = self.views.prepare_refresh(self.model["model_id"])
        watermark = self.memory.current_change_seq()
        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            self.views.commit_refresh(
                self.model["model_id"], content="", mode="delta",
                delta_operations=[{"op": "replace_exact", "old_text": "not-present", "new_text": "Beta"}],
                evidence_memory_ids=[self.source["memory_id"]],
                expected_model_revision=now["model_revision"],
                observed_change_seq=now["observed_change_seq"],
            )
        self.assertEqual(self.memory.current_change_seq(), watermark)
        self.assertEqual(self.views.model(self.model["model_id"])["revision"], 3)

    def test_stale_delta_cannot_commit_and_source_repin_is_not_noop(self):
        """正文不变但引用的版本已改变，必须重写支持快照；旧水位仍拒绝。"""
        materialized = self.materialize()
        old_plan = self.views.prepare_refresh(self.model["model_id"])
        self.memory.remember(kind="semantic", text="Alpha source evidence amended",
                             source_ref="source:alpha")
        with self.assertRaisesRegex(ValueError, "source scope changed"):
            self.views.commit_refresh(
                self.model["model_id"], content="", mode="delta",
                delta_operations=[], evidence_memory_ids=[self.source["memory_id"]],
                expected_model_revision=old_plan["model_revision"],
                observed_change_seq=old_plan["observed_change_seq"],
            )
        fresh_plan = self.views.prepare_refresh(self.model["model_id"])
        updated = self.views.commit_refresh(
            self.model["model_id"], content=materialized["content"]["text"],
            evidence_memory_ids=[self.source["memory_id"]],
            expected_model_revision=fresh_plan["model_revision"],
            observed_change_seq=fresh_plan["observed_change_seq"],
        )
        self.assertEqual(updated["revision"], 3)
        self.assertEqual(self.memory.evidence(updated["backing_memory_id"])[0]["source_revision"], 2)


if __name__ == "__main__":
    unittest.main()
