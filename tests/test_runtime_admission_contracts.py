"""真实 SQLite 的 Turn/Step/Ticket 身份与事务准备故障回归。"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.domain import IdentityConflict, InvalidTransition
from myth.models import parse_step_decision
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.goal_scheduler import GoalScheduler
from datetime import datetime, timezone
import time
from test_workspace import ChatProvider, decision


class RuntimeAdmissionContracts(unittest.TestCase):
    """固定真实准入/收据身份窗口；临时 SQLite 不代表远端服务已验证。"""
    def setUp(self):
        """每例建立独占状态和一个活跃 Turn，避免测试之间共享事实。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "test"})
        self.sid = self.repo.create_session()["id"]
        self.rid = self.repo.create_turn(self.sid, "你好", "entry")["run_id"]

    def tearDown(self):
        """先关闭连接，再释放临时目录。"""
        self.runtime.close()
        self.tmp.cleanup()

    def admitted_decision(self):
        """经过真实 Step/模型决定/绑定链生成合法 Ticket 的前置身份。"""
        step = self.repo.begin_step(self.rid)["step"]
        did, parsed = self.workspace.execution.decide(self.repo.turn(self.rid), step, ChatProvider())
        self.repo.bind(self.rid, step, did, parsed)
        return step, did, parsed

    def test_bind_requires_admitted_step(self):
        """没有已准入 Step 时拒绝绑定，并保持事件事实不变。"""
        before = len(self.repo.events(self.rid))
        with self.assertRaises(InvalidTransition):
            self.repo.bind(self.rid, 1, "missing", parse_step_decision(decision()))
        self.assertEqual(len(self.repo.events(self.rid)), before)

    def test_bind_replay_is_idempotent_and_conflicting_payload_rejected(self):
        """同决定重入不写第二次事件，异内容拒绝，已完成 Step 不被重开。"""
        step, did, parsed = self.admitted_decision()
        before = len(self.repo.events(self.rid))
        self.repo.bind(self.rid, step, did, parsed)
        self.assertEqual(len(self.repo.events(self.rid)), before)
        with self.assertRaises(IdentityConflict):
            self.repo.bind(self.rid, step, did, parse_step_decision(decision(claim="different")))
        self.repo.finish_tool(self.rid, step, {"done": True})
        self.repo.bind(self.rid, step, did, parsed)
        self.assertEqual(self.repo.turn(self.rid)["activities"][0]["state"], "DONE")

    def test_existing_ticket_rejects_changed_owner_capability_and_intent(self):
        """同决定不能借原 Ticket 换 Run、能力或意图；原意图重入复用身份。"""
        _, did, _ = self.admitted_decision()
        intent = {"write_bytes": 0, "result": {"content": "fixed"}}
        original = self.repo.start_operation(self.rid, did, "fixture.read", intent)
        for rid, cap, body in (("other", "fixture.read", intent), (self.rid, "fixture.other", intent), (self.rid, "fixture.read", {**intent, "write_bytes": 1})):
            with self.subTest(rid=rid, cap=cap, body=body), self.assertRaises(IdentityConflict):
                self.repo.start_operation(rid, did, cap, body)
        self.assertEqual(self.repo.start_operation(self.rid, did, "fixture.read", intent)["ticket_id"], original["ticket_id"])

    def test_resolved_operation_rejects_different_receipt(self):
        """已结算收据不可被第二份结果覆盖。"""
        _, did, _ = self.admitted_decision()
        self.repo.start_operation(self.rid, did, "fixture.read", {"write_bytes": 0, "requires_receipt": True})
        self.repo.settle_operation(did, {"content": "first"})
        with self.assertRaises(IdentityConflict):
            self.repo.settle_operation(did, {"content": "different"})

    def test_turn_knowledge_and_environment_reads_precede_write_transaction(self):
        """向量/对象读取与文件扫描即使很慢，也不得占据 SQLite 写锁。"""
        sid = self.repo.create_session()["id"]
        document = self.repo.knowledge.import_document({"title": "attachment", "content": "fixture"})
        original_search = self.repo.knowledge.search_report
        original_get = self.runtime.objects.get
        original_freeze = self.repo.sota_route.freeze_environment
        observed = []

        def outside(name, method):
            """记录实际 I/O 并断言不持写事务，保留原方法行为。"""
            def call(*args, **kwargs):
                """把事务边界断言插到真实调用前。"""
                observed.append(name)
                self.assertFalse(self.runtime.store.db.in_transaction, name)
                return method(*args, **kwargs)
            return call

        with patch.object(self.repo.knowledge, "search_report", side_effect=outside("search", original_search)), patch.object(
            self.runtime.objects, "get", side_effect=outside("object", original_get)
        ), patch.object(self.repo.sota_route, "freeze_environment", side_effect=outside("environment", original_freeze)):
            self.repo.create_turn(sid, "fixture", "outside", [document["id"]])
        self.assertEqual(set(observed), {"search", "object", "environment"})

    def test_scheduler_memory_reads_precede_write_transaction(self):
        """调度 Memory 预取遵守相同准入合同，occurrence 仍与 Run 原子提交。"""
        scheduler = GoalScheduler(self.workspace)
        goal = self.workspace.personal.create_goal("scheduled")
        sid = self.repo.create_session()["id"]
        now = time.time()
        schedule = scheduler.create(goal["goal_id"], {"session_id": sid, "prompt": "continue", "due_at": datetime.fromtimestamp(now, timezone.utc).isoformat()})
        original = self.workspace.memory.search_view_report

        def memory(*args, **kwargs):
            """真实召回前核对写锁，不能用替身返回值绕过读取。"""
            self.assertFalse(self.runtime.store.db.in_transaction)
            return original(*args, **kwargs)

        with patch.object(self.workspace.memory, "search_view_report", side_effect=memory):
            rid = scheduler.admit(schedule["schedule_id"], now + 1)
        self.assertEqual(scheduler.get(schedule["schedule_id"])["wakeups"][0]["run_id"], rid)

    def test_stale_preparation_rejects_commit_without_partial_run(self):
        """准备后任何 SQL 事实变更使整份快照失效；不留预算、消息或 Run。"""
        for mutation in ("session", "settings", "memory", "knowledge"):
            with self.subTest(mutation=mutation):
                sid = self.repo.create_session()["id"]
                request = "cas-" + mutation
                prepared = self.repo.prepare_turn(sid, "versioned context", request)
                if mutation == "session":
                    self.repo.update_session(sid, {"title": "changed"})
                elif mutation == "settings":
                    self.repo.save_settings({"model": "changed"})
                elif mutation == "memory":
                    self.workspace.memory.remember(kind="semantic", text="new fact", source_ref="fixture:new")
                else:
                    self.repo.knowledge.import_document({"title": "new source", "content": "versioned context"})
                before = self.runtime.store.db.execute("SELECT count(*) FROM runs").fetchone()[0]
                with self.assertRaises(IdentityConflict):
                    self.repo.create_turn(sid, "versioned context", request, _prepared=prepared)
                self.assertEqual(self.runtime.store.db.execute("SELECT count(*) FROM runs").fetchone()[0], before)
                self.assertEqual(self.repo.session(sid)["messages"], [])

    def test_memory_change_during_recall_cannot_be_admitted(self):
        """外部召回返回后水位变动，不能把旧 Memory 快照绑定到新准入版本。"""
        sid = self.repo.create_session()["id"]
        original = self.workspace.memory.search_view_report

        def recall(*args, **kwargs):
            """在真实召回后提交并发 Memory 变化，制造过期准备窗口。"""
            result = original(*args, **kwargs)
            self.workspace.memory.remember(kind="semantic", text="changed during recall", source_ref="fixture:concurrent")
            return result

        with patch.object(self.workspace.memory, "search_view_report", side_effect=recall):
            with self.assertRaises(IdentityConflict):
                self.repo.create_turn(sid, "context", "racing-memory")
        self.assertEqual(self.repo.session(sid)["turns"], [])

    def test_same_entry_retry_reuses_run_after_memory_changes(self):
        """稳定入口先去重；后来的 Memory 不得把一次用户意图重放成另一个 Run。"""
        self.workspace.memory.remember(kind="semantic", text="later fact", source_ref="fixture:later")
        again = self.repo.create_turn(self.sid, "你好", "entry")
        self.assertEqual(again["run_id"], self.rid)
