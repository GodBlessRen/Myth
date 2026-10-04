"""回归边界：对话、资料、受管产物和实际恢复。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

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
from myth.models import (
    ModelResult,
    ProviderStatus,
    parse_step_decision,
    DecisionValidationError,
)
from myth.domain import IdentityConflict, RecoveryRequired
from myth.conversation import calculate


# 构造统一决定夹具；测试预期由固定断言提供，不由模型完成声明生成。
def decision(
    kind="request_completion", capability="", args=None, claim="这是回答。", question=""
):
    return json.dumps(
        {
            "decision_type": kind,
            "reason": "choose the next useful step",
            "capability_id": capability,
            "arguments_json": json.dumps(args or {}),
            "question": question,
            "missing_info_category": "",
            "claim": claim,
            "goal_coverage": "answer",
            "evidence_refs": [],
            "remaining": [],
        },
        ensure_ascii=False,
    )


# 对话、资料、受管产物和实际恢复的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class ChatProvider:
    provider_id = "ollama"

    # 保存可控测试条件；这些字段属于替身，不模拟远端真实保证。
    def __init__(self, outputs=None):
        self.outputs = outputs or [decision()]
        self.calls = []

    # 固定返回替身连接状态；只隔离传输，不证明真实供应商可用。
    def check(self):
        return ProviderStatus("ollama", True, details={"models": ["test"]})

    # 按预定顺序返回模型夹具或注入异常；调用计数用于核对重放边界。
    def invoke(self, request):
        self.calls.append(request)
        return ModelResult(
            self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)],
            {"model_calls": 1, "input_tokens": 20, "output_tokens": 30},
            {"text": "fixture"},
        )


# 对话、资料、受管产物和实际恢复的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class WorkspaceTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "test"})

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 对话、资料、受管产物和实际恢复的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def session(self, pid=None):
        return self.repo.create_session(project_id=pid)["id"]

    # 对话、资料、受管产物和实际恢复的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def turn(self, sid, text="你好", request_id="request", docs=None):
        return self.repo.create_turn(sid, text, request_id, docs)["run_id"]

    # 回归断言：普通对话无需精确文件合同，避免两个用例的准入条件耦合。
    def test_normal_conversation_requires_no_files_or_exact_contract(self):
        sid = self.session()
        rid = self.turn(sid)
        self.workspace.run(rid, ChatProvider())
        session = self.repo.session(sid)
        self.assertEqual(session["turns"][0]["status"], "COMPLETED")
        self.assertEqual(
            [m["role"] for m in session["messages"]], ["user", "assistant"]
        )
        self.assertFalse(session["messages"][-1]["metadata"]["execution_verified"])

    # 回归断言：父模型可自行选择隔离 worker，Child 只收到显式委派上下文并以普通工具结果返回。
    def test_llm_may_delegate_to_isolated_read_only_subagent(self):
        sid = self.session()
        rid = self.turn(
            sid,
            "主任务含 PARENT-ONLY-SECRET；请判断是否需要独立复核。",
        )
        provider = ChatProvider(
            [
                decision(
                    "tool_call",
                    "agent.delegate",
                    {
                        "task": "独立复核 FACT=A 是否足以支持给定结论。",
                        "context": "FACT=A",
                        "expected_output": "一句结论和未解决项",
                        "source_refs": [],
                    },
                ),
                decision(claim="子结论：FACT=A 可以支持当前局部结论。"),
                decision(claim="最终回答：已结合隔离复核结果。"),
            ]
        )
        self.workspace.run(rid, provider)

        self.assertEqual(self.repo.turn(rid)["status"], "COMPLETED")
        self.assertEqual(len(provider.calls), 3)
        child_request = provider.calls[1]
        child_text = "\n".join(message.content for message in child_request.messages)
        self.assertIn("FACT=A", child_text)
        self.assertNotIn("PARENT-ONLY-SECRET", child_text)
        self.assertEqual(
            child_request.response_schema["properties"]["decision_type"]["enum"],
            ["request_completion"],
        )
        result = self.repo.turn(rid)["activities"][0]["result"]
        self.assertTrue(result["subagent"]["context_isolated"])
        self.assertFalse(result["subagent"]["write_access"])
        self.assertFalse(result["subagent"]["recursive_delegation"])
        model_rows = self.repo.decisions.status(rid)["model_invocations"]
        self.assertTrue(
            any(
                str(row.get("request_key") or "").startswith("subagent:")
                for row in model_rows
            )
        )

    # 回归断言：Child 即使忽略输出 Schema 提议再次委派，本地边界也拒绝递归，不把它升级为执行权限。
    def test_subagent_cannot_recursively_delegate(self):
        rid = self.turn(self.session())
        provider = ChatProvider(
            [
                decision(
                    "tool_call",
                    "agent.delegate",
                    {"task": "独立检查一个问题。"},
                ),
                decision(
                    "tool_call",
                    "agent.delegate",
                    {"task": "尝试创建孙级 Agent。"},
                ),
                decision(claim="父 Agent 在子任务被拒绝后继续完成。"),
            ]
        )
        self.workspace.run(rid, provider)

        turn = self.repo.turn(rid)
        self.assertEqual(turn["status"], "COMPLETED")
        self.assertEqual(len(provider.calls), 3)
        self.assertIn(
            "sub-agent may only return request_completion",
            turn["activities"][0]["result"]["error"],
        )

    # 回归断言：重复 SEEK 在 Tool Ticket 前被拒绝，不消耗第二次 tool_calls，模型仍可基于已有观察继续回答。
    def test_live_information_control_rejects_duplicate_seek_before_tool_ticket(self):
        rid = self.turn(self.session(), "查找资料后回答")
        provider = ChatProvider(
            [
                decision(
                    "tool_call",
                    "knowledge.search",
                    {"query": "SILVER-92", "limit": 5},
                ),
                decision(
                    "tool_call",
                    "knowledge.search",
                    {"query": "SILVER-92", "limit": 5},
                ),
                decision(claim="已使用现有检索结果继续回答。"),
            ]
        )
        self.workspace.run(rid, provider)

        turn = self.repo.turn(rid)
        self.assertEqual(turn["status"], "COMPLETED")
        self.assertEqual(len(provider.calls), 3)
        self.assertEqual(
            turn["activities"][0]["result"]["information_control"]["action"],
            "SEEK",
        )
        self.assertIn(
            "information control denied:",
            turn["activities"][1]["result"]["error"],
        )
        accounts = {row["meter"]: row for row in turn["budgets"]}
        self.assertEqual(accounts["tool_calls"]["settled"], 1)
        self.assertEqual(len(self.repo.operations(rid)), 1)
        summary = self.workspace.execution.information_controller.summary(turn)
        self.assertEqual(summary["actions"], 1)
        self.assertEqual(summary["denied"], 1)

    # 回归断言：多轮请求包含保存的旧消息；重启后的历史以仓储为准。
    def test_multi_turn_model_receives_prior_messages(self):
        sid = self.session()
        self.workspace.run(
            self.turn(sid, "请记住数字 928"),
            ChatProvider([decision(claim="我记住了 928。")]),
        )
        rid = self.turn(sid, "之前的数字是什么？", "next")
        provider = ChatProvider()
        self.workspace.run(rid, provider)
        conversation = provider.calls[0].messages[1:]
        self.assertEqual(len(conversation), 3)
        self.assertIn("928", conversation[0].content)

    # 回归断言：项目资料与共享资料可见，另一项目资料不能进入当前召回。
    def test_project_and_shared_knowledge_are_retrieved_without_cross_project_leak(
        self,
    ):
        p = self.repo.create_project({"name": "A", "instructions": "始终用中文"})
        other = self.repo.create_project({"name": "B"})
        self.repo.import_document(
            {
                "title": "计划",
                "content": "Myth 的交付代号是 SILVER-92，发布时间是周五。",
                "project_id": p["id"],
            }
        )
        self.repo.import_document(
            {
                "title": "秘密",
                "content": "SILVER-92 不应该泄露到 A。",
                "project_id": other["id"],
            }
        )
        self.repo.import_document(
            {"title": "共享", "content": "发布时间需要明确验证。"}
        )
        rid = self.turn(self.session(p["id"]), "Myth 的发布时间和交付代号是什么？")
        snapshot = self.repo.turn(rid)["snapshot"]
        self.assertEqual(snapshot["project"]["instructions"], "始终用中文")
        self.assertNotIn("秘密", [s["title"] for s in snapshot["knowledge"]])
        self.assertIn("SILVER-92", str(snapshot))

    # 回归断言：显式附件不因词面无重叠而被遗漏；检索相关度不能撤销用户选择。
    def test_attached_document_is_pinned_even_without_query_overlap(self):
        doc = self.repo.import_document(
            {"title": "random", "content": "唯一口令是 ZEBRA-482。"}
        )
        rid = self.turn(self.session(), "总结刚附加的资料", docs=[doc["id"]])
        self.assertIn(
            "ZEBRA-482", self.repo.turn(rid)["snapshot"]["knowledge"][0]["content"]
        )

    # 回归断言：相同请求复用原 Turn，不同意图复用身份必须冲突。
    def test_duplicate_message_and_conflicting_retry(self):
        sid = self.session()
        rid = self.turn(sid)
        self.assertEqual(self.turn(sid), rid)
        with self.assertRaises(IdentityConflict):
            self.turn(sid, "different")
        self.assertEqual(len(self.repo.session(sid)["messages"]), 1)

    # 回归断言：会话只能有一个占有者；拒绝第二项工作时预算也不能残留。
    def test_two_active_turns_in_one_session_are_rejected_atomically(self):
        sid = self.session()
        self.turn(sid)
        with self.assertRaises(ValueError):
            self.turn(sid, "next", "second")
        self.assertEqual(len(self.repo.session(sid)["turns"]), 1)

    # 回归断言：工具实际发布的固定对象可下载，同时原始项目文件保持不变。
    def test_artifact_write_is_downloadable_and_source_is_preserved(self):
        source = self.root / "notes.txt"
        source.write_text("original", encoding="utf-8")
        p = self.repo.create_project({"name": "work", "root": str(self.root)})
        sid = self.session(p["id"])
        rid = self.turn(sid, "写一个文件")
        provider = ChatProvider(
            [
                decision(
                    "tool_call",
                    "artifact.write",
                    {"path": "reports/notes.md", "content": "# Ready\n内容"},
                ),
                decision(),
            ]
        )
        self.workspace.run(rid, provider)
        self.assertEqual(self.repo.turn(rid)["status"], "COMPLETED")
        artifact = self.repo.artifacts(sid)[0]
        self.assertEqual(
            self.runtime.objects.get(artifact["digest"]), "# Ready\n内容".encode()
        )
        self.assertEqual(source.read_text(), "original")

    # 回归断言：路径上跳、秘钥路径和未知能力均在外部效果前拒绝。
    def test_path_traversal_secret_paths_and_unknown_tools_are_rejected(self):
        p = self.repo.create_project({"name": "work", "root": str(self.root)})
        rid = self.turn(self.session(p["id"]))
        turn = self.repo.turn(rid)
        for value in [
            "../outside",
            ".env",
            ".git/config",
            "secret.pem",
            str(self.root / "file.txt"),
        ]:
            with self.assertRaises(PermissionError):
                self.workspace.execution.project_path(turn, value)
        provider = ChatProvider(
            [decision("tool_call", "shell.exec", {"command": "bad"}), decision()]
        )
        self.workspace.run(rid, provider)
        self.assertIn(
            "not admitted", self.repo.turn(rid)["activities"][0]["result"]["error"]
        )

    # 回归断言：精确修改只写受管副本，原字节换行与原项目文件保留。
    def test_project_patch_writes_copy_and_preserves_crlf(self):
        source = self.root / "data.txt"
        source.write_bytes(b"\xef\xbb\xbffoo\r\n")
        p = self.repo.create_project({"name": "work", "root": str(self.root)})
        sid = self.session(p["id"])
        rid = self.turn(sid)
        provider = ChatProvider(
            [
                decision(
                    "tool_call",
                    "project.patch_exact",
                    {
                        "path": "data.txt",
                        "old_text": "foo",
                        "new_text": "bar",
                        "expected_count": 1,
                    },
                ),
                decision(),
            ]
        )
        self.workspace.run(rid, provider)
        self.assertEqual(source.read_bytes(), b"\xef\xbb\xbffoo\r\n")
        self.assertEqual(
            self.runtime.objects.get(self.repo.artifacts(sid)[0]["digest"]),
            b"\xef\xbb\xbfbar\r\n",
        )

    # 回归断言：模型结果不明时继续操作先核对，不能新增供应商调用。
    def test_model_unknown_continue_never_calls_again(self):
        provider = ChatProvider()

        # 对话、资料、受管产物和实际恢复的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def timeout(request):
            provider.calls.append(request)
            raise RuntimeError("timeout")

        provider.invoke = timeout
        rid = self.turn(self.session())
        self.workspace.run(rid, provider)
        self.workspace.run(rid, provider)
        self.assertEqual(self.repo.turn(rid)["status"], "UNKNOWN")
        self.assertEqual(len(provider.calls), 1)

    # 回归断言：回答消费匹配当前问题身份；重复消费不能创建另一规划步骤。
    def test_question_answer_consumed_once(self):
        provider = ChatProvider(
            [decision("ask_user", question="你的读者是谁？"), decision()]
        )
        sid = self.session()
        rid = self.turn(sid)
        self.workspace.run(rid, provider)
        qid = self.repo.turn(rid)["question_id"]
        with self.assertRaises(ValueError):
            self.repo.answer(rid, "工程师", "old")
        self.repo.answer(rid, "工程师", qid)
        with self.assertRaises(ValueError):
            self.repo.answer(rid, "工程师", qid)
        self.workspace.run(rid, provider)
        self.assertEqual(self.repo.turn(rid)["status"], "COMPLETED")

    # 回归断言：模型在途到达 Stop 后，晚到提案不能派发新工具。
    def test_cancel_during_model_cannot_execute_tool(self):
        rid = self.turn(self.session())
        provider = ChatProvider(
            [
                decision(
                    "tool_call", "artifact.write", {"path": "x.md", "content": "bad"}
                )
            ]
        )
        original = provider.invoke

        # 按预定顺序返回模型夹具或注入异常；调用计数用于核对重放边界。
        def invoke(request):
            self.repo.block(rid, "CANCELLED", "stop")
            return original(request)

        provider.invoke = invoke
        self.workspace.run(rid, provider)
        self.assertEqual(self.repo.turn(rid)["status"], "CANCELLED")
        self.assertEqual(self.repo.artifacts(self.repo.turn(rid)["session_id"]), [])

    # 回归断言：工具已结算、步骤未消费的重启窗口复用收据，不重复写入/计费。
    def test_tool_receipt_before_step_consumption_does_not_repeat_write_or_charge(self):
        rid = self.turn(self.session())
        provider = ChatProvider(
            [
                decision(
                    "tool_call",
                    "artifact.write",
                    {"path": "file.md", "content": "done"},
                ),
                decision(),
            ]
        )

        # 对话、资料、受管产物和实际恢复的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
        class Crash(BaseException):
            pass

        with patch.object(self.repo, "finish_tool", side_effect=Crash):
            with self.assertRaises(Crash):
                self.workspace.run(rid, provider)
        self.workspace.run(rid, provider)
        self.assertEqual(len(provider.calls), 2)
        accounts = {a["meter"]: a for a in self.repo.turn(rid)["budgets"]}
        self.assertEqual(accounts["tool_calls"]["settled"], 1)
        self.assertEqual(accounts["write_bytes"]["settled"], 4)

    # 回归断言：会话元数据更新在重新打开后保留；归档不删除历史。
    def test_session_rename_pin_archive_restore_and_reload(self):
        sid = self.session()
        self.repo.update_session(
            sid, {"title": "重要讨论", "pinned": True, "archived": True}
        )
        self.assertEqual(self.repo.sessions(), [])
        self.repo.update_session(sid, {"archived": False})
        self.runtime.close()
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.assertEqual(self.repo.sessions()[0]["title"], "重要讨论")
        self.assertEqual(self.repo.sessions()[0]["pinned"], 1)

    # 回归断言：算术白名单拒绝可执行代码，避免确定性捷径扩大权限。
    def test_calculator_does_not_evaluate_code(self):
        self.assertEqual(calculate("(18+2)*7/2"), 70)
        for expression in ["__import__('os')", "2**99999", "[1]", "1/0"]:
            with self.assertRaises(ValueError):
                calculate(expression)

    # 回归断言：兼容线协议只改变表示，仍生成同一领域决定合同。
    def test_local_action_wire_projects_to_the_same_domain_contract(self):
        proposal = parse_step_decision(
            json.dumps(
                {
                    "action": "artifact.write",
                    "reason": "生成文件",
                    "arguments": {"path": "plan.md", "content": "ready"},
                }
            )
        )
        self.assertEqual(proposal.decision_type, "tool_call")
        self.assertEqual(proposal.capability_id, "artifact.write")
        self.assertEqual(proposal.arguments["content"], "ready")
        reply = parse_step_decision(
            json.dumps({"action": "reply", "reason": "回答", "claim": "你好"})
        )
        self.assertEqual(reply.goal_coverage, "answer")
        with self.assertRaises(DecisionValidationError):
            parse_step_decision(
                json.dumps(
                    {
                        "action": "artifact.write",
                        "reason": "bad",
                        "arguments": "not-an-object",
                    }
                )
            )

    # 回归断言：撤下未来知识召回后，旧快照的固定来源仍可核对。
    def test_archived_knowledge_keeps_historical_citation_readable(self):
        doc = self.repo.import_document(
            {"title": "资料", "content": "学习代号 SILVER-92"}
        )
        self.repo.archive_document(doc["id"])
        self.assertEqual(self.repo.search("SILVER-92"), [])
        self.assertIn("SILVER-92", self.repo.document(doc["id"])["content"])
        with self.assertRaises(ValueError):
            self.turn(self.session(), docs=[doc["id"]])

    # 回归断言：未知写入保留资源占用，晚到证据只允许结算一次。
    def test_unknown_write_holds_budget_and_late_evidence_settles_once(self):
        rid = self.turn(self.session())
        provider = ChatProvider(
            [
                decision(
                    "tool_call",
                    "artifact.write",
                    {"path": "late.md", "content": "late"},
                )
            ]
        )
        with patch(
            "myth.adapters.conversation_execution.atomic_write",
            side_effect=OSError("interrupted"),
        ):
            self.workspace.run(rid, provider)
        self.assertEqual(self.repo.turn(rid)["status"], "UNKNOWN")
        op = self.repo.pending_operations(rid)[0]
        accounts = {a["meter"]: a for a in self.repo.turn(rid)["budgets"]}
        self.assertEqual(accounts["write_bytes"]["unknown_held"], 4)
        self.assertEqual(accounts["write_bytes"]["reserved"], 0)
        self.workspace.run(rid, provider)
        self.assertEqual(len(provider.calls), 1)
        target = Path(op["intent"]["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"late")
        final = ChatProvider()
        self.workspace.run(rid, final)
        accounts = {a["meter"]: a for a in self.repo.turn(rid)["budgets"]}
        self.assertEqual(accounts["write_bytes"]["unknown_held"], 0)
        self.assertEqual(accounts["write_bytes"]["settled"], 4)
        self.assertEqual(len(self.repo.artifacts(self.repo.turn(rid)["session_id"])), 1)

    # 对话、资料、受管产物和实际恢复的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def hard_crash(self, boundary):
        rid = self.turn(self.session())
        output = decision(
            "tool_call", "artifact.write", {"path": "crash.md", "content": "once"}
        )
        hook = (
            "w.repository.bind=lambda *args: os._exit(93)"
            if boundary == "model"
            else """
