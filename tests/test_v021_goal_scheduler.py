"""回归边界：计划机会原子准入及恢复。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from myth.domain import IdentityConflict
from myth.goal_scheduler import GoalScheduler, utc_timestamp
from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


SETTINGS = {
    "provider": "ollama",
    "model": "test",
    "max_steps": 4,
    "max_output_tokens": 512,
}


# 计划机会原子准入及恢复的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class GoalSchedulerTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings(SETTINGS)
        self.goal = self.workspace.personal.create_goal("Scheduled real work")
        self.sid = self.repo.create_session()["id"]
        self.scheduler = GoalScheduler(self.workspace)
        self.now = time.time()

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 计划机会原子准入及恢复的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def schedule(self, interval=None, **overrides):
        value = {
            "session_id": self.sid,
            "prompt": "Continue useful work",
            "due_at": datetime.fromtimestamp(self.now, timezone.utc).isoformat(),
            "interval_seconds": interval,
            **overrides,
        }
        return self.scheduler.create(self.goal["goal_id"], value)

    # 回归断言：一次计划的 occurrence、Turn、Goal 关联同事务准入，然后关闭未来机会。
    def test_one_shot_atomically_admits_goal_run_then_disables(self):
        schedule = self.schedule()
        rid = self.scheduler.admit(schedule["schedule_id"], self.now + 1)
        current = self.scheduler.get(schedule["schedule_id"])
        self.assertFalse(current["enabled"])
        self.assertEqual(current["wakeups"][0]["run_id"], rid)
        self.assertEqual(
            self.workspace.personal.runs(self.goal["goal_id"])[0]["run_id"], rid
        )
        self.assertEqual(
            self.workspace.personal.work_state(self.goal["goal_id"])["last_run_id"], rid
        )
        self.assertIsNone(self.scheduler.admit(schedule["schedule_id"], self.now + 2))
        self.workspace.run(rid, ChatProvider())
        self.assertEqual(self.repo.turn(rid)["status"], "COMPLETED")
        self.assertIn(
            "GoalWakeupAdmitted", [event["kind"] for event in self.repo.events(rid)]
        )

    # 回归断言：未到时间/已关闭计划不创建工作或预算。
    def test_not_yet_due_or_disabled_never_creates_run(self):
        schedule = self.schedule()
        self.assertIsNone(self.scheduler.admit(schedule["schedule_id"], self.now - 1))
        self.scheduler.set_enabled(schedule["schedule_id"], False)
        self.assertIsNone(self.scheduler.admit(schedule["schedule_id"], self.now + 1))
        self.assertEqual(
            self.runtime.store.db.execute("SELECT count(*) FROM runs").fetchone()[0], 0
        )

    # 回归断言：显式时区归一为 UTC，缺时区时间拒绝以免静默偏移。
    def test_offset_time_is_normalized_and_naive_time_rejected(self):
        self.assertEqual(
            utc_timestamp("2026-10-03T08:00:00+08:00"),
            utc_timestamp("2026-10-03T00:00:00Z"),
        )
        for due in (None, "2026-10-03T08:00", "not-a-date"):
            with self.assertRaises(ValueError):
                self.schedule(due_at=due)
        for interval in (True, 0, 59, 31536001, "600"):
            with self.assertRaises(ValueError):
                self.schedule(interval)

    # 回归断言：停机错过的间隔合并一次，不逐项补跑制造工作风暴。
    def test_intervals_coalesce_downtime_without_backlog(self):
        schedule = self.schedule(60)
        rid = self.scheduler.admit(schedule["schedule_id"], self.now + 3601)
        current = self.scheduler.get(schedule["schedule_id"])
        self.assertEqual(len(current["wakeups"]), 1)
        self.assertGreater(utc_timestamp(current["due_at"]), self.now + 3601)
        self.assertIsNone(
            self.scheduler.admit(schedule["schedule_id"], self.now + 3602)
        )
        self.workspace.run(rid, ChatProvider())
        second = self.scheduler.admit(schedule["schedule_id"], self.now + 3661)
        self.assertNotEqual(second, rid)
        self.assertEqual(self.scheduler.get(schedule["schedule_id"])["sequence"], 3)

    # 回归断言：计划创建时固定模型设置；后来全局设置不偷换该工作。
    def test_settings_are_frozen_at_schedule_creation(self):
        schedule = self.schedule()
        self.repo.save_settings({**SETTINGS, "model": "changed-model"})
        rid = self.scheduler.admit(schedule["schedule_id"], self.now + 1)
        self.assertEqual(self.repo.turn(rid)["settings"]["model"], "test")

    # 回归断言：长期意图暂停/等待阻止下一机会，但不抹去当前执行事实。
    def test_goal_pause_and_waiting_block_new_admission(self):
        schedule = self.schedule()
        self.workspace.personal.set_goal_state(self.goal["goal_id"], "PAUSED")
        with self.assertRaises(ValueError):
            self.scheduler.admit(schedule["schedule_id"], self.now + 1)
        self.workspace.personal.set_goal_state(self.goal["goal_id"], "ACTIVE")
        self.workspace.personal.update_work_state(
            self.goal["goal_id"], current_state="WAITING", waiting_for="user decision"
        )
        with self.assertRaises(ValueError):
            self.scheduler.admit(schedule["schedule_id"], self.now + 1)
        self.assertEqual(self.scheduler.get(schedule["schedule_id"])["wakeups"], [])

    # 回归断言：会话忙时保存拒绝/延后检查，不消费 occurrence 序号。
    def test_session_busy_defers_without_consuming_occurrence(self):
        schedule = self.schedule()
        self.repo.create_turn(self.sid, "ordinary work", "ordinary")
        with self.assertRaises(ValueError):
            self.scheduler.admit(schedule["schedule_id"], self.now + 1)
        current = self.scheduler.get(schedule["schedule_id"])
        self.assertTrue(current["enabled"])
        self.assertEqual(current["sequence"], 1)
        self.assertEqual(current["wakeups"], [])

    # 回归断言：归档 Session/非活动 Goal 不能创建可执行计划。
    def test_archived_session_and_inactive_goal_cannot_be_scheduled(self):
        self.repo.update_session(self.sid, {"archived": True})
        with self.assertRaises(ValueError):
            self.schedule()
        self.repo.update_session(self.sid, {"archived": False})
        self.workspace.personal.set_goal_state(self.goal["goal_id"], "COMPLETED")
        with self.assertRaises(ValueError):
            self.schedule()

    # 回归断言：故障注入让准入提交失败；机会、Turn、预算和 Goal 进度一起回滚。
    def test_wakeup_and_goal_checkpoint_rollback_with_failed_commit(self):
        schedule = self.schedule()
        before = self.workspace.personal.work_state(self.goal["goal_id"])
        event = self.runtime.store._event

        # 计划机会原子准入及恢复的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def crash(db, rid, kind, payload):
            if kind == "GoalWakeupAdmitted":
                raise RuntimeError("injected commit boundary")
            event(db, rid, kind, payload)

        with patch.object(self.runtime.store, "_event", side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.scheduler.admit(schedule["schedule_id"], self.now + 1)
        self.assertEqual(
            self.runtime.store.db.execute("SELECT count(*) FROM runs").fetchone()[0], 0
        )
        self.assertEqual(
            self.workspace.personal.work_state(self.goal["goal_id"]), before
        )
        self.assertEqual(self.scheduler.get(schedule["schedule_id"])["sequence"], 1)
        self.assertIsNotNone(
            self.scheduler.admit(schedule["schedule_id"], self.now + 1)
        )

    # 回归断言：真实两个连接争抢同一机会，只能提交一个 Run。
    def test_two_connections_admit_one_occurrence(self):
        schedule = self.schedule()
        barrier = threading.Barrier(2)
        outcomes, errors = [], []

        # 计划机会原子准入及恢复的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def admit():
            try:
                with MythRuntime(self.root) as runtime:
                    scheduler = GoalScheduler(Workspace(runtime))
                    barrier.wait(5)
                    outcomes.append(
                        scheduler.admit(schedule["schedule_id"], self.now + 1)
                    )
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=admit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(errors, [])
        self.assertEqual(sum(rid is not None for rid in outcomes), 1)
        self.assertEqual(len(self.scheduler.get(schedule["schedule_id"])["wakeups"]), 1)

    # 回归断言：同 Goal 跨 Session 也不能同时拥有两个活跃工作。
    def test_goal_cannot_admit_overlapping_work_across_sessions(self):
        first = self.schedule()
        other_sid = self.repo.create_session()["id"]
        second = self.schedule(session_id=other_sid)
        self.scheduler.admit(first["schedule_id"], self.now + 1)
        with self.assertRaises(ValueError):
            self.scheduler.admit(second["schedule_id"], self.now + 1)
        self.assertEqual(len(self.workspace.personal.runs(self.goal["goal_id"])), 1)

    # 回归断言：准入提交后进程退出，重启派发原机会身份而非另建 Run。
    def test_process_dies_after_admission_restart_dispatches_same_run(self):
        schedule = self.schedule()
        code = (
            "import os,sys;from myth.runtime import MythRuntime;from myth.workspace import Workspace;"
            "from myth.goal_scheduler import GoalScheduler;"
            "r=MythRuntime(sys.argv[1]);s=GoalScheduler(Workspace(r));"
            "s.admit(sys.argv[2],float(sys.argv[3]));os._exit(73)"
        )
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
                str(self.root),
                schedule["schedule_id"],
                str(self.now + 1),
            ],
            timeout=10,
        )
        self.assertEqual(process.returncode, 73)
        rid = self.scheduler.get(schedule["schedule_id"])["wakeups"][0]["run_id"]
        self.assertIn(rid, self.scheduler.dispatchable_runs())
        self.workspace.run(rid, ChatProvider())
        self.assertEqual(self.repo.turn(rid)["status"], "COMPLETED")
        self.assertIsNone(self.scheduler.admit(schedule["schedule_id"], self.now + 2))

    # 回归断言：已准入工作效果未知时定时器不盲目继续。
    def test_unknown_occurrence_is_not_automatically_replayed(self):
        schedule = self.schedule()
        rid = self.scheduler.admit(schedule["schedule_id"], self.now + 1)
        provider = ChatProvider()
        provider.invoke = lambda request: (_ for _ in ()).throw(
            RuntimeError("ambiguous timeout")
        )
        self.workspace.run(rid, provider)
        self.assertEqual(self.repo.turn(rid)["status"], "UNKNOWN")
        self.assertNotIn(rid, self.scheduler.dispatchable_runs())
        self.assertEqual(
            self.workspace.personal.work_state(self.goal["goal_id"])["current_state"],
            "RECONCILE",
        )

    # 回归断言：连接检查失败保留到期机会，未来检查不需要改题或换身份。
    def test_provider_unavailable_keeps_due_timer_for_later_retry(self):
        schedule = self.schedule(
            due_at=datetime.fromtimestamp(self.now - 1, timezone.utc).isoformat()
        )
        service = ConversationWebService(self.root)
        service.connection = lambda settings: {"ready": False}
        service.scheduler_tick()
        current = self.scheduler.get(schedule["schedule_id"])
        self.assertTrue(current["enabled"])
        self.assertEqual(current["wakeups"], [])
        self.assertIn("not connected", current["last_error"])
        self.assertEqual(self.scheduler.due(), [])

    # 回归断言：计划工作共用正常 Driver/Control，而非绕开授权的快捷执行路径。
    def test_timer_runs_through_normal_driver_and_control(self):
        schedule = self.schedule(
            due_at=datetime.fromtimestamp(self.now - 1, timezone.utc).isoformat()
        )
        service = ConversationWebService(self.root)
        provider = ChatProvider()
        service.connection = lambda settings: {
            "ready": True,
            "details": {"models": ["test"]},
        }
        service.provider = lambda settings: provider
        service.start_scheduler()
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                wakes = self.scheduler.get(schedule["schedule_id"])["wakeups"]
                if wakes and wakes[0]["status"] == "COMPLETED" and not service.active:
                    break
                time.sleep(0.02)
            self.assertEqual(wakes[0]["status"], "COMPLETED")
            rid = wakes[0]["run_id"]
            self.assertEqual(len(provider.calls), 1)
            kinds = [e["kind"] for e in self.repo.events(rid)]
            self.assertIn("DriverLeaseAcquired", kinds)
            self.assertIsNotNone(self.workspace.control.view(rid))
        finally:
            service.stop_scheduler()
        self.assertFalse(service.scheduler_thread.is_alive())

    # 回归断言：一次机会已消费不能以启用开关变成另一项工作。
    def test_one_shot_cannot_be_rearmed_after_it_fires(self):
        schedule = self.schedule()
        self.scheduler.admit(schedule["schedule_id"], self.now + 1)
        with self.assertRaises(ValueError):
            self.scheduler.set_enabled(schedule["schedule_id"], True)

    # 回归断言：计划执行后同 request_id 重试仍返回原计划身份。
    def test_schedule_request_retry_after_firing_preserves_identity(self):
        schedule = self.schedule(request_id="same-schedule-request")
        self.scheduler.admit(schedule["schedule_id"], self.now + 1)
        retry = self.schedule(request_id="same-schedule-request")
        self.assertEqual(retry["schedule_id"], schedule["schedule_id"])
        self.assertFalse(retry["enabled"])
        self.assertEqual(len(self.scheduler.list()), 1)
        with self.assertRaises(IdentityConflict):
            self.schedule(request_id="same-schedule-request", prompt="different")


    # 回归断言：无效 Goal 拒绝整体准入，相同意图重试不受环境进度变化影响。
    def test_invalid_goal_admission_and_request_retry_are_atomic(self):
        with self.assertRaises(KeyError):
            self.repo.create_turn(self.sid, "work", "invalid", goal_id="goal_missing")
        self.assertEqual(
            self.runtime.store.db.execute("SELECT count(*) FROM runs").fetchone()[0], 0
        )
        one = self.repo.create_turn(
            self.sid, "work", "valid", goal_id=self.goal["goal_id"]
        )
        revision = self.workspace.personal.work_state(self.goal["goal_id"])["revision"]
        retry = self.repo.create_turn(
            self.sid, "work", "valid", goal_id=self.goal["goal_id"]
        )
        self.assertEqual(one["run_id"], retry["run_id"])
        self.assertEqual(
            self.workspace.personal.work_state(self.goal["goal_id"])["revision"],
            revision,
        )
        other = self.workspace.personal.create_goal("Other")
        with self.assertRaises(IdentityConflict):
            self.repo.create_turn(self.sid, "work", "valid", goal_id=other["goal_id"])

    # 回归断言：旧 Run 迟到 checkpoint 不覆盖新准入工作进度。
    def test_late_old_goal_checkpoint_cannot_overwrite_new_turn(self):
        first = self.repo.create_turn(
            self.sid, "first", "first", goal_id=self.goal["goal_id"]
        )
        step = self.repo.begin_step(first["run_id"])
        self.repo.finish_reply(first["run_id"], step["step"], "First result")
        second = self.repo.create_turn(
            self.sid, "second", "second", goal_id=self.goal["goal_id"]
        )
        before = self.workspace.personal.work_state(self.goal["goal_id"])
        self.workspace.personal.checkpoint_run(
            self.goal["goal_id"],
            first["run_id"],
            status="COMPLETED",
            summary="late old result",
        )
        current = self.workspace.personal.work_state(self.goal["goal_id"])
        self.assertEqual(current, before)
        self.assertEqual(current["last_run_id"], second["run_id"])
        self.assertEqual(current["current_state"], "IN_PROGRESS")


# 计划机会原子准入及恢复的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class ToolPreflightTests(unittest.TestCase):
    # 回归断言：合同错误在工具 Ticket 前为已知拒绝，后续模型可纠正而不留下 UNKNOWN。
    def test_bad_patch_is_known_rejection_then_corrected_without_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "settings.txt").write_bytes(b"mode=old\n")
            with MythRuntime(root) as runtime:
                workspace = Workspace(runtime)
                repo = workspace.repository
                repo.save_settings(SETTINGS)
                project = repo.create_project({"name": "fixture", "root": str(root)})
                sid = repo.create_session(project_id=project["id"])["id"]
                rid = repo.create_turn(sid, "change old to new", "patch-retry")[
                    "run_id"
                ]
                provider = ChatProvider(
                    [
                        decision(
                            "tool_call",
                            "project.patch_exact",
                            {
                                "path": "settings.txt",
                                "old_text": "missing",
                                "new_text": "new",
                                "expected_count": 1,
                            },
                        ),
                        decision(
                            "tool_call",
                            "project.patch_exact",
                            {
                                "path": "settings.txt",
                                "old_text": "old",
                                "new_text": "new",
                                "expected_count": 1,
                            },
                        ),
                        decision(claim="corrected"),
                    ]
                )
                workspace.run(rid, provider)
                turn = repo.turn(rid)
                self.assertEqual(turn["status"], "COMPLETED")
                self.assertIn("found 0", turn["activities"][0]["result"]["error"])
                self.assertEqual(len(repo.operations(rid)), 1)
                artifact = turn["activities"][1]["result"]["artifact"]
                self.assertEqual(runtime.objects.get(artifact["digest"]), b"mode=new\n")
                self.assertEqual((root / "settings.txt").read_bytes(), b"mode=old\n")
                self.assertNotIn(
                    "UNKNOWN", [e["payload"].get("status") for e in repo.events(rid)]
                )


if __name__ == "__main__":
    unittest.main()
