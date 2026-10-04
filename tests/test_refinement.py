"""沉淀期回归：schema 初始化、步骤消费和评测资格必须保持真实、原子、可重试。

使用真实 SQLite、独立临时工作区和固定评测；不发送供应商请求。
重点覆盖原版已复现的零行 UPDATE、完成结果覆写和 DDL 部分提交窗口。
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from myth.domain import IdentityConflict, InvalidTransition
from myth.evaluation_runner import FoundationEvalRunner
from myth.runtime import MythRuntime
from myth.store import RuntimeStore, SchemaMismatch, SCHEMA_VERSION
from myth.workspace import Workspace


class SchemaInitializationTests(unittest.TestCase):
    """数据库格式只有一个明确入口；拒绝旧库不修改其内容，DDL 错误整体回滚。"""

    def test_failed_schema_creation_rolls_back_every_statement(self):
        """第二条 DDL 出错时，第一张表也必须不存在，连接随后仍能正常提交。"""
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            with self.assertRaises(sqlite3.OperationalError):
                runtime.store.ensure_schema("CREATE TABLE probe_partial(x); INVALID SQL;")
            self.assertFalse(runtime.store.db.in_transaction)
            self.assertIsNone(runtime.store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='probe_partial'"
            ).fetchone())
            runtime.store.ensure_schema("CREATE TABLE probe_complete(x);")
            self.assertIsNotNone(runtime.store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='probe_complete'"
            ).fetchone())

    def test_schema_initialization_never_commits_callers_business_transaction(self):
        """业务写事务中装配 schema 必须拒绝；不能像 executescript 那样偷偷提交外层。"""
        with tempfile.TemporaryDirectory() as tmp, MythRuntime(tmp) as runtime:
            with self.assertRaises(RuntimeError):
                with runtime.store.tx() as db:
                    db.execute("CREATE TABLE business_pending(x)")
                    runtime.store.ensure_schema("CREATE TABLE accidental(x);")
            for name in ("business_pending", "accidental"):
                self.assertIsNone(runtime.store.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name=?", (name,)
                ).fetchone())

    def test_unsupported_database_is_preserved_without_automatic_migration(self):
        """旧实验格式与未来格式均明确拒绝；原表、字段和数据保留，不能自动清库。"""
        for version in (0, SCHEMA_VERSION + 1):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "existing.db"
                db = sqlite3.connect(path)
                db.execute("CREATE TABLE preserved(value)")
                db.execute("INSERT INTO preserved VALUES ('original')")
                db.execute(f"PRAGMA user_version={version}")
                db.commit()
                db.close()
                before = path.read_bytes()
                with self.assertRaisesRegex(SchemaMismatch, "new --root"):
                    RuntimeStore(path)
                self.assertEqual(path.read_bytes(), before)

    def test_parallel_first_open_and_current_reopen_use_one_schema_identity(self):
        """两个首启连接竞争同一空库后只能留下完整当前格式；重开不创建另一份状态。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parallel.db"

            def open_store(_):
                """每个线程拥有并关闭自己的连接，只观察持久版本与 Core 表。"""
                store = RuntimeStore(path)
                try:
                    return store.db.execute("PRAGMA user_version").fetchone()[0]
                finally:
                    store.close()

            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(list(pool.map(open_store, range(2))), [SCHEMA_VERSION] * 2)
            self.assertEqual(open_store(None), SCHEMA_VERSION)


