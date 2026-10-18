"""替代证明端到端合同：默认 All-of、明确 OR-of-AND、共同前提、原子性及安全。"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.platform.memory_lifecycle import MemoryDeltaError


# AlternativeProofTests：证明路径由唯一 Memory owner 持久化，测试只走其公开读写接口。
class AlternativeProofTests(unittest.TestCase):
    # 每个用例使用独立 SQLite WAL 数据库，避免旧版本/外部路径干扰。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.memory = Workspace(self.runtime).memory

    # 关闭连接并清理临时文件，确保锁与版本不跨测试传播。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 建立可重复使用的来源；同一 source_ref 唯一，返回确切 Memory revision。
    def source(self, name, *, scope_type="global", scope_id=None):
        return self.memory.remember(
            kind="semantic", text=f"Proof premise {name}",
            source_ref=f"proof:{name}",
            scope_type=scope_type, scope_id=scope_id,
        )

    # 建立 AND 串联的两条替代证明，默认状态先保持所有来源都有效。
    def alternative(self):
        sources = {k: self.source(k) for k in "ABCE"}
        edges = [{"source_memory_id": row["memory_id"]} for row in sources.values()]
        derived = self.memory.remember(
            kind="semantic", text="Proof-backed result D",
            source_ref="proof:derived:D", evidence=edges,
        )
        refs = {
            key: f"memory:{row['memory_id']}" for key, row in sources.items()
        }
        result = self.memory.declare_proof_paths(
            derived["memory_id"],
            [[refs["A"], refs["B"]], [refs["C"], refs["E"]]],
            expected_revision=derived["revision"],
        )
        return sources, result, refs

    # 严格模式不因系统升级而自动 OR 化，任一依赖撤销即 stale。
    def test_legacy_all_of_remains_default(self):
        a, b = self.source("legacy-a"), self.source("legacy-b")
        root = self.memory.remember(
            kind="semantic", text="Legacy strict conclusion",
            source_ref="proof:legacy:root",
            evidence=[{"source_memory_id": a["memory_id"]},
                      {"source_memory_id": b["memory_id"]}],
        )
        self.memory.revoke(a["memory_id"])
        self.assertEqual(self.memory.freshness(root["memory_id"])["status"], "stale")
        self.assertNotIn("proof_paths", self.memory.freshness(root["memory_id"]))

    # 两条完整 OR 路径之一仍成立，则只失效旧路径，不撤销原 Conclusion。
    def test_revoked_one_path_keeps_other_complete_path(self):
        sources, root, refs = self.alternative()
        self.assertEqual(root["revision"], 2)
        self.memory.revoke(sources["B"]["memory_id"])
        fresh = self.memory.freshness(root["memory_id"])
        self.assertEqual(fresh["status"], "fresh")
        self.assertFalse(fresh["is_stale"])
        # Proof Paths 按稳定 Evidence 身份规范排序，不能把位置当业务上的路径身份。
        persisted = self.memory.revision_snapshot(root["memory_id"], 2)["proof_paths"]
        surviving = {
            frozenset(persisted[index])
            for index in fresh["proof_paths"]["valid_path_indices"]
        }
        self.assertEqual(surviving, {frozenset({refs["C"], refs["E"]})})
        self.assertTrue(fresh["proof_paths"]["failed_paths"])
        self.assertEqual(self.memory.resolve(root["memory_id"], resolution="L0")["freshness"], "fresh")
        # 另一条路径被打断后，任何 OR 分支都不能继续保留结论。
        self.memory.revoke(sources["C"]["memory_id"])
        self.assertEqual(self.memory.freshness(root["memory_id"])["status"], "stale")
        selected = self.memory.search_view_report("Proof-backed result D")["memories"]
        self.assertNotIn(root["memory_id"], {item["memory_id"] for item in selected})

    # 16 种输入组合全部按布尔公式验证，避免仅覆盖一条撤销快乐路径。
    def test_all_four_premise_truth_assignments_match_dnf(self):
        for mask in range(16):
            sources = {
                name: self.source(f"table-{mask}-{name}") for name in "ABCE"
            }
            claim = self.memory.remember(
                kind="semantic", text=f"Truth table claim {mask}",
                source_ref=f"proof:table:{mask}",
                evidence=[{"source_memory_id": sources[name]["memory_id"]} for name in "ABCE"],
            )
            refs = {name: f"memory:{sources[name]['memory_id']}" for name in "ABCE"}
            self.memory.declare_proof_paths(
                claim["memory_id"],
                [[refs["A"], refs["B"]], [refs["C"], refs["E"]]],
                expected_revision=1,
            )
            active = {name: bool(mask & (1 << index)) for index, name in enumerate("ABCE")}
            for name, enabled in active.items():
                if not enabled:
                    self.memory.revoke(sources[name]["memory_id"])
            expected = (active["A"] and active["B"]) or (active["C"] and active["E"])
            observed = self.memory.freshness(claim["memory_id"])["status"] == "fresh"
            with self.subTest(mask=mask, active=active):
                self.assertEqual(observed, expected)

    # 直接复现讨论例子：(A&B) OR (C&E) OR (B&E)；撤销 B/C 后不存在完整路径。
    def test_three_path_example_removes_claim_only_when_last_path_is_lost(self):
        premises = {name: self.source(f"example-{name}") for name in "ABCE"}
        target = self.memory.remember(
            kind="semantic", text="Example triple-path D",
            source_ref="proof:example:triple",
            evidence=[{"source_memory_id": premises[name]["memory_id"]} for name in "ABCE"],
        )
        refs = {name: f"memory:{premises[name]['memory_id']}" for name in "ABCE"}
        self.memory.declare_proof_paths(
            target["memory_id"],
            [[refs["A"], refs["B"]], [refs["C"], refs["E"]], [refs["B"], refs["E"]]],
            expected_revision=1,
        )
        self.memory.revoke(premises["B"]["memory_id"])
        self.assertEqual(self.memory.freshness(target["memory_id"])["status"], "fresh")
        self.memory.revoke(premises["C"]["memory_id"])
        self.assertEqual(self.memory.freshness(target["memory_id"])["status"], "stale")

    # 共享前提 B 对两个 AND 组都是必需条件，撤销 B 必须级联撤销 D。
    def test_shared_dependency_revocation_invalidates_every_path(self):
        sources = {k: self.source(f"shared-{k}") for k in "ABC"}
        root = self.memory.remember(
            kind="semantic", text="Shared dependency D", source_ref="proof:shared-root",
            evidence=[{"source_memory_id": sources[k]["memory_id"]} for k in "ABC"],
        )
        refs = {k: f"memory:{sources[k]['memory_id']}" for k in "ABC"}
        self.memory.declare_proof_paths(
            root["memory_id"],
            [[refs["A"], refs["B"]], [refs["B"], refs["C"]]],
            expected_revision=1,
        )
        self.memory.revoke(sources["B"]["memory_id"])
        result = self.memory.freshness(root["memory_id"])
        self.assertTrue(result["is_stale"])
        self.assertEqual(result["proof_paths"]["valid_path_indices"], [])

    # 祖先 Memory 的 OR 必须能拯救后代严格 AND，否则无法实现传递性真值维护。
    def test_transitive_descendant_sees_valid_ancestor_alternative(self):
        sources, root, _ = self.alternative()
        child = self.memory.remember(
            kind="semantic", text="Child inherits alternative proof",
            source_ref="proof:child",
            evidence=[{"source_memory_id": root["memory_id"]}],
        )
        self.memory.revoke(sources["B"]["memory_id"])
        self.assertEqual(self.memory.freshness(child["memory_id"])["status"], "fresh")
        self.memory.revoke(sources["C"]["memory_id"])
        self.assertEqual(self.memory.freshness(child["memory_id"])["status"], "stale")

    # 不完整证明、非版本化外部引用、重复路径都不允许悄悄降低前提门槛。
    def test_invalid_paths_cannot_partially_commit(self):
        sources, root, refs = self.alternative()
        watermark = self.memory.current_change_seq()
        for paths in (
            [[refs["A"]], [refs["C"]]],
            [[refs["A"], refs["B"]], [refs["A"], refs["B"]]],
            [[refs["A"], refs["B"]], ["missing-ref"]],
            [["external:unversioned"], [refs["C"]]],
        ):
            with self.subTest(paths=paths), self.assertRaises(MemoryDeltaError):
                self.memory.declare_proof_paths(
                    root["memory_id"], paths, expected_revision=2,
                )
        self.assertEqual(self.memory.get(root["memory_id"])["revision"], 2)
        self.assertEqual(self.memory.current_change_seq(), watermark)

    # 相同路径再次声明无新版本，CAS 冲突绝不能尝试覆盖后来合法决策。
    def test_cas_noop_and_restart_preserve_proof_history(self):
        sources, root, refs = self.alternative()
        before = self.memory.current_change_seq()
        same = self.memory.declare_proof_paths(
            root["memory_id"],
            [[refs["C"], refs["E"]], [refs["B"], refs["A"]]],
            expected_revision=2,
        )
        self.assertEqual(same["revision"], 2)
        self.assertEqual(self.memory.current_change_seq(), before)
        with self.assertRaisesRegex(MemoryDeltaError, "expected_revision"):
            self.memory.declare_proof_paths(
                root["memory_id"],
                [[refs["A"], refs["B"]], [refs["C"], refs["E"]]],
                expected_revision=1,
            )
        self.assertEqual(
            len(self.memory.revision_snapshot(root["memory_id"], 2)["proof_paths"]), 2
        )
        self.runtime.close()
        self.runtime = MythRuntime(self.root)
        self.memory = Workspace(self.runtime).memory
        self.memory.revoke(sources["B"]["memory_id"])
        self.assertEqual(self.memory.freshness(root["memory_id"])["status"], "fresh")

    # 更新正文后原 Proof 准入必须消失，不能假设先前证据自动证明新结论。
    def test_edit_resets_alternative_paths_and_keeps_old_revision(self):
        sources, root, _ = self.alternative()
        updated = self.memory.apply_delta(
            root["memory_id"],
            [{"op": "replace_text", "text": "New claim requiring new proof"}],
            expected_revision=2,
        )
        self.assertEqual(updated["revision"], 3)
        self.assertNotIn("proof_paths", self.memory.revision_snapshot(root["memory_id"], 3))
        self.assertIn("proof_paths", self.memory.revision_snapshot(root["memory_id"], 2))
        self.memory.revoke(sources["B"]["memory_id"])
        self.assertTrue(self.memory.freshness(root["memory_id"])["is_stale"])

    # 即使另一条证明还有效，依赖链中的私有作用域仍属于安全错误而非可忽略失败。
    def test_scope_violation_in_losing_branch_fails_closed(self):
        sources, root, _ = self.alternative()
        with self.runtime.store.tx() as db:
            db.execute(
                "UPDATE workspace_memories SET scope_type='session',scope_id='private' "
                "WHERE memory_id=?",
                (sources["A"]["memory_id"],),
            )
        report = self.memory.freshness(root["memory_id"])
        self.assertTrue(report["is_stale"])
        self.assertIn("scope_violation", [x["reason"] for x in report["stale_sources"]])
        with self.assertRaises(PermissionError):
            self.memory.resolve(root["memory_id"], resolution="L2")

    # 旧/外部 SQL 改写 Evidence 身份但不推进 Memory 版本时，签名不一致一律拒绝投影。
    def test_external_evidence_mutation_does_not_silently_rewrite_proof(self):
        _, root, _ = self.alternative()
        with self.runtime.store.tx() as db:
            db.execute(
                "UPDATE workspace_memory_evidence SET relevance='out-of-band' "
                "WHERE memory_id=?",
                (root["memory_id"],),
            )
        report = self.memory.freshness(root["memory_id"])
        self.assertTrue(report["is_stale"])
        self.assertIn("proof_paths_evidence_changed", [x["reason"] for x in report["stale_sources"]])
        with self.assertRaises(PermissionError):
            self.memory.resolve(root["memory_id"], resolution="L2")

    # 另一条 Proof 有效仍不能遮掩依赖图循环；安全结构缺陷全局一票否决。
    def test_cycle_in_one_alternative_cannot_be_hidden(self):
        sources, root, _ = self.alternative()
        with self.runtime.store.tx() as db:
            db.execute(
                "INSERT INTO workspace_memory_evidence("
                "memory_id,evidence_ref,source_memory_id,source_revision"
                ") VALUES (?,?,?,?)",
                (sources["A"]["memory_id"], "loop",
                 root["memory_id"], root["revision"]),
            )
        report = self.memory.freshness(root["memory_id"])
        self.assertTrue(report["is_stale"])
        self.assertIn("dependency_cycle", [x["reason"] for x in report["stale_sources"]])

    # 回滚新 Proof 声明时，当前 Memory、历史快照与变化水位不得出现部分提交。
    def test_failed_change_record_rolls_back_entire_proof_declaration(self):
        a, b = self.source("rollback-a"), self.source("rollback-b")
        root = self.memory.remember(
            kind="semantic", text="Rollback proof",
            source_ref="proof:rollback-root",
            evidence=[{"source_memory_id": a["memory_id"]},
                      {"source_memory_id": b["memory_id"]}],
        )
        watermark = self.memory.current_change_seq()
        refs = [[f"memory:{a['memory_id']}"], [f"memory:{b['memory_id']}"]]
        with patch.object(self.memory, "_record_change", side_effect=RuntimeError("disk error")):
            with self.assertRaisesRegex(RuntimeError, "disk error"):
                self.memory.declare_proof_paths(
                    root["memory_id"], refs, expected_revision=1,
                )
        self.assertEqual(self.memory.current_change_seq(), watermark)
        self.assertEqual(self.memory.get(root["memory_id"])["revision"], 1)
        self.assertNotIn("proof_paths", self.memory.revision_snapshot(root["memory_id"], 1))


if __name__ == "__main__":
    unittest.main()
