"""回归边界：持久游标、Driver Lease 与安全接管。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


SETTINGS = {
    "provider": "ollama",
    "model": "test",
    "max_steps": 8,
    "max_output_tokens": 512,
    "num_ctx": 8192,
    "temperature": 0.0,
    "thinking": False,
}


# 持久游标、Driver Lease 与安全接管的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class RecoveryFirstRuntimeTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings(SETTINGS)

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        try:
            self.runtime.close()
        except Exception:
            pass
        self.tmp.cleanup()

    # 创建固定会话和准入 Turn，返回稳定身份供重启/控制测试复用。
    def new_turn(self, request_id="recover"):
        sid = self.repo.create_session()["id"]
        turn = self.repo.create_turn(sid, "继续完成这个任务", request_id)
        return sid, turn["run_id"]

    # 回归断言：执行游标仅在持久步骤消费后推进，重开不能跳过未知机会。
    def test_cursor_is_durable_and_advances_only_at_persisted_checkpoints(self):
        _, rid = self.new_turn()
        cursor = self.repo.execution_cursor(rid)
        self.assertEqual(cursor["phase"], "ADMITTED")
        self.assertEqual(cursor["checkpoint_step"], 0)

        step = self.repo.begin_step(rid)
        cursor = self.repo.execution_cursor(rid)
        self.assertEqual(step["step"], 1)
        self.assertEqual(cursor["phase"], "STEP_STARTED")
        self.assertEqual(cursor["step"], 1)
        self.assertEqual(cursor["checkpoint_step"], 0)

        self.runtime.close()
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        restored = self.repo.execution_cursor(rid)
        self.assertEqual(restored["phase"], "STEP_STARTED")
        self.assertEqual(restored["step"], 1)
        self.assertEqual(restored["checkpoint_step"], 0)

    # 回归断言：租约过期且无未决效果才进入 INTERRUPTED，正常恢复继续原 Run。
    def test_expired_driver_without_uncertain_effect_becomes_interrupted_and_resumes(
        self,
    ):
        _, rid = self.new_turn()
        self.assertTrue(self.repo.claim_driver(rid, "dead-driver", 6))
        with self.runtime.store.tx() as db:
            db.execute(
                "UPDATE workspace_driver_leases SET lease_until=? WHERE run_id=?",
                (time.time() - 1, rid),
            )
        turn = self.repo.sweep_expired_driver(rid)
        self.assertEqual(turn["status"], "INTERRUPTED")
        cursor = self.repo.execution_cursor(rid)
        self.assertEqual(cursor["recovery_state"], "RESUME")
        self.assertEqual(cursor["phase"], "INTERRUPTED")

        provider = ChatProvider([decision(claim="从断点恢复完成。")])
        self.workspace.run(rid, provider)
        self.assertEqual(self.repo.turn(rid)["status"], "COMPLETED")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(self.repo.execution_cursor(rid)["phase"], "COMPLETED")

    # 回归断言：过期 Driver 的未知模型机会保持 RECONCILE，不能按超时认定未发出。
    def test_unknown_model_attempt_remains_reconcile_not_blind_resume(self):
        _, rid = self.new_turn("unknown-recovery")
        provider = ChatProvider()

        # 持久游标、Driver Lease 与安全接管的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def timeout(request):
            provider.calls.append(request)
            raise RuntimeError("synthetic timeout")

        provider.invoke = timeout
        self.workspace.run(rid, provider)
        self.assertEqual(self.repo.turn(rid)["status"], "UNKNOWN")
        cursor = self.repo.execution_cursor(rid)
        self.assertEqual(cursor["recovery_state"], "RECONCILE")
        self.assertEqual(cursor["phase"], "UNKNOWN")

        self.workspace.run(rid, provider)
        self.assertEqual(self.repo.turn(rid)["status"], "UNKNOWN")
        self.assertEqual(len(provider.calls), 1)

    # 回归断言：Driver 获得/续租/释放均有持久事实；回答结束先于 finally，等待实际释放。
    def test_web_driver_lease_is_acquired_heartbeated_and_released(self):
        sid, rid = self.new_turn("driver-lifecycle")
        service = ConversationWebService(self.root)
        provider = ChatProvider([decision(claim="worker finished")])
        service.provider = lambda settings: provider
        service._spawn(rid)

        deadline = time.time() + 5
        status = None
        while time.time() < deadline:
            with MythRuntime(self.root) as runtime:
                repo = Workspace(runtime).repository
                status = repo.turn(rid)["status"]
                # 回答提交先于 Driver finally 清理；等待两项事实都落库，不能把 COMPLETED 当成已释放租约。
                if status == "COMPLETED":
                    events = [item["kind"] for item in repo.events(rid)]
                    lease = repo.driver_lease(rid)
                    if lease is None and "DriverLeaseReleased" in events:
                        break
            time.sleep(0.03)
        self.assertEqual(status, "COMPLETED")
        self.assertIn("DriverLeaseAcquired", events)
        self.assertIn("DriverLeaseReleased", events)
        self.assertIsNone(lease)

    # 回归断言：恢复区域/renderer/继续按钮存在；不把静态检查当浏览器视觉验收。
    def test_recovery_observability_contract_is_present(self):
        webui = Path(__file__).resolve().parents[1] / "src" / "myth" / "webui"
        html = (webui / "index.html").read_text(encoding="utf-8")
        inspector = (webui / "inspector.js").read_text(encoding="utf-8")
        app = (webui / "app.js").read_text(encoding="utf-8")
        self.assertIn("inspectorRecovery", html)
        self.assertIn("renderInspectorRecovery", inspector)
        self.assertIn('"Recovery"', inspector)
        self.assertIn('"从断点继续"', app)
        self.assertIn('"核对并继续"', app)


if __name__ == "__main__":
    unittest.main()
