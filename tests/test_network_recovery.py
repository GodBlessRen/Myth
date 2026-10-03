"""断网恢复的故障注入回归。
固定时钟覆盖两小时离线、真实进程退出与 loopback HTTP 丢响应；不访问真实账户或证明远端模型质量。"""

import errno
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib import error

from myth.durable_executor import DurableExecutor
from myth.agent_runtime import AgentRuntime
from myth.goal_scheduler import GoalScheduler
from myth.models import ModelMessage, ModelRequest, ProviderUnavailable, STEP_DECISION_SCHEMA
from myth.network_recovery import reconnect_delay, is_pre_dispatch_disconnect
from myth.providers.ollama import OllamaProvider
from myth.providers.openai import OpenAIResponsesProvider
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision
from test_agent_runtime import LoopProvider


# 固定错误类型和时序；这些替身只证明保守派发分类，不模拟供应商的远端幂等性。
class NetworkRuleTests(unittest.TestCase):
    # 长期离线指数先封顶，禁止无穷增长；用户指定的每一档必须保留。
    def test_delay_sequence_and_long_outage_cap(self):
        self.assertEqual([reconnect_delay(i) for i in range(1, 10)], [1, 2, 4, 8, 16, 32, 60, 60, 60])
        self.assertEqual(reconnect_delay(10**9), 60)
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                reconnect_delay(value)

    # 重置/超时可能在提交后发生；不能因为网络错误就推定模型没有收到。
    def test_only_proven_pre_dispatch_failures_are_retryable(self):
        for reason in (socket.gaierror(), ConnectionRefusedError(), OSError(errno.ENETUNREACH, "offline")):
            self.assertTrue(is_pre_dispatch_disconnect(reason))
        for reason in (TimeoutError(), ConnectionResetError(), OSError(errno.ECONNABORTED, "aborted"), "offline"):
            self.assertFalse(is_pre_dispatch_disconnect(reason))

    # 两种 adapter 均只派发一次，把明确未发送的失败返回 Runtime，而不内循环重复 POST。
    def test_openai_and_ollama_return_zero_dispatch_evidence(self):
        request = ModelRequest("test", (ModelMessage("user", "fixture"),), STEP_DECISION_SCHEMA, 64)
        for provider, target in (
            (OllamaProvider(), "myth.providers.ollama.open_credential_request"),
            (OpenAIResponsesProvider(provider_id="openai", token_supplier=lambda: "synthetic"), "myth.providers.openai.open_credential_request"),
        ):
            with patch(target, side_effect=error.URLError(socket.gaierror())) as send:
                with self.assertRaises(ProviderUnavailable) as caught:
                    provider.invoke(request)
                self.assertEqual(send.call_count, 1)
                self.assertEqual(caught.exception.usage, {"model_calls": 0, "input_tokens": 0, "output_tokens": 0})

    # HTTP 已建立后，即使读取产生同名 DNS 异常也不能升级成“未派发”。
    def test_response_read_failure_is_not_safe_to_replay(self):
        request = ModelRequest("test", (ModelMessage("user", "fixture"),), STEP_DECISION_SCHEMA, 64)
        response = io.BytesIO()
        response.read = lambda size=-1: (_ for _ in ()).throw(error.URLError(socket.gaierror()))
        with patch("myth.providers.ollama.open_credential_request", return_value=response):
            with self.assertRaises(RuntimeError) as caught:
                OllamaProvider().invoke(request)
        self.assertNotIsInstance(caught.exception, ProviderUnavailable)


