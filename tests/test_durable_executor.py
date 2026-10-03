"""回归边界：独立 Durable Executor、同 Run 恢复与无进展观测。
本文件固定本机 SQLite/线程夹具；通过只证明执行器与 Web 解耦边界，不证明真实远端供应商可用。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest

from myth.durable_executor import DurableExecutor, executor_snapshot, run_liveness
from myth.goal_scheduler import GoalScheduler
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from test_workspace import ChatProvider


# 独立执行器固定测试集合；临时 Runtime 由每个用例拥有，所有结果从持久仓储重新读取。
class DurableExecutorTests(unittest.TestCase):
    # 建立独立 Runtime、固定模型设置和会话；不启动 Web/HTTP 线程。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            workspace.repository.save_settings({"provider": "ollama", "model": "test"})
            self.sid = workspace.repository.create_session()["id"]

    # 停止测试持有的 worker 并清理临时目录；不能让线程跨用例污染状态。
    def tearDown(self):
        self.tmp.cleanup()

    # 等待某 Run 离开 RUNNING/INTERRUPTED；读取来自新连接，避免依赖 worker 内存状态。
    def wait_turn(self, run_id, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with MythRuntime(self.root) as runtime:
                turn = Workspace(runtime).repository.turn(run_id)
            if turn["status"] not in {"RUNNING", "INTERRUPTED"}:
                return turn
            time.sleep(0.02)
        self.fail("durable executor did not reach a durable yield")

    # 回归断言：没有 Web Driver 的普通 Turn 由独立 worker 接管，并继续原 run_id 而不是创建替代任务。
    def test_worker_recovers_plain_turn_without_web_lifecycle(self):
        with MythRuntime(self.root) as runtime:
            repository = Workspace(runtime).repository
            rid = repository.create_turn(
                self.sid, "long work", "durable-worker-plain"
            )["run_id"]
        provider = ChatProvider()
        executor = DurableExecutor(
            self.root, poll_seconds=0.05, provider_factory=lambda settings: provider
        )
        self.assertTrue(executor.claim())
        try:
            self.assertGreaterEqual(executor.tick(), 1)
            turn = self.wait_turn(rid)
            self.assertEqual(turn["status"], "COMPLETED")
            self.assertEqual(len(provider.calls), 1)
            with MythRuntime(self.root) as runtime:
                rows = runtime.store.db.execute(
                    "SELECT run_id FROM workspace_turns"
                ).fetchall()
                self.assertEqual([row["run_id"] for row in rows], [rid])
                self.assertTrue(executor_snapshot(runtime)["active"])
        finally:
            executor.release()

    # 回归断言：UNKNOWN 不进入自动 dispatch 候选；后台 worker 不能把不明模型效果盲目重放。
    def test_unknown_turn_is_never_automatically_redispatched(self):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            rid = workspace.repository.create_turn(
                self.sid, "uncertain work", "durable-worker-unknown"
            )["run_id"]
            failing = ChatProvider()
            failing.invoke = lambda request: (_ for _ in ()).throw(
                RuntimeError("ambiguous provider timeout")
            )
            workspace.run(rid, failing)
            self.assertEqual(workspace.repository.turn(rid)["status"], "UNKNOWN")

        provider = ChatProvider()
        executor = DurableExecutor(
            self.root, poll_seconds=0.05, provider_factory=lambda settings: provider
        )
        self.assertTrue(executor.claim())
        try:
            self.assertEqual(executor.tick(), 0)
            time.sleep(0.05)
            self.assertEqual(len(provider.calls), 0)
            with MythRuntime(self.root) as runtime:
                turn = Workspace(runtime).repository.turn(rid)
                self.assertEqual(turn["status"], "UNKNOWN")
                self.assertEqual(
                    turn["execution_cursor"]["recovery_state"], "RECONCILE"
                )
        finally:
            executor.release()

    # 回归断言：Goal 到期机会由独立执行器准入和驱动；不依赖 Web 内两秒 scheduler 线程。
    def test_worker_admits_and_runs_due_goal_schedule(self):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            goal = workspace.personal.create_goal("Durable scheduled goal")
            schedule = GoalScheduler(workspace).create(
                goal["goal_id"],
                {
                    "request_id": "durable-schedule",
                    "session_id": self.sid,
                    "prompt": "scheduled work",
                    "due_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        provider = ChatProvider()
        executor = DurableExecutor(
            self.root, poll_seconds=0.05, provider_factory=lambda settings: provider
        )
        self.assertTrue(executor.claim())
        try:
            self.assertGreaterEqual(executor.tick(), 1)
            with MythRuntime(self.root) as runtime:
                current = GoalScheduler(Workspace(runtime)).get(schedule["schedule_id"])
                rid = current["wakeups"][0]["run_id"]
            turn = self.wait_turn(rid)
            self.assertEqual(turn["status"], "COMPLETED")
            self.assertEqual(len(provider.calls), 1)
        finally:
            executor.release()

    # 回归断言：Driver 心跳存活但 checkpoint 长时间不动时只标记疑似无进展，不擅自失败/重试。
    def test_live_heartbeat_does_not_fake_progress(self):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            rid = workspace.repository.create_turn(
                self.sid, "stuck work", "durable-worker-liveness"
            )["run_id"]
            self.assertTrue(
                workspace.repository.claim_driver(rid, "fixture-driver", 60.0)
            )
            with runtime.store.tx() as db:
                db.execute(
                    "UPDATE workspace_execution_cursors "
                    "SET updated_at='2020-01-01 00:00:00' WHERE run_id=?",
                    (rid,),
                )
            observed = run_liveness(
                workspace.repository, rid, threshold_seconds=1.0
            )
            self.assertTrue(observed["driver_heartbeat_live"])
            self.assertTrue(observed["suspected_no_progress"])
            self.assertEqual(workspace.repository.turn(rid)["status"], "RUNNING")


if __name__ == "__main__":
    unittest.main()
