"""控制命令的真实 SQLite 故障窗口。

触发器在后半段写入拒绝提交，第二连接模拟并发回答；核对命令、Turn、
Core、Goal 与事件只能一起提交，不能把部分成功留给下一次 HTTP 请求补救。
"""

from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from myth.runtime import MythRuntime
from myth.workspace import Workspace


class ControlAtomicityTests(unittest.TestCase):
    """每例使用独立根、真实仓储和预算；不调用外部模型或用户项目。"""

    def setUp(self):
        """同时准入 Goal 和 Turn，使跨聚合的部分提交可以从持久事实识别。"""
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.workspace.repository.save_settings({"provider": "ollama", "model": "fixture"})
        self.goal = self.workspace.personal.create_goal("控制原子性")
        session = self.workspace.repository.create_session("原子控制")
        self.rid = self.workspace.repository.create_turn(
            session["id"], "review this task", "control-atomic", goal_id=self.goal["goal_id"]
        )["run_id"]
        self.workspace.control.ensure(self.rid)

    def tearDown(self):
        """先关闭数据库，再删除本例临时目录。"""
        self.runtime.close()
        self.temp.cleanup()

    def facts(self):
        """读取控制会修改的所有表；比较完整行可发现状态、计量或事件的残留。"""
        return {
            table: [tuple(row) for row in self.runtime.store.db.execute(f"SELECT * FROM {table}")]
            for table in (
                "workspace_control_projection", "workspace_control_commands", "workspace_turns",
                "runs", "accounts", "workspace_operations", "workspace_execution_cursors",
                "workspace_network_retries", "goal_work_state", "goals", "events",
            )
        }

    def assert_projection_failure(self, command):
        """后半段真实 SQL 拒绝后比较全部事实；每个命令独立夹具，失败不会污染下一例。"""
        if command == "resume":
            self.workspace.control.command(self.rid, "pause")
        before = self.facts()
        self.runtime.store.db.execute(
            "CREATE TEMP TRIGGER fail_state BEFORE UPDATE OF status ON workspace_turns "
            "BEGIN SELECT RAISE(ABORT, 'injected state failure'); END"
        )
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "injected state failure"):
                self.workspace.control.command(self.rid, command)
            self.assertEqual(self.facts(), before)
        finally:
            self.runtime.store.db.execute("DROP TRIGGER fail_state")

    def test_failed_pause_rolls_back_entire_command(self):
        """暂停投影失败，命令和当前状态一起回滚。"""
        self.assert_projection_failure("pause")

    def test_failed_resume_rolls_back_entire_command(self):
        """恢复投影失败，持久暂停标志不能提前清除。"""
        self.assert_projection_failure("resume")

    def test_failed_stop_rolls_back_entire_command(self):
        """终止投影失败，不残留无法继续操作的 stopped 标志。"""
        self.assert_projection_failure("stop")

    def test_goal_checkpoint_commits_without_web_followup(self):
        """任意入口发出的控制都应更新 Goal；不依赖 Web 成功返回后的第二次调用。"""
        for command, status in (("pause", "PAUSED"), ("resume", "IN_PROGRESS"), ("stop", "PAUSED")):
            self.workspace.control.command(self.rid, command)
            work = self.workspace.personal.work_state(self.goal["goal_id"])
            self.assertEqual(work["current_state"], status)
            self.assertEqual(work["last_run_id"], self.rid)

    def test_goal_failure_rolls_back_control_and_turn(self):
        """Goal checkpoint 失败时命令、Turn、Core 和事件全部回滚，原请求可重新执行。"""
        before = self.facts()
        self.runtime.store.db.execute(
            "CREATE TEMP TRIGGER fail_goal BEFORE UPDATE ON goal_work_state "
            "BEGIN SELECT RAISE(ABORT, 'injected goal failure'); END"
        )
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "injected goal failure"):
                self.workspace.control.command(self.rid, "pause")
            self.assertEqual(self.facts(), before)
        finally:
            self.runtime.store.db.execute("DROP TRIGGER fail_goal")
        self.workspace.control.command(self.rid, "pause")
        self.assertEqual(self.workspace.repository.turn(self.rid)["status"], "PAUSED")

    def test_gate_cannot_overwrite_a_concurrently_completed_answer(self):
        """在旧安全点的读写间提交回答；只接受暂停先赢或回答先赢的串行结果。"""
        repository = self.workspace.repository
        step = repository.begin_step(self.rid)["step"]
        # 固定旧版崩溃后可能出现的待投影 Pause，下一次 gate 应安全消费。
        self.runtime.store.db.execute(
            "UPDATE workspace_control_projection SET paused=1 WHERE run_id=?", (self.rid,)
        )
        ready = threading.Event()
        finish = threading.Event()
        done = threading.Event()
        errors = []

        def complete():
            """第二连接只尝试一次已准入回答；控制事务先提交时回答必须让步。"""
            try:
                with MythRuntime(self.root) as runtime:
                    other = Workspace(runtime)
                    ready.set()
                    if not finish.wait(5):
                        raise TimeoutError("gate did not reach projection")
                    other.repository.finish_reply(self.rid, step, "finished")
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()

        worker = threading.Thread(target=complete)
        worker.start()
        self.assertTrue(ready.wait(5))
        original_turn = repository.turn
        reads = 0

        def read_turn(rid):
            """旧实现读取 Turn 后触发另一连接提交；新实现的读在事务内，另一连接必须等待。"""
            nonlocal reads
            result = original_turn(rid)
            reads += 1
            if reads == 2:
                finish.set()
                if not self.runtime.store.db.in_transaction:
                    self.assertTrue(done.wait(5))
            return result

        try:
            with patch.object(repository, "turn", side_effect=read_turn):
                self.workspace.control.gate(self.rid)
        finally:
            finish.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        messages = self.runtime.store.db.execute(
            "SELECT content FROM workspace_messages WHERE run_id=? AND role='assistant'", (self.rid,)
        ).fetchall()
        status = repository.turn(self.rid)["status"]
        self.assertIn((status, len(messages)), {("PAUSED", 0), ("COMPLETED", 1)})

    def test_core_revision_never_moves_back_after_recovery(self):
        """Core 恢复会递增自己的栅栏；新控制命令不能用独立命令序号覆盖它。"""
        for _ in range(3):
            self.workspace.repository.interrupt(self.rid, "known safe interruption")
        before = self.runtime.store.get_run(self.rid)["control_revision"]
        self.workspace.control.command(self.rid, "compact")
        self.assertGreater(self.runtime.store.get_run(self.rid)["control_revision"], before)

    def test_missing_goal_progress_is_not_silently_recreated(self):
        """当前格式保证创建原子性；缺失进度是损坏，读取不得冒充旧库升级并伪造 READY。"""
        self.runtime.store.db.execute("DELETE FROM goal_work_state WHERE goal_id=?", (self.goal["goal_id"],))
        with self.assertRaisesRegex(RuntimeError, "work state missing"):
            self.workspace.personal.work_state(self.goal["goal_id"])
        self.assertEqual(self.runtime.store.db.execute("SELECT count(*) FROM goal_work_state").fetchone()[0], 0)

    def test_pause_resume_preserves_pending_question(self):
        """暂停/恢复待答轮次只改变调度开关；问题身份和 Goal 等待内容不得丢失。"""
        step = self.workspace.repository.begin_step(self.rid)["step"]
        self.workspace.repository.finish_reply(self.rid, step, "使用哪个目录？", question_id="question-1")
        self.workspace.control.command(self.rid, "pause")
        self.workspace.control.command(self.rid, "resume")
        turn = self.workspace.repository.turn(self.rid)
        self.assertEqual((turn["status"], turn["question_id"]), ("WAITING_USER", "question-1"))
        work = self.workspace.personal.work_state(self.goal["goal_id"])
        self.assertEqual((work["current_state"], work["waiting_for"]), ("WAITING", "使用哪个目录？"))

    def test_stale_model_preflight_cannot_commit_unvalidated_combination(self):
        """模型目录检查期间有新控制，旧 revision 的结果不得覆盖更新后的设置。"""
        revision = self.workspace.control.view(self.rid)["revision"]
        self.workspace.control.command(self.rid, "switch_model", "new-model")
        before = self.facts()
        with self.assertRaisesRegex(ValueError, "control changed during validation"):
            self.workspace.control.command(self.rid, "switch_thinking", "high", expected_revision=revision)
        self.assertEqual(self.facts(), before)

    def test_real_process_exit_before_and_after_control_commit(self):
        """真正 os._exit：提交前命令全项回滚，提交后 Turn/Goal 无需 Web 补调用。"""
        code = '''
import os, sys
from pathlib import Path
from myth.runtime import MythRuntime
from myth.workspace import Workspace
runtime = MythRuntime(Path(sys.argv[1]))
workspace = Workspace(runtime)
if sys.argv[3] == "before":
    original = runtime.store._event
    def crash(db, rid, kind, payload):
        original(db, rid, kind, payload)
        if kind == "ControlCommandCommitted":
            os._exit(73)
    runtime.store._event = crash
workspace.control.command(sys.argv[2], "pause")
os._exit(74)
'''
        before = self.facts()
        for stage, expected_exit in (("before", 73), ("after", 74)):
            result = subprocess.run([sys.executable, "-c", code, str(self.root), self.rid, stage],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, expected_exit, result.stderr)
            if stage == "before":
                self.assertEqual(self.facts(), before)
            else:
                self.assertEqual(self.workspace.repository.turn(self.rid)["status"], "PAUSED")
                self.assertEqual(self.workspace.personal.work_state(self.goal["goal_id"])["current_state"], "PAUSED")


if __name__ == "__main__":
    unittest.main()
