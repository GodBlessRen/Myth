"""回归边界：个人状态所有权与真实 SQL 故障回滚。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from pathlib import Path
import sqlite3
import tempfile
import threading
import traceback
import unittest
from unittest.mock import patch

from myth.runtime import MythRuntime
from myth.domain import BudgetExceeded
from myth.goal_scheduler import GoalScheduler
from myth.artifacts import ObjectStore, atomic_write
from myth.domain import sha256_bytes
from myth.workspace import Workspace


# 个人状态所有权与真实 SQL 故障回滚的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class StateBoundaryTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.temp.name))
        self.workspace = Workspace(self.runtime)
        self.workspace.repository.save_settings(
            {"provider": "ollama", "model": "fixture"}
        )

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    # 核对准入业务事实全为空；允许事务外准备的私有字节残留，但它们没有 Run/Ticket 身份。
    def assert_no_patch_admission(self):
        for table in (
            "runs",
            "accounts",
            "actions",
            "attempts",
            "reservations",
            "tickets",
            "events",
        ):
            self.assertEqual(
                self.runtime.store.db.execute(
                    f"SELECT count(*) FROM {table}"
                ).fetchone()[0],
                0,
                table,
            )

    # 原始文件属于明确测试夹具；失败/恢复均不得覆盖它，替换只交后续受管执行。
    def patch_source(self):
        source = Path(self.temp.name) / "source.txt"
        source.write_text("before", encoding="utf-8")
        return source

    # 模拟 Windows 并发发布赢家已存在时 replace 被拒绝；只有完全相同对象才能复用，不新增效果重试。
    def test_object_publish_permission_race_reuses_identical_winner(self):
        objects = ObjectStore(Path(self.temp.name) / "object-race")
        data = b"same immutable bytes"

        # 先真实发布赢家字节，再注入 replace 拒绝；避免把一般权限错误无条件当作成功。
        def winner(path, content):
            atomic_write(path, content)
            raise PermissionError("injected competing reader")

        with patch("myth.artifacts.atomic_write", side_effect=winner):
            digest = objects.put(data)
        self.assertEqual(digest, sha256_bytes(data))
        self.assertEqual(objects.get(digest), data)

    # 同路径已有错误字节不能借并发恢复分支冒充正确对象；保留明确失败，不覆写异常赢家。
    def test_object_publish_permission_race_rejects_conflicting_winner(self):
        objects = ObjectStore(Path(self.temp.name) / "object-conflict")

        # 固定制造内容冲突，证明路径存在本身不足以消除不确定或损坏。
        def wrong_winner(path, content):
            atomic_write(path, b"wrong content")
            raise PermissionError("injected conflicting publisher")

        with patch("myth.artifacts.atomic_write", side_effect=wrong_winner):
            with self.assertRaises(PermissionError):
                objects.put(b"expected bytes")

    # 回归断言：内容寻址对象即使 symlink 目标字节完全一致也不能当作可信对象复用或读取。
    @unittest.skipIf(not hasattr(Path, "symlink_to"), "symlink is unavailable")
    def test_object_store_rejects_symlink_substitution(self):
        objects = ObjectStore(Path(self.temp.name) / "object-symlink")
        data = b"bound evidence"
        digest = objects.put(data)
        path = objects._path(digest)
        target = Path(self.temp.name) / "same-bytes.txt"
        target.write_bytes(data)
        path.unlink()
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is not permitted on this platform")
        with self.assertRaises(IOError):
            objects.get(digest)
        with self.assertRaises(IOError):
            objects.put(data)

    # 故障在数据库准入之前：私有副本准备失败不能残留 Run，同 request_id 修复后可完整准入。
    def test_patch_baseline_failure_has_no_run_and_same_request_can_retry(self):
        source = self.patch_source()
        with patch.object(
            self.runtime.workspaces,
            "materialize",
            side_effect=OSError("injected copy failure"),
        ):
            with self.assertRaises(OSError):
                self.runtime.submit_patch(
                    source,
                    old_text="before",
                    new_text="after",
                    expected_count=1,
                    request_id="copy-failure",
                )
        self.assert_no_patch_admission()
        rid = self.runtime.submit_patch(
            source,
            old_text="before",
            new_text="after",
            expected_count=1,
            request_id="copy-failure",
        )
        self.assertEqual(self.runtime.store.get_action_for_run(rid)["run_id"], rid)
        self.assertEqual(source.read_text(encoding="utf-8"), "before")

    # 故障在第二个仓储写入：触发器拒绝 Action 时 Run、账号、事件一起回滚，而非留下空 Run。
    def test_patch_intent_failure_rolls_back_run_accounts_and_events(self):
        source = self.patch_source()
        self.runtime.store.db.execute(
            "CREATE TRIGGER reject_action BEFORE INSERT ON actions BEGIN SELECT RAISE(ABORT,'injected intent failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.runtime.submit_patch(
                source,
                old_text="before",
                new_text="after",
                expected_count=1,
                request_id="intent-failure",
            )
        self.assert_no_patch_admission()

    # 故障在资源预留：任一 meter 不足时初始 Run/Intent 也整体撤回，不能提交无可执行机会的入口。
    def test_patch_reservation_failure_rolls_back_the_entire_admission(self):
        source = self.patch_source()
        with self.assertRaises(BudgetExceeded):
            self.runtime.submit_patch(
                source,
                old_text="before",
                new_text="after",
                expected_count=1,
                request_id="budget-failure",
                budgets={"tool_calls": 0, "write_bytes": 100},
            )
        self.assert_no_patch_admission()

    # 两个实际连接在事务外都准备好私有基线后争抢；唯一入口必须只有一个完整 Run/Action/Attempt。
    def test_two_patch_connections_commit_one_complete_initial_intent(self):
        source = self.patch_source()
        barrier = threading.Barrier(2)
        results, errors = [], []
        result_lock = threading.Lock()

        # 每个线程拥有自己的 Runtime/连接；同步点固定在副本准备后，强制覆盖事务内第二次去重。
        def admit():
            try:
                with MythRuntime(Path(self.temp.name)) as runtime:
                    original = runtime.workspaces.materialize

                    # 仅同步准备，不在事务中等待；并发业务提交仍通过 SQLite 单写者规则竞争。
                    def prepared(*args):
                        original(*args)
                        barrier.wait(timeout=5)

                    with patch.object(
                        runtime.workspaces, "materialize", side_effect=prepared
                    ):
                        rid = runtime.submit_patch(
                            source,
                            old_text="before",
                            new_text="after",
                            expected_count=1,
                            request_id="competing-entry",
                        )
                    with result_lock:
                        results.append(rid)
            except BaseException as exc:
                with result_lock:
                    errors.append(traceback.format_exc())

        threads = [threading.Thread(target=admit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(set(results)), 1)
        for table in ("runs", "actions", "attempts"):
            self.assertEqual(
                self.runtime.store.db.execute(
                    f"SELECT count(*) FROM {table}"
                ).fetchone()[0],
                1,
                table,
            )

    # 显式事务协作不能传入另一连接或已提交连接；拒绝发生在任何 Core 写入前。
    def test_core_admission_rejects_foreign_or_inactive_transaction(self):
        with self.assertRaises(RuntimeError):
            self.runtime.store.admission_transaction(self.runtime.store.db)
        with MythRuntime(Path(self.temp.name)) as other:
            with other.store.tx() as db:
                with self.assertRaises(RuntimeError):
                    self.runtime.store.admission_transaction(db)
        self.assert_no_patch_admission()

    # 历史 Goal 缺工作状态时，调度在同一准入事务补齐；不能触发嵌套事务或只留下初始化进度。
    def test_schedule_initializes_legacy_goal_inside_its_admission_transaction(self):
        goal = self.workspace.personal.create_goal("legacy goal")
        session = self.workspace.repository.create_session()
        scheduler = GoalScheduler(self.workspace)
        schedule = scheduler.create(
            goal["goal_id"],
            {
                "session_id": session["id"],
                "prompt": "continue",
                "due_at": "2020-01-01T00:00:00Z",
                "request_id": "legacy-admission",
            },
        )
        self.runtime.store.db.execute(
            "DELETE FROM goal_work_state WHERE goal_id=?", (goal["goal_id"],)
        )
        rid = scheduler.admit(schedule["schedule_id"])
        self.assertEqual(
            self.workspace.personal.work_state(goal["goal_id"])["last_run_id"],
            rid,
        )
        self.assertEqual(len(scheduler.get(schedule["schedule_id"])["wakeups"]), 1)

    # 回归断言：第二次初始进度写入触发真实 SQL 错误，Goal 也整体回滚。
    def test_goal_and_initial_work_state_rollback_together(self):
        self.runtime.store.db.execute(
            "CREATE TRIGGER reject_work BEFORE INSERT ON goal_work_state "
            "BEGIN SELECT RAISE(ABORT,'injected work failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.workspace.personal.create_goal("atomic goal")
        self.assertEqual(
            self.runtime.store.db.execute("SELECT count(*) FROM goals").fetchone()[0], 0
        )
        self.assertEqual(
            self.runtime.store.db.execute(
                "SELECT count(*) FROM goal_work_state"
            ).fetchone()[0],
            0,
        )

    # 回归断言：Goal link 写入失败时 Turn/预算/长期进度整项回滚。
    def test_personal_binding_failure_rolls_back_turn_budgets_and_goal(self):
        goal = self.workspace.personal.create_goal("binding")
        session = self.workspace.repository.create_session()
        before = self.workspace.personal.goal_view(goal["goal_id"])
        self.runtime.store.db.execute(
            "CREATE TRIGGER reject_link BEFORE INSERT ON goal_runs "
            "BEGIN SELECT RAISE(ABORT,'injected link failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.workspace.repository.create_turn(
                session["id"], "task", "request", goal_id=goal["goal_id"]
            )
        self.assertEqual(self.workspace.repository.session(session["id"])["turns"], [])
        self.assertEqual(
            self.runtime.store.db.execute("SELECT count(*) FROM accounts").fetchone()[
                0
            ],
            0,
        )
        self.assertEqual(self.workspace.personal.goal_view(goal["goal_id"]), before)

    # 回归断言：工作区调用个人状态所有者且连接/活动事务身份一致。
    def test_workspace_uses_personal_owner_inside_the_same_transaction(self):
        goal = self.workspace.personal.create_goal("ownership")
        session = self.workspace.repository.create_session()
        owner = self.workspace.personal
        original = owner.bind_admitted_run

        # 在个人状态写入协作点检查同连接/活动事务，然后调用原实现；不另行提交。
        def bind(db, goal_id, run_id):
            self.assertIs(db, self.runtime.store.db)
            self.assertTrue(db.in_transaction)
            original(db, goal_id, run_id)

        with patch.object(owner, "bind_admitted_run", side_effect=bind) as binding:
            turn = self.workspace.repository.create_turn(
                session["id"], "task", "request", goal_id=goal["goal_id"]
            )
        binding.assert_called_once()
        self.assertEqual(
            owner.work_state(goal["goal_id"])["last_run_id"], turn["run_id"]
        )

    # 回归断言：个人准入协作拒绝无事务或其他连接，防止伪原子提交。
    def test_personal_admission_rejects_foreign_or_uncommitted_connection(self):
        goal = self.workspace.personal.create_goal("connection")
        with self.assertRaises(RuntimeError):
            self.workspace.personal.admission_snapshot(
                self.runtime.store.db, goal["goal_id"]
            )
        with MythRuntime(Path(self.temp.name)) as other:
            with other.store.tx() as db:
                with self.assertRaises(RuntimeError):
                    self.workspace.personal.admission_snapshot(db, goal["goal_id"])


if __name__ == "__main__":
    unittest.main()