class StepConsumptionTests(unittest.TestCase):
    """步骤是先准入、再消费的持久身份；幂等回调不产生新的完成事实。"""

    def setUp(self):
        """建立真实 Conversation，但不调用模型，所有步骤由仓储明确准入。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(self.tmp.name)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "fixture"})
        self.sid = self.repo.create_session("step contract")["id"]
        self.rid = self.repo.create_turn(self.sid, "inspect the project", "fixture")["run_id"]

    def tearDown(self):
        """先关闭连接再删除本用例临时目录，避免 Windows 文件句柄影响其他用例。"""
        self.runtime.close()
        self.tmp.cleanup()

    def test_unadmitted_step_cannot_create_answer_observation_or_checkpoint(self):
        """原版第 999 步可完成零步骤 Turn；三种消费入口都必须原子拒绝。"""
        before = self.repo.turn(self.rid)
        events = self.repo.events(self.rid)
        messages = self.repo.session(self.sid)["messages"]
        for method, payload in (
            (self.repo.finish_reply, "false completion"),
            (self.repo.finish_tool, {"capability_id": "math.calculate", "value": 7}),
            (self.repo.finish_observation, {"error": "unadmitted"}),
        ):
            with self.subTest(method=method.__name__), self.assertRaises(InvalidTransition):
                method(self.rid, 999, payload)
            self.assertEqual(self.repo.turn(self.rid), before)
            self.assertEqual(self.repo.events(self.rid), events)
            self.assertEqual(self.repo.session(self.sid)["messages"], messages)

    def test_tool_retry_is_idempotent_and_cannot_regress_a_newer_cursor(self):
        """原结果重复到达时不新增事件；开始下一步后也不能把游标退回上一步。"""
        step = self.repo.begin_step(self.rid)["step"]
        result = {"capability_id": "math.calculate", "value": 7}
        self.repo.finish_tool(self.rid, step, result)
        self.repo.begin_step(self.rid)
        before = self.repo.turn(self.rid)
        events = self.repo.events(self.rid)
        self.repo.finish_tool(self.rid, step, result)
        self.assertEqual(self.repo.turn(self.rid), before)
        self.assertEqual(self.repo.events(self.rid), events)

    def test_completed_result_is_immutable_and_observation_retry_is_idempotent(self):
        """相同步骤只能有一个结果；不同回调拒绝，原 JSON、事件和游标保持不变。"""
        for method in (self.repo.finish_tool, self.repo.finish_observation):
            step = self.repo.begin_step(self.rid)["step"]
            method(self.rid, step, {"value": 1})
            before = self.repo.turn(self.rid)
            events = self.repo.events(self.rid)
            method(self.rid, step, {"value": 1})
            with self.assertRaises(IdentityConflict):
                method(self.rid, step, {"value": 2})
            self.assertEqual(self.repo.turn(self.rid), before)
            self.assertEqual(self.repo.events(self.rid), events)

    def test_stop_keeps_real_late_tool_evidence_without_reopening_run(self):
        """Stop 只停未来调度；已经准入步骤的晚到事实仍消费，Turn 保持 CANCELLED。"""
        step = self.repo.begin_step(self.rid)["step"]
        self.workspace.control.command(self.rid, "stop")
        result = {"capability_id": "math.calculate", "value": 7}
        self.repo.finish_tool(self.rid, step, result)
        turn = self.repo.turn(self.rid)
        self.assertEqual(turn["status"], "CANCELLED")
        self.assertEqual(turn["activities"][0]["result"], result)

    def test_missing_cursor_is_reported_instead_of_inferred(self):
        """当前格式的游标由准入创建；删除它模拟损坏，读取不得编造恢复进度。"""
        with self.runtime.store.tx() as db:
            db.execute("DELETE FROM workspace_execution_cursors WHERE run_id=?", (self.rid,))
        with self.assertRaisesRegex(RuntimeError, "cursor missing"):
            self.repo.execution_cursor(self.rid)

    def test_document_and_chunks_roll_back_together(self):
        """分片写入失败时知识仓储不能只留下文档行；事务外对象允许等待后续 GC。"""
        self.runtime.store.db.execute(
            "CREATE TEMP TRIGGER reject_chunks BEFORE INSERT ON workspace_chunks "
            "BEGIN SELECT RAISE(ABORT, 'injected chunk failure'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.knowledge.import_document({"title": "atomic", "content": "evidence"})
        self.assertEqual(self.repo.knowledge.documents(), [])
        self.assertEqual(self.runtime.store.db.execute("SELECT count(*) FROM workspace_chunks").fetchone()[0], 0)

    def test_acceptance_rechecks_subject_inside_commit_transaction(self):
        """模拟读取后到提交前回答被修订：两种验收入口都拒绝旧摘要，不保存过期 PASS。"""
        step = self.repo.begin_step(self.rid)["step"]
        self.repo.finish_reply(self.rid, step, "first answer")
        ledger = self.workspace.delivery
        original = self.runtime.store.tx
        for method in ("ensure_acceptance", "set_acceptance"):
            old_digest = ledger._subject(self.rid)[0]

            @contextmanager
            def changed_before_commit():
                """在真正事务入口修改回答，精确固定核对与写入之间的竞争窗口。"""
                with original() as db:
                    db.execute("UPDATE workspace_messages SET content=content || ' revised' "
                               "WHERE run_id=? AND role='assistant'", (self.rid,))
                    yield db

            kwargs = {"subject_digest": old_digest}
            if method == "set_acceptance":
                kwargs.update(state="PASSED", checker_id="fixture/reviewer")
            with patch.object(self.runtime.store, "tx", changed_before_commit):
                with self.assertRaises(ValueError):
                    getattr(ledger, method)(self.rid, **kwargs)
            self.assertIsNone(ledger.acceptance(self.rid))

    def _concurrent_delivery(self, operations):
        """两条独立连接同时到达写事务入口；强制重现事务外读旧 revision/字段的竞争窗口。"""
        barrier = threading.Barrier(2)
        root = Path(self.tmp.name)

        def worker(operation):
            """每线程独立装配仓储，只在目标操作 BEGIN 前等另一连接就绪。"""
            with MythRuntime(root) as runtime:
                ledger = Workspace(runtime).delivery
                original = runtime.store.tx

                @contextmanager
                def coordinated_tx():
                    """屏障位于 BEGIN IMMEDIATE 之前；业务读取应在随后获得写锁的事务里。"""
                    barrier.wait(timeout=5)
                    with original() as db:
                        yield db

                with patch.object(runtime.store, "tx", coordinated_tx):
                    return operation(ledger)

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, operations))

    def test_concurrent_plans_allocate_distinct_ordinals_and_revisions(self):
        """两个自动 revision 计划都成功，既不能撞 UNIQUE，也不能共用同一个修订号。"""
        self.workspace.delivery.ensure_root_work_item(self.repo.turn(self.rid))
        self._concurrent_delivery([
            lambda ledger: ledger.plan_work_items(self.rid, [{"title": "first plan"}]),
            lambda ledger: ledger.plan_work_items(self.rid, [{"title": "second plan"}]),
        ])
        items = self.workspace.delivery.work_items(self.rid)
        self.assertEqual([item["ordinal"] for item in items], [1, 2, 3])
        self.assertEqual([item["plan_revision"] for item in items], [1, 2, 3])

    def test_concurrent_partial_updates_preserve_both_callers_fields(self):
        """一方改状态、一方改备注；省略字段必须使用事务内最新值，不能互相抹掉。"""
        item = self.workspace.delivery.ensure_root_work_item(self.repo.turn(self.rid))
        identity = item["work_item_id"]
        self._concurrent_delivery([
            lambda ledger: ledger.update_work_item(identity, status="WAITING"),
            lambda ledger: ledger.update_work_item(identity, progress_note="needs review"),
        ])
        updated = self.workspace.delivery.work_items(self.rid)[0]
        self.assertEqual(updated["status"], "WAITING")
        self.assertEqual(updated["progress_note"], "needs review")


class EvaluationCoverageTests(unittest.TestCase):
    """诊断选题可以全部通过，但只有固定完整分母才有发布资格。"""

    def test_selected_success_is_partial_and_unknown_case_is_rejected(self):
        """原版筛选两题可显示 release_gate.passed=true；此处同时检查未知题号。"""
        runner = FoundationEvalRunner.from_path(Path(__file__).resolve().parents[1] / "evals/foundation-v4.json")
        result = runner.run(["intent-arithmetic-local", "intent-ambiguous-fallback"])
        self.assertEqual(result["report"]["pass_count"], 2)
        self.assertFalse(result["complete_suite"])
        self.assertFalse(result["release_gate"]["passed"])
        with self.assertRaisesRegex(ValueError, "unknown evaluation cases"):
            runner.run(["intent-arithmetic-local", "nonexistent-case"])
