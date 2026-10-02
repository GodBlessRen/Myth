"""目标与恢复反例；Fake、真实磁盘与硬进程退出分别记录覆盖范围。"""
from __future__ import annotations
import json
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from myth.acceptance import ContextBudgetError, compile_context, freeze_acceptance, verify_goal
from myth.agent_runtime import AgentRuntime
from myth.domain import IdentityConflict, RecoveryRequired
from myth.models import ModelResult
from myth.providers.scripted import ScriptedPatchProvider
from myth.runtime import MythRuntime
from test_agent_runtime import AskProvider, LoopProvider


def rule(source, old="foo", new="bar"):
    return {"path": str(source), "old_text": old, "new_text": new, "expected_count": 1}


class VerifiedAgentTests(unittest.TestCase):
    @contextmanager
    def sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._owned_runtimes = []
            try:
                yield tmp
            finally:
                for runtime in reversed(self._owned_runtimes):
                    runtime.close()

    def fixture(self, root, provider=None, **kwargs):
        source = root / "data.txt"
        source.write_bytes(b"\xef\xbb\xbffoo\r\nkeep bar\r\n")
        runtime = MythRuntime(root)
        agent = AgentRuntime(runtime)
        provider = provider or ScriptedPatchProvider()
        rid = agent.create_run(goal="replace foo with bar", provider=provider, model="test",
                               allowed_files=(source,), acceptance=[rule(source)], **kwargs)
        self._owned_runtimes.append(runtime)
        return source, runtime, agent, provider, rid

    def test_wrong_patch_receipt_cannot_prove_goal(self):
        class Wrong(LoopProvider):
            def invoke(self, request):
                result = super().invoke(request)
                value = json.loads(result.text)
                if value["decision_type"] == "tool_call":
                    args = json.loads(value["arguments_json"])
                    args["new_text"] = "WRONG"
                    value["arguments_json"] = json.dumps(args)
                return ModelResult(json.dumps(value), result.usage, result.raw)
        with self.sandbox() as tmp:
            _, _, agent, provider, rid = self.fixture(Path(tmp), Wrong(), max_steps=3)
            status = agent.run(rid, provider)
            self.assertIsNone(status["delivery"])
            self.assertEqual(status["verification"][-1]["verdict"], "FAIL")

    def test_no_goal_contract_never_delivers(self):
        with self.sandbox() as tmp:
            root=Path(tmp); source=root/"data.txt";source.write_text("foo")
            with MythRuntime(root) as runtime:
                agent=AgentRuntime(runtime);provider=LoopProvider()
                rid=agent.create_run(goal="some goal",provider=provider,model="test",allowed_files=(source,),max_steps=3)
                self.assertIsNone(agent.run(rid,provider)["delivery"])

    def test_baseline_is_fixed_before_first_model_call(self):
        with self.sandbox() as tmp:
            source, runtime, agent, provider, rid=self.fixture(Path(tmp))
            source.write_text("external writer changed source",encoding="utf-8")
            status=agent.run(rid,provider)
            self.assertEqual(status["agent"]["status"],"SUCCEEDED")
            self.assertEqual(runtime.workspaces.path_for(rid,source.name).read_bytes(),b"\xef\xbb\xbfbar\r\nkeep bar\r\n")
            self.assertEqual(source.read_text(),"external writer changed source")

    def test_multiple_files_and_preserved_file_are_verified(self):
        with self.sandbox() as tmp:
            root=Path(tmp); a=root/"a.txt";b=root/"b.txt";c=root/"keep.txt"
            a.write_text("foo");b.write_text("foo");c.write_text("unchanged")
            with MythRuntime(root) as runtime:
                agent=AgentRuntime(runtime);provider=ScriptedPatchProvider()
                rid=agent.create_run(goal="replace in two files",provider=provider,model="test",allowed_files=(a,b,c),
                                     acceptance=[rule(a),rule(b)],max_steps=8)
                status=agent.run(rid,provider)
                self.assertEqual(status["agent"]["status"],"SUCCEEDED")
                self.assertEqual(len(status["tool_actions"]),2)
                self.assertEqual(runtime.workspaces.path_for(rid,c.name).read_text(),"unchanged")

    def test_duplicate_filenames_rejected_before_run(self):
        with self.sandbox() as tmp:
            root=Path(tmp);(root/"nested").mkdir();a=root/"same.txt";b=root/"nested"/"same.txt"
            a.write_text("foo");b.write_text("foo")
            with MythRuntime(root) as runtime:
                agent=AgentRuntime(runtime)
                with self.assertRaises(ValueError):
                    agent.create_run(goal="edit",provider=ScriptedPatchProvider(),model="test",allowed_files=(a,b))
                self.assertEqual(agent.list_runs(),[])

    def test_entry_deduplicates_and_conflicts_on_limits(self):
        with self.sandbox() as tmp:
            source,runtime,agent,provider,rid=self.fixture(Path(tmp),request_id="stable")
            args=dict(goal="replace foo with bar",provider=provider,model="test",allowed_files=(source,),acceptance=[rule(source)],request_id="stable")
            self.assertEqual(agent.create_run(**args),rid)
            with self.assertRaises(IdentityConflict):agent.create_run(**args,max_steps=7)
            self.assertEqual(len(agent.list_runs()),1)

    def test_unknown_provider_is_not_called_again_on_continue(self):
        class Timeout(LoopProvider):
            calls=0
            def invoke(self,request):
                self.calls+=1
                raise RuntimeError("remote result lost")
        with self.sandbox() as tmp:
            _,_,agent,provider,rid=self.fixture(Path(tmp),Timeout())
            self.assertEqual(agent.run(rid,provider)["agent"]["status"],"UNKNOWN")
            self.assertEqual(agent.run(rid,provider)["agent"]["status"],"UNKNOWN")
            self.assertEqual(provider.calls,1)

    def test_invalid_response_is_charged_and_next_step_uses_new_request(self):
        class Repair(ScriptedPatchProvider):
            calls=0
            def invoke(self,request):
                self.calls+=1
                if self.calls==1:return ModelResult("bad JSON",{"model_calls":1,"input_tokens":2,"output_tokens":3},{"bad":True})
                return super().invoke(request)
        with self.sandbox() as tmp:
            _,_,agent,provider,rid=self.fixture(Path(tmp),Repair())
            status=agent.run(rid,provider)
            self.assertEqual(status["agent"]["status"],"SUCCEEDED")
            accounts={a["meter"]:a for a in status["model"]["budgets"]}
            self.assertEqual(accounts["model_calls"]["settled"],4)
            self.assertEqual(accounts["output_tokens"]["settled"],3)

    def test_cancel_during_model_call_cannot_start_tool(self):
        with self.sandbox() as tmp:
            _,_,agent,provider,rid=self.fixture(Path(tmp))
            original=provider.invoke
            def invoke(request):
                agent.cancel(rid)
                return original(request)
            with patch.object(provider,"invoke",side_effect=invoke):status=agent.run(rid,provider)
            self.assertEqual(status["agent"]["status"],"CANCELLED")
            self.assertEqual(status["tool_actions"],[])
            self.assertIsNone(status["delivery"])
            self.assertEqual(status["model"]["model_invocations"][0]["state"],"RESOLVED")

    def test_answer_requires_current_question_and_is_consumed_once(self):
        with self.sandbox() as tmp:
            _,_,agent,provider,rid=self.fixture(Path(tmp),AskProvider())
            status=agent.run(rid,provider);question=status["agent"]["question_id"]
            with self.assertRaises(ValueError):agent.repository.answer(rid,"stale","answer")
            self.assertEqual(agent.status(rid)["agent"]["status"],"WAITING_USER")
            agent.repository.answer(rid,question,"answer")
            with self.assertRaises(ValueError):agent.repository.answer(rid,question,"answer")

    def test_os_lock_rejects_second_local_driver(self):
        with self.sandbox() as tmp:
            _,_,agent,_,rid=self.fixture(Path(tmp))
            with agent.execution.lock(rid):
                with self.assertRaises(RecoveryRequired):
                    with agent.execution.lock(rid):pass

    def test_context_keeps_corrections_and_references_without_rewriting_notes(self):
        notes=[{"sequence":i,"kind":"user" if i==1 else "tool_result","payload":{"text":"最新约束"} if i==1 else
                {"preview":"x"*5000,"evidence_ref":f"ref-{i}","source_file":"a"}} for i in range(1,31)]
        original=json.dumps(notes);value=json.loads(compile_context(notes,{"rules":[]}))
        self.assertEqual(value["constraints"][0]["payload"]["text"],"最新约束")
        self.assertEqual(len(value["tool_evidence"]),29)
        self.assertEqual(value["latest_tool_result"]["preview"],"x"*5000)
        self.assertEqual(original,json.dumps(notes))
        with self.assertRaises(ContextBudgetError):compile_context(notes,{"rules":[]},max_bytes=5)
        with self.assertRaises(ContextBudgetError):
            compile_context([notes[-1]],{"rules":[]},max_bytes=1000)

    def test_untouched_file_and_remaining_work_block_completion(self):
        from myth.domain import sha256_bytes
        manifest=freeze_acceptance({"a":b"foo","keep":b"unchanged"},[rule("a")])
        current={"a":sha256_bytes(b"bar"),"keep":sha256_bytes(b"tampered")}
        evidence={"ref":{"source_file":"a","after_digest":current["a"],"attempt_state":"RESOLVED","outcome":"SUCCEEDED"}}
        self.assertEqual(verify_goal(manifest,current,evidence,("ref",),())[0].value,"FAIL")
        current["keep"]=sha256_bytes(b"unchanged")
        self.assertEqual(verify_goal(manifest,current,evidence,("ref",),("not done",))[0].value,"INCONCLUSIVE")

    def test_cancel_prepared_intent_releases_reservations_and_prevents_ticket(self):
        with self.sandbox() as tmp:
            source,runtime,agent,provider,rid=self.fixture(Path(tmp))
            prepared=runtime.prepare_patch_action(rid,source,old_text="foo",new_text="bar",expected_count=1)
            agent.cancel(rid)
            with self.assertRaises(RecoveryRequired):runtime.execute_patch_action(rid,action_id=prepared["action_id"])
            self.assertEqual(runtime.workspaces.path_for(rid,source.name).read_bytes(),b"\xef\xbb\xbffoo\r\nkeep bar\r\n")
            self.assertEqual(runtime.store.db.execute("SELECT COUNT(*) FROM tickets JOIN attempts USING(attempt_id) WHERE run_id=?",(rid,)).fetchone()[0],0)
            for account in runtime.store.get_accounts(rid):self.assertEqual(account["reserved"],0)

    def test_oversized_full_model_request_stops_before_model_ticket(self):
        with self.sandbox() as tmp:
            _,_,agent,provider,rid=self.fixture(Path(tmp))
            agent.runtime.store.db.execute("UPDATE runs SET goal=? WHERE run_id=?",("x"*70000,rid))
            status=agent.run(rid,provider)
            self.assertEqual(status["agent"]["status"],"FAILED")
            self.assertEqual(status["model"]["model_invocations"],[])

    def test_late_model_receipt_settles_unknown_hold_once(self):
        with self.sandbox() as tmp:
            _,runtime,agent,provider,rid=self.fixture(Path(tmp))
            step=agent.repository.begin_step(rid)
            decisions=agent.repository.decisions
            original=decisions._settle
            def interrupt(attempt_id,receipt):
                decisions._mark_unknown(attempt_id,"interrupted before settle")
                raise RuntimeError("interrupted")
            with patch.object(decisions,"_settle",side_effect=interrupt):
                with self.assertRaises(RuntimeError):agent.execution.request_decision(rid,step["step"],provider,compile_context(agent.repository.notes(rid),agent.repository.manifest(rid)))
            decisions.recover(rid);decisions.recover(rid)
            status=agent.run(rid,provider)
            self.assertEqual(status["agent"]["status"],"SUCCEEDED")
            for account in runtime.store.get_accounts(rid):
                self.assertEqual(account["reserved"],0)
                self.assertEqual(account["unknown_held"],0)


