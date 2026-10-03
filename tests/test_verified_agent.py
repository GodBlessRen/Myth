"""回归边界：独立固定验收与 Agent 崩溃窗口。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

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

from myth.acceptance import (
    ContextBudgetError,
    compile_context,
    freeze_acceptance,
    verify_goal,
)
from myth.agent_runtime import AgentRuntime
from myth.domain import IdentityConflict, RecoveryRequired
from myth.models import ModelResult
from myth.providers.scripted import ScriptedPatchProvider
from myth.runtime import MythRuntime
from test_agent_runtime import AskProvider, LoopProvider


# 独立固定验收与 Agent 崩溃窗口的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
def rule(source, old="foo", new="bar"):
    return {"path": str(source), "old_text": old, "new_text": new, "expected_count": 1}


# 独立固定验收与 Agent 崩溃窗口的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class VerifiedAgentTests(unittest.TestCase):
    # 独立固定验收与 Agent 崩溃窗口的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    @contextmanager
    def sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._owned_runtimes = []
            try:
                yield tmp
            finally:
                for runtime in reversed(self._owned_runtimes):
                    runtime.close()

    # 独立固定验收与 Agent 崩溃窗口的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def fixture(self, root, provider=None, **kwargs):
        source = root / "data.txt"
        source.write_bytes(b"\xef\xbb\xbffoo\r\nkeep bar\r\n")
        runtime = MythRuntime(root)
        agent = AgentRuntime(runtime)
        provider = provider or ScriptedPatchProvider()
        rid = agent.create_run(
            goal="replace foo with bar",
            provider=provider,
            model="test",
            allowed_files=(source,),
            acceptance=[rule(source)],
            **kwargs,
        )
        self._owned_runtimes.append(runtime)
        return source, runtime, agent, provider, rid

    # 回归断言：其他修改收据不能证明当前固定 Goal；验收需身份和字节同时匹配。
    def test_wrong_patch_receipt_cannot_prove_goal(self):
        # 独立固定验收与 Agent 崩溃窗口的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
        class Wrong(LoopProvider):
            # 按预定顺序返回模型夹具或注入异常；调用计数用于核对重放边界。
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

    # 回归断言：旧 Run 缺固定合同保持可检查，不能推断 PASS 后交付。
    def test_no_goal_contract_never_delivers(self):
        with self.sandbox() as tmp:
            root = Path(tmp)
            source = root / "data.txt"
            source.write_text("foo")
            with MythRuntime(root) as runtime:
                agent = AgentRuntime(runtime)
                provider = LoopProvider()
                rid = agent.create_run(
                    goal="some goal",
                    provider=provider,
                    model="test",
                    allowed_files=(source,),
                    max_steps=3,
                )
                self.assertIsNone(agent.run(rid, provider)["delivery"])

    # 回归断言：首个模型调用之前冻结原始基线，模型不能改写验收预期。
    def test_baseline_is_fixed_before_first_model_call(self):
        with self.sandbox() as tmp:
            source, runtime, agent, provider, rid = self.fixture(Path(tmp))
            source.write_text("external writer changed source", encoding="utf-8")
            status = agent.run(rid, provider)
            self.assertEqual(status["agent"]["status"], "SUCCEEDED")
            self.assertEqual(
                runtime.workspaces.path_for(rid, source.name).read_bytes(),
                b"\xef\xbb\xbfbar\r\nkeep bar\r\n",
            )
            self.assertEqual(source.read_text(), "external writer changed source")

    # 回归断言：全部声明文件都验收，未改文件也必须与固定基线一致。
    def test_multiple_files_and_preserved_file_are_verified(self):
        with self.sandbox() as tmp:
            root = Path(tmp)
            a = root / "a.txt"
            b = root / "b.txt"
            c = root / "keep.txt"
            a.write_text("foo")
            b.write_text("foo")
            c.write_text("unchanged")
            with MythRuntime(root) as runtime:
                agent = AgentRuntime(runtime)
                provider = ScriptedPatchProvider()
                rid = agent.create_run(
                    goal="replace in two files",
                    provider=provider,
                    model="test",
                    allowed_files=(a, b, c),
                    acceptance=[rule(a), rule(b)],
                    max_steps=8,
                )
                status = agent.run(rid, provider)
                self.assertEqual(status["agent"]["status"], "SUCCEEDED")
                self.assertEqual(len(status["tool_actions"]), 2)
                self.assertEqual(
                    runtime.workspaces.path_for(rid, c.name).read_text(), "unchanged"
                )

    # 回归断言：扁平受管名称冲突提前拒绝，避免不同源串到同目标。
    def test_duplicate_filenames_rejected_before_run(self):
        with self.sandbox() as tmp:
            root = Path(tmp)
            (root / "nested").mkdir()
            a = root / "same.txt"
            b = root / "nested" / "same.txt"
            a.write_text("foo")
            b.write_text("foo")
            with MythRuntime(root) as runtime:
                agent = AgentRuntime(runtime)
                with self.assertRaises(ValueError):
                    agent.create_run(
                        goal="edit",
                        provider=ScriptedPatchProvider(),
                        model="test",
                        allowed_files=(a, b),
                    )
                self.assertEqual(agent.list_runs(), [])

    # 回归断言：入口身份包含固定限制；相同意图复用，不同预算/步数冲突。
    def test_entry_deduplicates_and_conflicts_on_limits(self):
        with self.sandbox() as tmp:
            source, runtime, agent, provider, rid = self.fixture(
                Path(tmp), request_id="stable"
            )
            args = dict(
                goal="replace foo with bar",
                provider=provider,
                model="test",
                allowed_files=(source,),
                acceptance=[rule(source)],
                request_id="stable",
            )
            self.assertEqual(agent.create_run(**args), rid)
            with self.assertRaises(IdentityConflict):
                agent.create_run(**args, max_steps=7)
            self.assertEqual(len(agent.list_runs()), 1)

    # 回归断言：供应商已派发而结果不明时继续不重发。
    def test_unknown_provider_is_not_called_again_on_continue(self):
        # 独立固定验收与 Agent 崩溃窗口的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
        class Timeout(LoopProvider):
            calls = 0

            # 按预定顺序返回模型夹具或注入异常；调用计数用于核对重放边界。
            def invoke(self, request):
                self.calls += 1
                raise RuntimeError("remote result lost")

        with self.sandbox() as tmp:
            _, _, agent, provider, rid = self.fixture(Path(tmp), Timeout())
            self.assertEqual(agent.run(rid, provider)["agent"]["status"], "UNKNOWN")
            self.assertEqual(agent.run(rid, provider)["agent"]["status"], "UNKNOWN")
            self.assertEqual(provider.calls, 1)

    # 回归断言：实际收到非法输出仍计费；后续纠正使用新的规划步骤身份。
    def test_invalid_response_is_charged_and_next_step_uses_new_request(self):
        # 独立固定验收与 Agent 崩溃窗口的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
        class Repair(ScriptedPatchProvider):
            calls = 0

            # 按预定顺序返回模型夹具或注入异常；调用计数用于核对重放边界。
            def invoke(self, request):
                self.calls += 1
                if self.calls == 1:
                    return ModelResult(
                        "bad JSON",
                        {"model_calls": 1, "input_tokens": 2, "output_tokens": 3},
                        {"bad": True},
                    )
                return super().invoke(request)

        with self.sandbox() as tmp:
            _, _, agent, provider, rid = self.fixture(Path(tmp), Repair())
            status = agent.run(rid, provider)
            self.assertEqual(status["agent"]["status"], "SUCCEEDED")
            accounts = {a["meter"]: a for a in status["model"]["budgets"]}
            self.assertEqual(accounts["model_calls"]["settled"], 4)
            self.assertEqual(accounts["output_tokens"]["settled"], 3)

    # 回归断言：取消发生在模型在途窗口，新工具不能从晚到决定取得 Ticket。
    def test_cancel_during_model_call_cannot_start_tool(self):
        with self.sandbox() as tmp:
            _, _, agent, provider, rid = self.fixture(Path(tmp))
            original = provider.invoke

            # 按预定顺序返回模型夹具或注入异常；调用计数用于核对重放边界。
            def invoke(request):
                agent.cancel(rid)
                return original(request)

            with patch.object(provider, "invoke", side_effect=invoke):
                status = agent.run(rid, provider)
            self.assertEqual(status["agent"]["status"], "CANCELLED")
            self.assertEqual(status["tool_actions"], [])
            self.assertIsNone(status["delivery"])
            self.assertEqual(
                status["model"]["model_invocations"][0]["state"], "RESOLVED"
            )

    # 回归断言：回答需当前 question_id；重复/错身份消费拒绝。
    def test_answer_requires_current_question_and_is_consumed_once(self):
        with self.sandbox() as tmp:
            _, _, agent, provider, rid = self.fixture(Path(tmp), AskProvider())
            status = agent.run(rid, provider)
            question = status["agent"]["question_id"]
            with self.assertRaises(ValueError):
                agent.repository.answer(rid, "stale", "answer")
            self.assertEqual(agent.status(rid)["agent"]["status"], "WAITING_USER")
            agent.repository.answer(rid, question, "answer")
            with self.assertRaises(ValueError):
                agent.repository.answer(rid, question, "answer")

    # 回归断言：同 Run 两个本机执行器竞争物理锁，第二个不能并发驱动。
    def test_os_lock_rejects_second_local_driver(self):
        with self.sandbox() as tmp:
            _, _, agent, _, rid = self.fixture(Path(tmp))
            with agent.execution.lock(rid):
                with self.assertRaises(RecoveryRequired):
                    with agent.execution.lock(rid):
                        pass

    # 回归断言：有界上下文保留用户修正与证据引用，原始笔记不倒写。
    def test_context_keeps_corrections_and_references_without_rewriting_notes(self):
        notes = [
            {
                "sequence": i,
                "kind": "user" if i == 1 else "tool_result",
                "payload": (
                    {"text": "最新约束"}
                    if i == 1
                    else {
                        "preview": "x" * 5000,
                        "evidence_ref": f"ref-{i}",
                        "source_file": "a",
                    }
                ),
            }
            for i in range(1, 31)
        ]
        original = json.dumps(notes)
        value = json.loads(compile_context(notes, {"rules": []}))
        self.assertEqual(value["constraints"][0]["payload"]["text"], "最新约束")
        self.assertEqual(len(value["tool_evidence"]), 29)
        self.assertEqual(value["latest_tool_result"]["preview"], "x" * 5000)
        self.assertEqual(original, json.dumps(notes))
        with self.assertRaises(ContextBudgetError):
            compile_context(notes, {"rules": []}, max_bytes=5)
        with self.assertRaises(ContextBudgetError):
            compile_context([notes[-1]], {"rules": []}, max_bytes=1000)

    # 回归断言：未改文件漂移或仍有 remaining 都阻止精确用例交付。
    def test_untouched_file_and_remaining_work_block_completion(self):
        from myth.domain import sha256_bytes

        manifest = freeze_acceptance({"a": b"foo", "keep": b"unchanged"}, [rule("a")])
        current = {"a": sha256_bytes(b"bar"), "keep": sha256_bytes(b"tampered")}
        evidence = {
            "ref": {
                "source_file": "a",
                "after_digest": current["a"],
                "attempt_state": "RESOLVED",
                "outcome": "SUCCEEDED",
            }
        }
        self.assertEqual(
            verify_goal(manifest, current, evidence, ("ref",), ())[0].value, "FAIL"
        )
        current["keep"] = sha256_bytes(b"unchanged")
        self.assertEqual(
            verify_goal(manifest, current, evidence, ("ref",), ("not done",))[0].value,
            "INCONCLUSIVE",
        )

    # 回归断言：效果前取消可释放预留且禁止签发；与未知效果占用分开。
    def test_cancel_prepared_intent_releases_reservations_and_prevents_ticket(self):
        with self.sandbox() as tmp:
            source, runtime, agent, provider, rid = self.fixture(Path(tmp))
            prepared = runtime.prepare_patch_action(
                rid, source, old_text="foo", new_text="bar", expected_count=1
            )
            agent.cancel(rid)
            with self.assertRaises(RecoveryRequired):
                runtime.execute_patch_action(rid, action_id=prepared["action_id"])
            self.assertEqual(
                runtime.workspaces.path_for(rid, source.name).read_bytes(),
                b"\xef\xbb\xbffoo\r\nkeep bar\r\n",
            )
            self.assertEqual(
                runtime.store.db.execute(
                    "SELECT COUNT(*) FROM tickets JOIN attempts USING(attempt_id) WHERE run_id=?",
                    (rid,),
                ).fetchone()[0],
                0,
            )
            for account in runtime.store.get_accounts(rid):
                self.assertEqual(account["reserved"], 0)

    # 回归断言：必需请求过大在模型 Ticket 前失败，不静默截掉约束。
    def test_oversized_full_model_request_stops_before_model_ticket(self):
        with self.sandbox() as tmp:
            _, _, agent, provider, rid = self.fixture(Path(tmp))
            agent.runtime.store.db.execute(
                "UPDATE runs SET goal=? WHERE run_id=?", ("x" * 70000, rid)
            )
            status = agent.run(rid, provider)
            self.assertEqual(status["agent"]["status"], "FAILED")
            self.assertEqual(status["model"]["model_invocations"], [])

    # 回归断言：晚到模型收据解除对应未知占用，重复核对不重复扣费。
    def test_late_model_receipt_settles_unknown_hold_once(self):
        with self.sandbox() as tmp:
            _, runtime, agent, provider, rid = self.fixture(Path(tmp))
            step = agent.repository.begin_step(rid)
            decisions = agent.repository.decisions
            original = decisions._settle

            # 独立固定验收与 Agent 崩溃窗口的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
            def interrupt(attempt_id, receipt):
                decisions._mark_unknown(attempt_id, "interrupted before settle")
                raise RuntimeError("interrupted")

            with patch.object(decisions, "_settle", side_effect=interrupt):
                with self.assertRaises(RuntimeError):
                    agent.execution.request_decision(
                        rid,
                        step["step"],
                        provider,
                        compile_context(
                            agent.repository.notes(rid), agent.repository.manifest(rid)
                        ),
                    )
            decisions.recover(rid)
            decisions.recover(rid)
            status = agent.run(rid, provider)
            self.assertEqual(status["agent"]["status"], "SUCCEEDED")
            for account in runtime.store.get_accounts(rid):
                self.assertEqual(account["reserved"], 0)
                self.assertEqual(account["unknown_held"], 0)


# 独立固定验收与 Agent 崩溃窗口的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class AgentHardCrashTests(unittest.TestCase):
    # 独立固定验收与 Agent 崩溃窗口的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def hard_crash(self, boundary):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "data.txt"
            source.write_bytes(b"foo\r\n")
            provider = ScriptedPatchProvider()
            with MythRuntime(root) as runtime:
                rid = AgentRuntime(runtime).create_run(
                    goal="replace",
                    provider=provider,
                    model="test",
                    allowed_files=(source,),
                    acceptance=[rule(source)],
                )
            hook = (
                "agent.repository.bind_decision = lambda *args: os._exit(93)"
                if boundary == "model"
                else (
                    "original=agent.execution.execute\n"
                    "def execute(*args):\n"
                    "    result=original(*args)\n"
                    "    if args[-1].capability_id=='file.patch_exact': os._exit(94)\n"
                    "    return result\n"
                    "agent.execution.execute=execute"
                )
            )
            script = f"import os\nfrom myth.runtime import MythRuntime\nfrom myth.agent_runtime import AgentRuntime\nfrom myth.providers.scripted import ScriptedPatchProvider\nruntime=MythRuntime({str(root)!r})\nagent=AgentRuntime(runtime)\n{hook}\nagent.run({rid!r},ScriptedPatchProvider())"
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            child = subprocess.run(
                [sys.executable, "-c", script], env=env, capture_output=True, timeout=15
            )
            self.assertEqual(
                child.returncode, 93 if boundary == "model" else 94, child.stderr
            )
            with MythRuntime(root) as runtime:
                agent = AgentRuntime(runtime)
                status = agent.run(rid, provider)
                self.assertEqual(status["agent"]["status"], "SUCCEEDED")
                self.assertEqual(len(status["tool_actions"]), 1)
                accounts = {a["meter"]: a for a in status["model"]["budgets"]}
                self.assertEqual(accounts["model_calls"]["settled"], 3)
                self.assertEqual(accounts["tool_calls"]["settled"], 2)
                self.assertEqual(
                    runtime.workspaces.path_for(rid, "data.txt").read_bytes(),
                    b"bar\r\n",
                )
                self.assertEqual(
                    runtime.store.db.execute(
                        "SELECT COUNT(*) FROM deliveries WHERE run_id=?", (rid,)
                    ).fetchone()[0],
                    0,
                )

    # 回归断言：模型收据后重开复用原请求结果，避免重复成本。
    def test_restart_after_model_receipt_does_not_call_model_again(self):
        self.hard_crash("model")

    # 回归断言：已结算修改后重开复用工具绑定，不重复应用替换。
    def test_restart_after_patch_settle_does_not_repeat_patch(self):
        self.hard_crash("tool")
