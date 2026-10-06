"""Web Driver 启动故障回归：真实 SQLite、固定 Provider 和可控线程创建失败。

本机 active、持久 Driver Lease 与运行结果是三种不同事实。测试只注入线程边界，
不替换仓储恢复逻辑；成功重试必须继续原 Run，不伪造远端模型的可用性。
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from myth.adapters.workspace_store import SqliteWorkspaceRepository
from myth.demo import create_demo
from myth.runtime import MythRuntime
from myth.web import AgentWebService
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace
from test_workspace import ChatProvider


# 保存真实构造器，线程故障只在显式 patch 窗口生效，不污染测试框架或重试。
REAL_THREAD = threading.Thread


class InlineThread:
    """只用于确定性进入 worker 函数；不声称这一阶段验证了真实线程调度。"""

    def __init__(self, *, target, **kwargs):
        """保存固定待测入口；心跳线程由用例另行构造，不在此吞并。"""
        self.target = target

    def start(self):
        """同步执行入口，让线程内部异常能够明确暴露在测试调用点。"""
        self.target()


class WebWorkerLifecycleTests(unittest.TestCase):
    """每个用例拥有独立根目录；重试阶段使用真实线程并 join 后再清理文件。"""

    def setUp(self):
        """不启动 HTTP 服务器；本组隔离更内层的线程、租约与持久结果边界。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def exact(self):
        """创建真实 Exact 验收合同，暂不启动后台 Driver。"""
        service = AgentWebService(self.root)
        with MythRuntime(self.root) as runtime:
            rid, provider = create_demo(runtime)
        return service, rid, provider

    def conversation(self):
        """创建有固定请求键和设置的真实 Turn，尚未消费模型机会。"""
        service = ConversationWebService(self.root)
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            workspace.repository.save_settings({"provider": "ollama", "model": "test"})
            sid = workspace.repository.create_session()["id"]
            rid = workspace.repository.create_turn(sid, "Explain the evidence", "request-" + sid)["run_id"]
        return service, rid

    def turn(self, rid):
        """从新的连接读取结果和租约，不从本机 active 推断业务状态。"""
        with MythRuntime(self.root) as runtime:
            repository = Workspace(runtime).repository
            return repository.turn(rid), repository.driver_lease(rid)

    def finish(self, service, rid, provider, *, exact=False):
        """用真实线程重试同一 Run，并等待所有已创建线程退出后核对结果。"""
        threads = []

        def capture(*args, **kwargs):
            """记录真实线程句柄只供清理；不替换线程的 start/join 实现。"""
            thread = REAL_THREAD(*args, **kwargs)
            threads.append(thread)
            return thread

        method = "_provider" if exact else "provider"
        with patch("threading.Thread", side_effect=capture), patch.object(service, method, return_value=provider):
            if exact:
                service.advance(rid)
            else:
                service._spawn(rid)
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive(), "test worker failed to finish")
        if exact:
            self.assertFalse(service.status(rid)["driver_active"])
            self.assertEqual(service.status(rid)["agent"]["status"], "SUCCEEDED")
        else:
            turn, lease = self.turn(rid)
            self.assertEqual(turn["status"], "COMPLETED")
            self.assertIsNone(lease)
            self.assertNotIn(rid, service.active)

    def test_exact_constructor_and_start_failure_do_not_leave_active(self):
        """线程未启动就报错时没有外部效果，原 Run 可直接继续且不重复创建。"""
        service, rid, provider = self.exact()
        for boundary in ("constructor", "start"):
            with self.subTest(boundary=boundary):
                thread = Mock()
                thread.start.side_effect = RuntimeError("fixture thread start failure")
                with patch("threading.Thread", side_effect=RuntimeError("fixture construction failure") if boundary == "constructor" else None,
                           return_value=thread), patch.object(service, "_provider") as factory:
                    with self.assertRaises(RuntimeError):
                        service._spawn(rid, {"provider": "scripted"})
                factory.assert_not_called()
                self.assertNotIn(rid, service._active)
                status = service.status(rid)
                self.assertEqual(status["agent"]["status"], "RUNNING")
                self.assertEqual(status["model"]["model_invocations"], [])
        self.finish(service, rid, provider, exact=True)
        self.assertEqual(len(service.list_runs()), 1)

    def test_exact_duplicate_admission_does_not_clear_existing_active(self):
        """重复调用没有取得占位，不能清掉另一个已存在的本机 Driver 标记。"""
        service, rid, _ = self.exact()
        service._active.add(rid)
        with patch("threading.Thread") as constructor:
            with self.assertRaises(RuntimeError):
                service._spawn(rid, {"provider": "scripted"})
        constructor.assert_not_called()
        self.assertIn(rid, service._active)
        service._active.clear()

    def test_conversation_constructor_and_start_failure_release_own_lease(self):
        """取得租约后线程仍可能启动失败；释放自己的 owner，重试继续同一 Turn。"""
        service, rid = self.conversation()
        for boundary in ("constructor", "start"):
            with self.subTest(boundary=boundary):
                thread = Mock()
                thread.start.side_effect = RuntimeError("fixture thread start failure")
                with patch("threading.Thread", side_effect=RuntimeError("fixture construction failure") if boundary == "constructor" else None,
                           return_value=thread), patch.object(service, "provider") as factory:
                    with self.assertRaises(RuntimeError):
                        service._spawn(rid)
                factory.assert_not_called()
                self.assertNotIn(rid, service.active)
                turn, lease = self.turn(rid)
                self.assertIsNone(lease)
                self.assertEqual(turn["status"], "RUNNING")
                self.assertEqual(turn["current_step"], 0)
        provider = ChatProvider()
        self.finish(service, rid, provider)
        self.assertEqual(len(provider.calls), 1)

    def test_heartbeat_constructor_and_start_failure_interrupt_without_dispatch(self):
        """心跳未启动时不进入 Provider；持久状态可恢复，清理不 join 未启动的线程。"""
        for boundary in ("constructor", "start"):
            with self.subTest(boundary=boundary):
                service, rid = self.conversation()
                heartbeat = Mock()
                heartbeat.start.side_effect = RuntimeError("fixture heartbeat failure")

                def construct(*args, **kwargs):
                    """只让外层 Driver 同步进入；失败窗口精确落在心跳构造或 start。"""
                    if kwargs["name"].startswith("chat-"):
                        return InlineThread(**kwargs)
                    if boundary == "constructor":
                        raise RuntimeError("fixture heartbeat construction failure")
                    return heartbeat

                with patch("threading.Thread", side_effect=construct), patch.object(service, "provider") as factory:
                    service._spawn(rid)
                factory.assert_not_called()
                heartbeat.join.assert_not_called()
                self.assertNotIn(rid, service.active)
                turn, lease = self.turn(rid)
                self.assertIsNone(lease)
                self.assertEqual(turn["status"], "INTERRUPTED")
                self.assertEqual(turn["current_step"], 0)
                self.finish(service, rid, ChatProvider())

    def test_missing_run_claim_failure_clears_only_local_reservation(self):
        """准入仓储拒绝未知 Run 时，不残留本机占位或启动任何线程。"""
        service = ConversationWebService(self.root)
        with patch("threading.Thread") as constructor:
            with self.assertRaises(KeyError):
                service._spawn("unknown-fixture")
        constructor.assert_not_called()
        self.assertEqual(service.active, set())

    def test_foreign_lease_is_not_released_when_claim_is_denied(self):
        """竞争失败并不拥有旧租约，清理只移除本机标记，不删除其他 owner。"""
        service, rid = self.conversation()
        with MythRuntime(self.root) as runtime:
            self.assertTrue(Workspace(runtime).repository.claim_driver(rid, "another-driver", 60))
        with patch("threading.Thread") as constructor:
            service._spawn(rid)
        constructor.assert_not_called()
        self.assertNotIn(rid, service.active)
        self.assertEqual(self.turn(rid)[1]["owner_id"], "another-driver")

    def test_lease_cleanup_failure_is_visible_but_does_not_pin_active(self):
        """清租约失败保留持久 TTL 事实并发固定警告，不能假报释放或永留 active。"""
        service, rid = self.conversation()
        with patch("threading.Thread", side_effect=RuntimeError("fixture thread failure")), \
             patch.object(SqliteWorkspaceRepository, "release_driver", side_effect=RuntimeError("private fixture detail")):
            with self.assertLogs("myth.web_workspace", level="WARNING") as logs:
                with self.assertRaisesRegex(RuntimeError, "fixture thread failure"):
                    service._spawn(rid)
        self.assertNotIn(rid, service.active)
        self.assertIsNotNone(self.turn(rid)[1])
        self.assertNotIn("private fixture detail", " ".join(logs.output))

    def test_conversation_duplicate_admission_preserves_existing_driver(self):
        """同进程重复启动不重新竞争租约，也不清理原线程的标记。"""
        service, rid = self.conversation()
        service.active.add(rid)
        with patch("threading.Thread") as constructor, patch.object(SqliteWorkspaceRepository, "claim_driver") as claim:
            service._spawn(rid)
        constructor.assert_not_called()
        claim.assert_not_called()
        self.assertIn(rid, service.active)
        service.active.clear()