class AgentHardCrashTests(unittest.TestCase):
    def hard_crash(self, boundary):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/"data.txt";source.write_bytes(b"foo\r\n")
            provider=ScriptedPatchProvider()
            with MythRuntime(root) as runtime:
                rid=AgentRuntime(runtime).create_run(goal="replace",provider=provider,model="test",allowed_files=(source,),acceptance=[rule(source)])
            hook = "agent.repository.bind_decision = lambda *args: os._exit(93)" if boundary=="model" else (
                "original=agent.execution.execute\n"
                "def execute(*args):\n"
                "    result=original(*args)\n"
                "    if args[-1].capability_id=='file.patch_exact': os._exit(94)\n"
                "    return result\n"
                "agent.execution.execute=execute")
            script=f"import os\nfrom myth.runtime import MythRuntime\nfrom myth.agent_runtime import AgentRuntime\nfrom myth.providers.scripted import ScriptedPatchProvider\nruntime=MythRuntime({str(root)!r})\nagent=AgentRuntime(runtime)\n{hook}\nagent.run({rid!r},ScriptedPatchProvider())"
            env=os.environ.copy();env["PYTHONPATH"]=str(Path(__file__).resolve().parents[1]/"src")
            child=subprocess.run([sys.executable,"-c",script],env=env,capture_output=True,timeout=15)
            self.assertEqual(child.returncode,93 if boundary=="model" else 94,child.stderr)
            with MythRuntime(root) as runtime:
                agent=AgentRuntime(runtime);status=agent.run(rid,provider)
                self.assertEqual(status["agent"]["status"],"SUCCEEDED")
                self.assertEqual(len(status["tool_actions"]),1)
                accounts={a["meter"]:a for a in status["model"]["budgets"]}
                self.assertEqual(accounts["model_calls"]["settled"],3)
                self.assertEqual(accounts["tool_calls"]["settled"],2)
                self.assertEqual(runtime.workspaces.path_for(rid,"data.txt").read_bytes(),b"bar\r\n")
                self.assertEqual(runtime.store.db.execute("SELECT COUNT(*) FROM deliveries WHERE run_id=?",(rid,)).fetchone()[0],0)
    def test_restart_after_model_receipt_does_not_call_model_again(self):self.hard_crash("model")
    def test_restart_after_patch_settle_does_not_repeat_patch(self):self.hard_crash("tool")
