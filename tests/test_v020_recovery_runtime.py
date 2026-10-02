from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


SETTINGS={
    "provider":"ollama",
    "model":"test",
    "max_steps":8,
    "max_output_tokens":512,
    "num_ctx":8192,
    "temperature":0.0,
    "thinking":False,
}


class RecoveryFirstRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.runtime=MythRuntime(self.root)
        self.workspace=Workspace(self.runtime)
        self.repo=self.workspace.repository
        self.repo.save_settings(SETTINGS)

    def tearDown(self):
        try:
            self.runtime.close()
        except Exception:
            pass
        self.tmp.cleanup()

    def new_turn(self,request_id="recover"):
        sid=self.repo.create_session()["id"]
        turn=self.repo.create_turn(sid,"继续完成这个任务",request_id)
        return sid,turn["run_id"]

    def test_cursor_is_durable_and_advances_only_at_persisted_checkpoints(self):
        _,rid=self.new_turn()
        cursor=self.repo.execution_cursor(rid)
        self.assertEqual(cursor["phase"],"ADMITTED")
        self.assertEqual(cursor["checkpoint_step"],0)

        step=self.repo.begin_step(rid)
        cursor=self.repo.execution_cursor(rid)
        self.assertEqual(step["step"],1)
        self.assertEqual(cursor["phase"],"STEP_STARTED")
        self.assertEqual(cursor["step"],1)
        self.assertEqual(cursor["checkpoint_step"],0)

        self.runtime.close()
        self.runtime=MythRuntime(self.root)
        self.workspace=Workspace(self.runtime)
        self.repo=self.workspace.repository
        restored=self.repo.execution_cursor(rid)
        self.assertEqual(restored["phase"],"STEP_STARTED")
        self.assertEqual(restored["step"],1)
        self.assertEqual(restored["checkpoint_step"],0)

    def test_expired_driver_without_uncertain_effect_becomes_interrupted_and_resumes(self):
        _,rid=self.new_turn()
        self.assertTrue(self.repo.claim_driver(rid,"dead-driver",6))
        with self.runtime.store.tx() as db:
            db.execute(
                "UPDATE workspace_driver_leases SET lease_until=? WHERE run_id=?",
                (time.time()-1,rid),
            )
        turn=self.repo.sweep_expired_driver(rid)
        self.assertEqual(turn["status"],"INTERRUPTED")
        cursor=self.repo.execution_cursor(rid)
        self.assertEqual(cursor["recovery_state"],"RESUME")
        self.assertEqual(cursor["phase"],"INTERRUPTED")

        provider=ChatProvider([decision(claim="从断点恢复完成。")])
        self.workspace.run(rid,provider)
        self.assertEqual(self.repo.turn(rid)["status"],"COMPLETED")
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(self.repo.execution_cursor(rid)["phase"],"COMPLETED")

    def test_unknown_model_attempt_remains_reconcile_not_blind_resume(self):
        _,rid=self.new_turn("unknown-recovery")
        provider=ChatProvider()
        def timeout(request):
            provider.calls.append(request)
            raise RuntimeError("synthetic timeout")
        provider.invoke=timeout
        self.workspace.run(rid,provider)
        self.assertEqual(self.repo.turn(rid)["status"],"UNKNOWN")
        cursor=self.repo.execution_cursor(rid)
        self.assertEqual(cursor["recovery_state"],"RECONCILE")
        self.assertEqual(cursor["phase"],"UNKNOWN")

        self.workspace.run(rid,provider)
        self.assertEqual(self.repo.turn(rid)["status"],"UNKNOWN")
        self.assertEqual(len(provider.calls),1)

    def test_web_driver_lease_is_acquired_heartbeated_and_released(self):
        sid,rid=self.new_turn("driver-lifecycle")
        service=ConversationWebService(self.root)
        provider=ChatProvider([decision(claim="worker finished")])
        service.provider=lambda settings: provider
        service._spawn(rid)

        deadline=time.time()+5
        status=None
        while time.time()<deadline:
            with MythRuntime(self.root) as runtime:
                repo=Workspace(runtime).repository
                status=repo.turn(rid)["status"]
                if status=="COMPLETED":
                    events=[item["kind"] for item in repo.events(rid)]
                    lease=repo.driver_lease(rid)
                    break
            time.sleep(0.03)
        self.assertEqual(status,"COMPLETED")
        self.assertIn("DriverLeaseAcquired",events)
        self.assertIn("DriverLeaseReleased",events)
        self.assertIsNone(lease)

    def test_recovery_observability_contract_is_present(self):
        webui=Path(__file__).resolve().parents[1]/"src"/"myth"/"webui"
        html=(webui/"index.html").read_text(encoding="utf-8")
        inspector=(webui/"inspector.js").read_text(encoding="utf-8")
        app=(webui/"app.js").read_text(encoding="utf-8")
        self.assertIn("inspectorRecovery",html)
        self.assertIn("renderInspectorRecovery",inspector)
        self.assertIn('"Recovery"',inspector)
        self.assertIn('"从断点继续"',app)
        self.assertIn('"核对并继续"',app)


if __name__=="__main__":
    unittest.main()