import myth.adapters.conversation_execution as execution
original=execution.atomic_write
def write(path,data):
    original(path,data)
    if 'session-outputs' in path.parts:os._exit(94)
execution.atomic_write=write
"""
        )
        script = f"""import os
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
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        child = subprocess.run(
            [sys.executable, "-c", script], env=env, capture_output=True, timeout=15
        )
        self.assertEqual(
            child.returncode, 93 if boundary == "model" else 94, child.stderr
        )
        final = ChatProvider()
        self.workspace.run(rid, final)
        self.assertEqual(self.repo.turn(rid)["status"], "COMPLETED")
        self.assertEqual(len(final.calls), 1)
        accounts = {a["meter"]: a for a in self.repo.turn(rid)["budgets"]}
        self.assertEqual(accounts["model_calls"]["settled"], 2)
        self.assertEqual(accounts["tool_calls"]["settled"], 1)
        self.assertEqual(accounts["write_bytes"]["settled"], 4)

    # 回归断言：真实子进程退出后复用已保存模型收据/决定，不再调用供应商。
    def test_hard_exit_after_model_receipt_reuses_saved_decision(self):
        self.hard_crash("model")

    # 回归断言：实际写入后日志前硬退出，重开按固定摘要核对效果。
    def test_hard_exit_after_write_before_receipt_reconciles_digest(self):
        self.hard_crash("write")
