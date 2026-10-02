"""通用 Agent 的实际状态与文件合同；测试替身不算真实模型能力证明。"""
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.models import ModelResult, ProviderStatus, parse_step_decision, DecisionValidationError
from myth.domain import IdentityConflict, RecoveryRequired
from myth.conversation import calculate


def decision(kind="request_completion",capability="",args=None,claim="这是回答。",question=""):
    return json.dumps({"decision_type":kind,"reason":"choose the next useful step","capability_id":capability,"arguments_json":json.dumps(args or {}),"question":question,"missing_info_category":"","claim":claim,"goal_coverage":"answer","evidence_refs":[],"remaining":[]},ensure_ascii=False)


class ChatProvider:
    provider_id="ollama"
    def __init__(self,outputs=None):self.outputs=outputs or [decision()];self.calls=[]
    def check(self):return ProviderStatus("ollama",True,details={"models":["test"]})
    def invoke(self,request):
        self.calls.append(request)
        return ModelResult(self.outputs[min(len(self.calls)-1,len(self.outputs)-1)],{"model_calls":1,"input_tokens":20,"output_tokens":30},{"text":"fixture"})


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.runtime=MythRuntime(self.root);self.workspace=Workspace(self.runtime);self.repo=self.workspace.repository
        self.repo.save_settings({"provider":"ollama","model":"test"})
    def tearDown(self):self.runtime.close();self.tmp.cleanup()
    def session(self,pid=None):return self.repo.create_session(project_id=pid)["id"]
    def turn(self,sid,text="你好",request_id="request",docs=None):return self.repo.create_turn(sid,text,request_id,docs)["run_id"]

    def test_normal_conversation_requires_no_files_or_exact_contract(self):
        sid=self.session();rid=self.turn(sid);self.workspace.run(rid,ChatProvider())
        session=self.repo.session(sid)
        self.assertEqual(session["turns"][0]["status"],"COMPLETED")
        self.assertEqual([m["role"] for m in session["messages"]],["user","assistant"])
        self.assertFalse(session["messages"][-1]["metadata"]["execution_verified"])

    def test_multi_turn_model_receives_prior_messages(self):
        sid=self.session();self.workspace.run(self.turn(sid,"请记住数字 928"),ChatProvider([decision(claim="我记住了 928。")]))
        rid=self.turn(sid,"之前的数字是什么？","next");provider=ChatProvider()
        self.workspace.run(rid,provider)
        conversation=provider.calls[0].messages[1:]
        self.assertEqual(len(conversation),3)
        self.assertIn("928",conversation[0].content)

    def test_project_and_shared_knowledge_are_retrieved_without_cross_project_leak(self):
        p=self.repo.create_project({"name":"A","instructions":"始终用中文"});other=self.repo.create_project({"name":"B"})
        self.repo.import_document({"title":"计划","content":"Myth 的交付代号是 SILVER-92，发布时间是周五。","project_id":p["id"]})
        self.repo.import_document({"title":"秘密","content":"SILVER-92 不应该泄露到 A。","project_id":other["id"]})
        self.repo.import_document({"title":"共享","content":"发布时间需要明确验证。"})
        rid=self.turn(self.session(p["id"]),"Myth 的发布时间和交付代号是什么？")
        snapshot=self.repo.turn(rid)["snapshot"]
        self.assertEqual(snapshot["project"]["instructions"],"始终用中文")
        self.assertNotIn("秘密",[s["title"] for s in snapshot["knowledge"]])
        self.assertIn("SILVER-92",str(snapshot))

    def test_attached_document_is_pinned_even_without_query_overlap(self):
        doc=self.repo.import_document({"title":"random","content":"唯一口令是 ZEBRA-482。"})
        rid=self.turn(self.session(),"总结刚附加的资料",docs=[doc["id"]])
        self.assertIn("ZEBRA-482",self.repo.turn(rid)["snapshot"]["knowledge"][0]["content"])

    def test_duplicate_message_and_conflicting_retry(self):
        sid=self.session();rid=self.turn(sid)
        self.assertEqual(self.turn(sid),rid)
        with self.assertRaises(IdentityConflict):self.turn(sid,"different")
        self.assertEqual(len(self.repo.session(sid)["messages"]),1)

    def test_two_active_turns_in_one_session_are_rejected_atomically(self):
        sid=self.session();self.turn(sid)
        with self.assertRaises(ValueError):self.turn(sid,"next","second")
        self.assertEqual(len(self.repo.session(sid)["turns"]),1)

    def test_artifact_write_is_downloadable_and_source_is_preserved(self):
        source=self.root/"notes.txt";source.write_text("original",encoding="utf-8")
        p=self.repo.create_project({"name":"work","root":str(self.root)})
        sid=self.session(p["id"]);rid=self.turn(sid,"写一个文件")
        provider=ChatProvider([decision("tool_call","artifact.write",{"path":"reports/notes.md","content":"# Ready\n内容"}),decision()])
        self.workspace.run(rid,provider)
        self.assertEqual(self.repo.turn(rid)["status"],"COMPLETED")
        artifact=self.repo.artifacts(sid)[0]
        self.assertEqual(self.runtime.objects.get(artifact["digest"]),"# Ready\n内容".encode())
        self.assertEqual(source.read_text(),"original")

    def test_path_traversal_secret_paths_and_unknown_tools_are_rejected(self):
        p=self.repo.create_project({"name":"work","root":str(self.root)})
        rid=self.turn(self.session(p["id"]));turn=self.repo.turn(rid)
        for value in ["../outside",".env",".git/config","secret.pem",str(self.root/"file.txt")]:
            with self.assertRaises(PermissionError):self.workspace.execution.project_path(turn,value)
        provider=ChatProvider([decision("tool_call","shell.exec",{"command":"bad"}),decision()]);self.workspace.run(rid,provider)
        self.assertIn("not admitted",self.repo.turn(rid)["activities"][0]["result"]["error"])

    def test_project_patch_writes_copy_and_preserves_crlf(self):
        source=self.root/"data.txt";source.write_bytes(b"\xef\xbb\xbffoo\r\n")
        p=self.repo.create_project({"name":"work","root":str(self.root)});sid=self.session(p["id"]);rid=self.turn(sid)
        provider=ChatProvider([decision("tool_call","project.patch_exact",{"path":"data.txt","old_text":"foo","new_text":"bar","expected_count":1}),decision()])
        self.workspace.run(rid,provider)
        self.assertEqual(source.read_bytes(),b"\xef\xbb\xbffoo\r\n")
        self.assertEqual(self.runtime.objects.get(self.repo.artifacts(sid)[0]["digest"]),b"\xef\xbb\xbfbar\r\n")

    def test_model_unknown_continue_never_calls_again(self):
        provider=ChatProvider()
        def timeout(request):provider.calls.append(request);raise RuntimeError("timeout")
        provider.invoke=timeout
        rid=self.turn(self.session());self.workspace.run(rid,provider);self.workspace.run(rid,provider)
        self.assertEqual(self.repo.turn(rid)["status"],"UNKNOWN");self.assertEqual(len(provider.calls),1)

    def test_question_answer_consumed_once(self):
        provider=ChatProvider([decision("ask_user",question="你的读者是谁？"),decision()]);sid=self.session();rid=self.turn(sid)
        self.workspace.run(rid,provider);qid=self.repo.turn(rid)["question_id"]
        with self.assertRaises(ValueError):self.repo.answer(rid,"工程师","old")
        self.repo.answer(rid,"工程师",qid)
        with self.assertRaises(ValueError):self.repo.answer(rid,"工程师",qid)
        self.workspace.run(rid,provider)
        self.assertEqual(self.repo.turn(rid)["status"],"COMPLETED")

    def test_cancel_during_model_cannot_execute_tool(self):
        rid=self.turn(self.session());provider=ChatProvider([decision("tool_call","artifact.write",{"path":"x.md","content":"bad"})]);original=provider.invoke
        def invoke(request):self.repo.block(rid,"CANCELLED","stop");return original(request)
        provider.invoke=invoke;self.workspace.run(rid,provider)
        self.assertEqual(self.repo.turn(rid)["status"],"CANCELLED")
        self.assertEqual(self.repo.artifacts(self.repo.turn(rid)["session_id"]),[])

    def test_tool_receipt_before_step_consumption_does_not_repeat_write_or_charge(self):
        rid=self.turn(self.session());provider=ChatProvider([decision("tool_call","artifact.write",{"path":"file.md","content":"done"}),decision()])
        class Crash(BaseException):pass
        with patch.object(self.repo,"finish_tool",side_effect=Crash):
            with self.assertRaises(Crash):self.workspace.run(rid,provider)
        self.workspace.run(rid,provider)
        self.assertEqual(len(provider.calls),2)
        accounts={a["meter"]:a for a in self.repo.turn(rid)["budgets"]}
        self.assertEqual(accounts["tool_calls"]["settled"],1)
        self.assertEqual(accounts["write_bytes"]["settled"],4)

    def test_session_rename_pin_archive_restore_and_reload(self):
        sid=self.session();self.repo.update_session(sid,{"title":"重要讨论","pinned":True,"archived":True})
        self.assertEqual(self.repo.sessions(),[])
        self.repo.update_session(sid,{"archived":False})
        self.runtime.close();self.runtime=MythRuntime(self.root);self.workspace=Workspace(self.runtime);self.repo=self.workspace.repository
        self.assertEqual(self.repo.sessions()[0]["title"],"重要讨论")
        self.assertEqual(self.repo.sessions()[0]["pinned"],1)

    def test_calculator_does_not_evaluate_code(self):
        self.assertEqual(calculate("(18+2)*7/2"),70)
        for expression in ["__import__('os')","2**99999","[1]","1/0"]:
            with self.assertRaises(ValueError):calculate(expression)

    def test_local_action_wire_projects_to_the_same_domain_contract(self):
        proposal=parse_step_decision(json.dumps({"action":"artifact.write","reason":"生成文件","arguments":{"path":"plan.md","content":"ready"}}))
        self.assertEqual(proposal.decision_type,"tool_call")
        self.assertEqual(proposal.capability_id,"artifact.write")
        self.assertEqual(proposal.arguments["content"],"ready")
        reply=parse_step_decision(json.dumps({"action":"reply","reason":"回答","claim":"你好"}))
        self.assertEqual(reply.goal_coverage,"answer")
        with self.assertRaises(DecisionValidationError):parse_step_decision(json.dumps({"action":"artifact.write","reason":"bad","arguments":"not-an-object"}))

    def test_archived_knowledge_keeps_historical_citation_readable(self):
        doc=self.repo.import_document({"title":"资料","content":"学习代号 SILVER-92"})
        self.repo.archive_document(doc["id"])
        self.assertEqual(self.repo.search("SILVER-92"),[])
        self.assertIn("SILVER-92",self.repo.document(doc["id"])["content"])
        with self.assertRaises(ValueError):self.turn(self.session(),docs=[doc["id"]])

    def test_unknown_write_holds_budget_and_late_evidence_settles_once(self):
        rid=self.turn(self.session());provider=ChatProvider([decision("tool_call","artifact.write",{"path":"late.md","content":"late"})])
        with patch("myth.adapters.conversation_execution.atomic_write",side_effect=OSError("interrupted")):
            self.workspace.run(rid,provider)
        self.assertEqual(self.repo.turn(rid)["status"],"UNKNOWN")
        op=self.repo.pending_operations(rid)[0]
        accounts={a["meter"]:a for a in self.repo.turn(rid)["budgets"]}
        self.assertEqual(accounts["write_bytes"]["unknown_held"],4)
        self.assertEqual(accounts["write_bytes"]["reserved"],0)
        self.workspace.run(rid,provider)
        self.assertEqual(len(provider.calls),1)
        target=Path(op["intent"]["target"]);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b"late")
        final=ChatProvider();self.workspace.run(rid,final)
        accounts={a["meter"]:a for a in self.repo.turn(rid)["budgets"]}
        self.assertEqual(accounts["write_bytes"]["unknown_held"],0)
        self.assertEqual(accounts["write_bytes"]["settled"],4)
        self.assertEqual(len(self.repo.artifacts(self.repo.turn(rid)["session_id"])),1)

    def hard_crash(self,boundary):
        rid=self.turn(self.session())
        output=decision("tool_call","artifact.write",{"path":"crash.md","content":"once"})
        hook="w.repository.bind=lambda *args: os._exit(93)" if boundary=="model" else '''
import myth.adapters.conversation_execution as execution
original=execution.atomic_write
def write(path,data):
    original(path,data)
    if 'session-outputs' in path.parts:os._exit(94)
execution.atomic_write=write
'''
        script=f'''import os
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.models import ModelResult
class Provider:
    provider_id='ollama'
    def invoke(self,request):return ModelResult({output!r},{{'model_calls':1,'input_tokens':20,'output_tokens':30}},{{}})
r=MythRuntime({str(self.root)!r})
w=Workspace(r)
{hook}
w.run({rid!r},Provider())
'''
        env=os.environ.copy();env["PYTHONPATH"]=str(Path(__file__).resolve().parents[1]/"src")
        child=subprocess.run([sys.executable,"-c",script],env=env,capture_output=True,timeout=15)
        self.assertEqual(child.returncode,93 if boundary=="model" else 94,child.stderr)
        final=ChatProvider();self.workspace.run(rid,final)
        self.assertEqual(self.repo.turn(rid)["status"],"COMPLETED")
        self.assertEqual(len(final.calls),1)
        accounts={a["meter"]:a for a in self.repo.turn(rid)["budgets"]}
        self.assertEqual(accounts["model_calls"]["settled"],2)
        self.assertEqual(accounts["tool_calls"]["settled"],1)
        self.assertEqual(accounts["write_bytes"]["settled"],4)

    def test_hard_exit_after_model_receipt_reuses_saved_decision(self):self.hard_crash("model")
    def test_hard_exit_after_write_before_receipt_reconciles_digest(self):self.hard_crash("write")