# 每用例独立 SQLite/Run；测试结束先等待所有 worker 线程，不能把缓存状态当持久恢复。
class NetworkRecoveryTests(unittest.TestCase):
    # 固定会话和模型，创建独立仓储；不读取用户已有 Runtime 或账号。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "test"})
        self.sid = self.repo.create_session()["id"]
        self.rid = self.repo.create_turn(self.sid, "Explain durable recovery", "network-fixture")["run_id"]

    # 关闭连接后清目录，子进程/线程均由用例自己的 finally 收束。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 首次扫描出错前也可计算下一次唤醒；初始化旧目录的定时表，不让重连循环提前退出。
    def test_poll_delay_initializes_schedule_schema(self):
        executor = DurableExecutor(self.root)
        self.assertEqual(executor._next_poll_delay(), executor.poll_seconds)

    # Exact CLI 没有后台自动发现，但显式再次驱动复用原 Run/step，并保留真实工具验收。
    def test_exact_agent_resumes_same_step_after_pre_dispatch_disconnect(self):
        source = self.root / "exact.txt"
        source.write_text("foo", encoding="utf-8")
        provider = LoopProvider()
        agent = AgentRuntime(self.runtime)
        rid = agent.create_run(goal="replace foo with bar", provider=provider, model="test",
            allowed_files=(source,), max_steps=4, max_output_tokens=100,
            acceptance=[{"path": str(source), "old_text": "foo", "new_text": "bar", "expected_count": 1}])
        with patch.object(provider, "invoke", side_effect=ProviderUnavailable()):
            interrupted = agent.run(rid, provider)
        self.assertEqual(interrupted["agent"]["status"], "INTERRUPTED")
        self.assertEqual(interrupted["agent"]["current_step"], 1)
        completed = agent.run(rid, provider)
        self.assertEqual(completed["agent"]["status"], "SUCCEEDED")
        self.assertEqual(len(completed["tool_actions"]), 1)
        self.assertEqual(len(completed["model"]["model_invocations"]), 3)
        self.assertEqual(source.read_text(encoding="utf-8"), "foo")

    # 重新打开连接检查 Run 真相；worker 心跳和检查不能推进原 checkpoint。
    def test_two_hour_outage_persists_across_worker_restart_without_tickets(self):
        provider = ChatProvider()
        provider.check = lambda: type("Offline", (), {"ready": False})()
        clock = [time.time()]
        cursor_before = self.repo.execution_cursor(self.rid)
        snapshot_before = self.repo.turn(self.rid)["snapshot"]
        executor = DurableExecutor(self.root, provider_factory=lambda settings: provider)
        with patch("time.time", side_effect=lambda: clock[0]):
            self.assertTrue(executor.claim())
            try:
                # 固定时钟推进 7200 秒，实际覆盖超过一百次持久检查，不等待墙钟两小时。
                deadline = clock[0] + 7200
                observed = []
                while clock[0] <= deadline:
                    executor.tick()
                    self.assertTrue(executor.wait_for_idle(3))
                    retry = self.repo.network_retry(self.rid)
                    observed.append(retry["delay_seconds"])
                    self.assertEqual(executor.dispatchable_runs(), [])
                    clock[0] = retry["retry_at"]
                self.assertEqual(observed[:8], [1, 2, 4, 8, 16, 32, 60, 60])
                self.assertGreater(len(observed), 100)
                self.assertEqual(self.repo.execution_cursor(self.rid)["updated_at"], cursor_before["updated_at"])
                self.assertEqual(self.repo.decisions.status(self.rid)["model_invocations"], [])
                persisted = self.repo.network_retry(self.rid)
            finally:
                executor.release()
            # 新 worker 不把次数归零；到期后恢复原 Run，首次实际推理只消费一个模型机会。
            provider.check = ChatProvider().check
            restarted = DurableExecutor(self.root, provider_factory=lambda settings: provider)
            self.assertTrue(restarted.claim())
            try:
                clock[0] = persisted["retry_at"] - 0.1
                self.assertEqual(restarted.tick(), 0)
                clock[0] = persisted["retry_at"]
                self.assertEqual(restarted.tick(), 1)
                self.assertTrue(restarted.wait_for_idle(3))
                self.assertEqual(self.repo.turn(self.rid)["status"], "COMPLETED")
                self.assertIsNone(self.repo.network_retry(self.rid))
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(self.runtime.store.db.execute("SELECT count(*) FROM workspace_turns").fetchone()[0], 1)
                self.assertEqual(self.repo.turn(self.rid)["snapshot"], snapshot_before)
            finally:
                restarted.release()

    # 推理检查 ready 但 POST 遇 DNS 失败时，退避仍继续增长；已有工具产物不重做、不消费更多步骤。
    def test_disconnect_between_steps_preserves_tool_and_backoff(self):
        provider = ChatProvider([decision("tool_call", "artifact.write", {"path": "done.txt", "content": "once"}), decision()])
        invoke = provider.invoke
        offline = [False]
        # 第一个模型决定正常，随后断连；网络恢复后才能取得最终回答。
        def call(request):
            if offline[0] or len(provider.calls) == 1:
                raise ProviderUnavailable()
            return invoke(request)
        provider.invoke = call
        now = [time.time()]
        with patch("time.time", side_effect=lambda: now[0]):
            self.workspace.run(self.rid, provider)
            self.assertEqual(self.repo.turn(self.rid)["current_step"], 2)
            operations = self.repo.operations(self.rid)
            self.assertEqual(len(operations), 1)
            with self.runtime.store.tx() as db:
                db.execute("UPDATE workspace_execution_cursors SET updated_at='2020-01-01 00:00:00' WHERE run_id=?", (self.rid,))
            # 一秒到期后网络仍不可用，下一档必须为两秒。
            now[0] = self.repo.network_retry(self.rid)["retry_at"]
            self.workspace.run(self.rid, provider)
            self.assertEqual(self.repo.network_retry(self.rid)["delay_seconds"], 2)
            self.assertEqual(self.repo.operations(self.rid), operations)
            self.assertEqual(self.repo.turn(self.rid)["current_step"], 2)
            self.assertEqual(self.repo.execution_cursor(self.rid)["updated_at"], "2020-01-01 00:00:00")
            now[0] = self.repo.network_retry(self.rid)["retry_at"]
            provider.invoke = invoke
            self.workspace.run(self.rid, provider)
            self.assertEqual(self.repo.turn(self.rid)["status"], "COMPLETED")
            self.assertIsNone(self.repo.network_retry(self.rid))
            calls = self.repo.decisions.status(self.rid)["model_invocations"]
            self.assertEqual([c["usage"]["model_calls"] for c in calls], [1, 0, 0, 1])
            self.assertEqual(self.repo.operations(self.rid), operations)
            budgets = {item["meter"]: item for item in self.repo.turn(self.rid)["budgets"]}
            self.assertEqual(budgets["model_calls"]["settled"], 2)

    # 到期前重复驱动只返回原现场，不能创建第二次模型机会或把截止时间提前。
    def test_early_drive_and_duplicate_deferral_do_not_bypass_deadline(self):
        now = time.time()
        self.repo.defer_network(self.rid, now=now)
        original = self.repo.network_retry(self.rid)
        self.repo.defer_network(self.rid, now=now + 0.2)
        provider = ChatProvider()
        self.workspace.run(self.rid, provider)
        self.assertEqual(self.repo.network_retry(self.rid)["retry_at"], original["retry_at"])
        self.assertEqual(len(provider.calls), 0)

    # 暂停与停止在断连状态仍能生效，worker 不等待网络才能执行本地控制。
    def test_pause_and_stop_while_offline_are_effective(self):
        self.repo.defer_network(self.rid)
        self.workspace.control.command(self.rid, "pause")
        executor = DurableExecutor(self.root, provider_factory=lambda settings: ChatProvider())
        self.assertTrue(executor.claim())
        try:
            with patch("time.time", return_value=time.time() + 2):
                executor.tick()
            self.assertEqual(self.repo.turn(self.rid)["status"], "PAUSED")
            self.workspace.control.command(self.rid, "stop")
            self.workspace.control.gate(self.rid)
            self.assertEqual(self.repo.turn(self.rid)["status"], "CANCELLED")
            self.assertIsNone(self.repo.network_retry(self.rid))
        finally:
            executor.wait_for_idle(3)
            executor.release()

    # 崩溃真实发生在零派发收据落盘后、数据库结算前；新进程只核对收据，随后复用同一 Run/step。
    def test_process_crash_after_zero_dispatch_receipt_recovers(self):
        code = """import os,sys
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.models import ProviderUnavailable
class Offline:
 provider_id='ollama'
 def invoke(self, request): raise ProviderUnavailable()
r=MythRuntime(sys.argv[1]);w=Workspace(r)
w.repository.decisions._settle_failed=lambda *args: os._exit(73)
w.run(sys.argv[2], Offline())
"""
        child = subprocess.run([sys.executable, "-c", code, str(self.root), self.rid], timeout=10, capture_output=True)
        self.assertEqual(child.returncode, 73, child.stderr.decode(errors="replace"))
        self.repo.sweep_expired_driver(self.rid)
        self.assertEqual(self.repo.turn(self.rid)["status"], "INTERRUPTED")
        provider = ChatProvider()
        self.workspace.run(self.rid, provider)
        self.assertEqual(self.repo.turn(self.rid)["status"], "COMPLETED")
        self.assertEqual(self.repo.turn(self.rid)["current_step"], 1)
        self.assertEqual([item["usage"]["model_calls"] for item in self.repo.decisions.status(self.rid)["model_invocations"]], [0, 1])

    # UNKNOWN 的迟到零派发证据从 unknown_held 释放，重复核对不得再次扣减预算。
    def test_late_failure_receipt_settlement_is_idempotent(self):
        provider = ChatProvider()
        provider.invoke = lambda request: (_ for _ in ()).throw(ProviderUnavailable())
        runtime = self.repo.decisions
        with patch.object(runtime, "_settle_failed", side_effect=RuntimeError("synthetic crash window")):
            self.workspace.run(self.rid, provider)
        invocation = runtime.status(self.rid)["model_invocations"][0]
        runtime._mark_unknown(invocation["model_attempt_id"], "unsettled receipt")
        runtime.recover(self.rid)
        before = self.repo.turn(self.rid)["budgets"]
        runtime.recover(self.rid)
        self.assertEqual(self.repo.turn(self.rid)["budgets"], before)
        budgets = {item["meter"]: item for item in before}
        for meter in ("model_calls", "input_tokens", "output_tokens"):
            self.assertEqual(budgets[meter]["reserved"], 0)
            self.assertEqual(budgets[meter]["unknown_held"], 0)

    # 断连队列不挤占 SQL LIMIT；最早 32 个等待中的 Run 后面的就绪工作仍能被发现。
    def test_waiting_runs_do_not_starve_ready_run(self):
        self.repo.defer_network(self.rid, now=time.time() + 3600)
        for i in range(36):
            sid = self.repo.create_session()["id"]
            rid = self.repo.create_turn(sid, "waiting", f"queue-{i}")["run_id"]
            self.repo.defer_network(rid, now=time.time() + 3600)
        executor = DurableExecutor(self.root)
        sid = self.repo.create_session()["id"]
        ready = self.repo.create_turn(sid, "ready", "queue-ready")["run_id"]
        self.assertEqual(executor.dispatchable_runs(4), [ready])

    # 已固定的本地工具决定不需要再次连模型；断网仍可完成其收据，后续模型请求再进入等待。
    def test_already_decided_local_tool_continues_when_provider_is_offline(self):
        provider = ChatProvider([decision("tool_call", "artifact.write", {"path": "local.txt", "content": "saved"})])
        self.repo.begin_step(self.rid)
        did, proposal = self.workspace.execution.decide(self.repo.turn(self.rid), 1, provider)
        self.repo.bind(self.rid, 1, did, proposal)
        provider.check = lambda: (_ for _ in ()).throw(AssertionError("local decision must not probe"))
        provider.invoke = lambda request: (_ for _ in ()).throw(ProviderUnavailable())
        executor = DurableExecutor(self.root, provider_factory=lambda settings: provider)
        self.assertTrue(executor.claim())
        try:
            executor.tick()
            self.assertTrue(executor.wait_for_idle(3))
            turn = self.repo.turn(self.rid)
            self.assertEqual(turn["activities"][0]["state"], "DONE")
            self.assertEqual(len(self.repo.operations(self.rid)), 1)
            self.assertEqual(turn["current_step"], 2)
            self.assertEqual(turn["status"], "INTERRUPTED")
        finally:
            executor.release()

    # 旧定时表没有失败次数列时升级保留已保存的截止时间，不重新准入或清空旧计划。
    def test_legacy_schedule_retry_migration_preserves_deadline(self):
        scheduler = GoalScheduler(self.workspace)
        goal = self.workspace.personal.create_goal("Migration")
        sid = self.repo.create_session()["id"]
        entry = scheduler.create(goal["goal_id"], {"session_id": sid, "prompt": "Resume", "due_at": "2026-01-01T00:00:00Z"})
        scheduler.defer(entry["schedule_id"], "offline")
        before = scheduler.get(entry["schedule_id"])
        with self.runtime.store.tx() as db:
            db.execute("ALTER TABLE goal_schedules DROP COLUMN retry_failures")
        current = GoalScheduler(self.workspace).get(entry["schedule_id"])
        self.assertEqual(current["retry_at"], before["retry_at"])
        self.assertEqual(current["retry_failures"], 0)
        self.assertEqual(current["wakeups"], [])

    # 定时机会持久保存相同退避，旧 schema 可以加列；恢复准入后重置连续失败计数。
    def test_goal_schedule_uses_same_backoff_and_resets_after_admission(self):
        scheduler = GoalScheduler(self.workspace)
        goal = self.workspace.personal.create_goal("Scheduled reconnect")
        sid = self.repo.create_session()["id"]
        entry = scheduler.create(goal["goal_id"], {"session_id": sid, "prompt": "Resume", "due_at": "2026-01-01T00:00:00Z"})
        now = time.time()
        for expected in (1, 2, 4, 8, 16, 32, 60, 60):
            scheduler.defer(entry["schedule_id"], "not connected", now)
            state = scheduler.get(entry["schedule_id"])
            self.assertEqual(state["retry_at"] - now, expected)
            now = state["retry_at"]
        rid = scheduler.admit(entry["schedule_id"], now)
        self.assertIsNotNone(rid)
        self.assertEqual(scheduler.get(entry["schedule_id"])["retry_failures"], 0)

    # 常驻循环的真实第一档约一秒；线程交还后唤醒扫描，不能仍按旧两秒轮询截断节奏。
    def test_worker_reconnects_after_one_second_and_can_stop(self):
        provider = ChatProvider()
        checks = []
        check = provider.check
        # 第一检查断连，下一检查恢复；记录实际 monotonic 时间用于验证调度而非模型质量。
        def readiness():
            checks.append(time.monotonic())
            return check() if len(checks) > 1 else type("Offline", (), {"ready": False})()
        provider.check = readiness
        executor = DurableExecutor(self.root, provider_factory=lambda settings: provider)
        worker = threading.Thread(target=executor.serve_forever)
        worker.start()
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and self.repo.turn(self.rid)["status"] != "COMPLETED":
                time.sleep(0.02)
            self.assertEqual(self.repo.turn(self.rid)["status"], "COMPLETED")
            self.assertGreaterEqual(checks[1] - checks[0], 0.95)
            self.assertLess(checks[1] - checks[0], 1.9)
        finally:
            executor.stop()
            worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertTrue(executor.wait_for_idle(3))

    # 真正的 POST 已被服务接收但响应读超时：保留 UNKNOWN/预算占用，后台重连不能重复发送。
    def test_accepted_http_request_timeout_is_never_automatically_replayed(self):
        received = []
        # 固定 loopback 服务模拟远端已接收；与真实账户无关，故障只发生在响应阶段。
        class Handler(BaseHTTPRequestHandler):
            # POST 先记录已接收正文，再延迟结束；客户端无法凭超时知道处理结果。
            def do_POST(self):
                received.append(self.rfile.read(int(self.headers["Content-Length"])))
                time.sleep(0.15)
                self.send_response(200)
                self.end_headers()
            # 禁止测试服务器打印请求正文或噪声日志。
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            provider = OllamaProvider(f"http://127.0.0.1:{server.server_port}", timeout=0.05)
            self.workspace.run(self.rid, provider)
            self.assertEqual(self.repo.turn(self.rid)["status"], "UNKNOWN")
            self.assertIsNone(self.repo.network_retry(self.rid))
            executor = DurableExecutor(self.root, provider_factory=lambda settings: provider)
            self.assertTrue(executor.claim())
            try:
                self.assertEqual(executor.tick(), 0)
                self.assertEqual(len(received), 1)
            finally:
                executor.release()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__ == "__main__":
    unittest.main()
