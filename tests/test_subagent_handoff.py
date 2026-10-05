"""共享子引擎与交接的语义/故障回归。

真实仓储、Ticket 和 Context 编译器配合可控 Provider；断言固定内容、隔离、费用与
恢复事实，不用替身通过推断远端质量。主评分仍明确是模型判断而非独立 Verification。
"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.domain import ExecutionDeferred, IdentityConflict, SimulatedCrash
from myth.models import ModelResult, ProviderUnavailable
from myth.platform.control import ControlCommand
from myth.platform.handoff import project_handoffs
from myth.platform.model_pool import clean_pool, profile_key, route, pending_resolutions
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


def complete(content, summary):
    """单独提供正文和摘要，证明不会把截断片段冒充模型语义摘要。"""
    value = json.loads(decision(claim=content))
    value["summary"] = summary
    return json.dumps(value, ensure_ascii=False)


class RichProvider(ChatProvider):
    """真实模型端口返回新增公开计量和私有字段，测试投影保留/排除界限。"""

    def invoke(self, request):
        """可控正文与固定新增元数据；耗时由生产 Runtime 实测。"""
        result = super().invoke(request)
        return ModelResult(result.text, result.usage, {"id": "response-fixture", "model": request.model,
            "usage": {"input_tokens": 20, "output_tokens": 30, "input_tokens_details": {"cached_tokens": 7},
                "output_tokens_details": {"reasoning_tokens": 11}, "future_stat": {"batch": 2}},
            "created_at": 123, "billing": {"currency": "USD", "provider_amount": 0.02},
            "future_details": {"long_stat": "M" * 5100, "attempt_tags": list(range(125))},
            "reasoning_content": "PRIVATE-REASONING", "api_key": "PRIVATE-KEY", "text": result.text}, "response-fixture")


class SubagentHandoffTests(unittest.TestCase):
    """每例以实际父决定准入，子计划使用同一父预算而不是绕过 Runtime 的直接调用。"""

    def setUp(self):
        """创建独立工作区；父秘密用于核对没有继承主历史。"""
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.temp.name))
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "parent", "max_steps": 24,
            "model_pool": {"main_pricing": {"currency": "USD", "input": 1, "output": 2}, "children": [
                {"id": "slot", "provider": "ollama", "model": "worker", "tier": 3,
                 "max_steps": 4, "pricing": {"currency": "USD", "input": 1, "output": 2}}]}})
        self.rid = self.repo.create_turn(self.repo.create_session()["id"], "PARENT-ONLY-SECRET", "handoff") ["run_id"]

    def tearDown(self):
        """停止本例仓储再清理文件；不使用用户账号或已有 Runtime。"""
        self.runtime.close()
        self.temp.cleanup()

    def act(self, capability, args, child=None):
        """产生真实父模型决定并走生产工具准入；不伪造决定 ID。"""
        step = self.repo.begin_step(self.rid)["step"]
        parent = ChatProvider([decision("tool_call", capability, args)])
        did, proposal = self.workspace.execution.decide(self.repo.turn(self.rid), step, parent)
        self.repo.bind(self.rid, step, did, proposal)
        result = self.workspace.execution.execute(self.repo.turn(self.rid), did, proposal, provider=child)
        self.repo.finish_tool(self.rid, step, result)
        return result

    def delegate(self, child=None, **args):
        """派发一个明确输入的子任务，返回已结算的固定信封。"""
        return self.act("agent.delegate", {"task": "核对给定事实", "context": "FACT=A", **args}, child or ChatProvider())

    def review(self, result, accepted=True, metadata="accepted", tier=3):
        """主模型分别评判内容和元数据；独立绑定报告摘要。"""
        return self.act("agent.evaluate", {"delegation_id": result["delegation_id"], "correctness": 90 if accepted else 30,
            "completeness": 90 if accepted else 30, "usefulness": 90 if accepted else 30,
            "accepted": accepted, "failure_kind": "none" if accepted else "quality", "reason": "固定事实核对",
            "capability_tier": tier, "metadata_verdict": metadata, "metadata_digest": result["telemetry"]["report_digest"]})

    def graph(self):
        """只从已有父子调用和收据投影图，费用不得由 fixture 文本推断。"""
        return self.workspace.components.observability.execution_graph(run_id=self.rid, status=self.repo.turn(self.rid)["status"],
            model_state=self.repo.decisions.status(self.rid), operations=self.repo.operations(self.rid),
            main_pricing=self.repo.turn(self.rid)["settings"]["model_pool"]["main_pricing"])

    def test_large_result_keeps_full_object_and_pages_exact_text(self):
        """大正文不上默认上下文；分页保留尾部，不截断权威结果，跨 Run 与版本错配拒绝。"""
        content = "正文资料。" * 1800 + "TAIL-FACT"
        result = self.delegate(ChatProvider([complete(content, "已核对正文，尾部含 TAIL-FACT")]))
        self.assertLessEqual(len(result["summary"]), 1200)
        self.assertEqual(result["summary_kind"], "model_summary")
        self.assertNotIn(content, json.dumps(result))
        self.assertEqual(self.runtime.objects.get(result["handoff"]["content_ref"]).decode(), content)
        recalled = ""
        for offset in range(0, len(content), 3000):
            page = self.workspace.execution.delegation.read_result(self.repo.turn(self.rid), {
                "delegation_id": result["delegation_id"], "field": "content", "offset": offset, "max_chars": 3000,
                "expected_digest": result["handoff"]["content_digest"]})
            recalled += page["content"]
        self.assertEqual(recalled, content)
        with self.assertRaises(ValueError):
            self.workspace.execution.delegation.read_result(self.repo.turn(self.rid), {
                "delegation_id": result["delegation_id"], "field": "content", "expected_digest": "stale"})
        other = self.repo.create_turn(self.repo.create_session()["id"], "其他任务", "other")["run_id"]
        with self.assertRaises(ValueError):
            self.workspace.execution.delegation.read_result(self.repo.turn(other), {"delegation_id": result["delegation_id"]})

    def test_no_summary_is_honest_excerpt(self):
        """旧形式/无摘要正文仍完整存储；片段明确标注，不能宣称摘要包含所有细节。"""
        result = self.delegate(ChatProvider([decision(claim="长文本" * 1000)]))
        self.assertEqual(result["summary_kind"], "exact_excerpt")
        self.assertFalse(result["handoff"]["summary_is_full_content"])

    def test_multi_step_input_read_uses_shared_engine_and_budget(self):
        """第二页输入确实进入子观察；全部子调用/输入工具映射到父账本且父秘密不泄露。"""
        child = ChatProvider([decision("tool_call", "input.read", {"offset": 800, "max_chars": 600}), complete("FACT=TAIL", "FACT=TAIL")])
        result = self.delegate(child, context="x" * 800 + "FACT=TAIL")
        self.assertEqual(result["subagent"]["steps_used"], 2)
        self.assertEqual(len(result["telemetry"]["attempt_ids"]), 2)
        self.assertEqual(result["telemetry"]["cost"]["amount"], 0.00016)
        first = "\n".join(x.content for x in child.calls[0].messages)
        second = "\n".join(x.content for x in child.calls[1].messages)
        self.assertNotIn("PARENT-ONLY-SECRET", first + second)
        self.assertNotIn("FACT=TAIL", first)
        self.assertIn("FACT=TAIL", second)
        graph = self.graph()
        self.assertEqual(graph["coverage"]["unmapped_model_calls"], 0)
        self.assertEqual(sum(x["kind"] == "subagent" for x in graph["nodes"]), 2)
        self.assertTrue(any(x.get("label") == "input.read" for x in graph["nodes"]))

    def test_rich_provider_metadata_preserved_without_private_fields(self):
        """厂商新增统计和原始缓存结构交由主处理，私有思维/凭据不在交接元数据。"""
        result = self.delegate(RichProvider())
        page = self.workspace.execution.delegation.read_result(self.repo.turn(self.rid), {"delegation_id": result["delegation_id"], "field": "metadata", "max_chars": 6000})
        text = page["content"]
        while page["has_more"]:
            page = self.workspace.execution.delegation.read_result(self.repo.turn(self.rid), {
                "delegation_id": result["delegation_id"], "field": "metadata", "offset": page["next_offset"], "max_chars": 6000})
            text += page["content"]
        report = json.loads(text)["calls"][0]["provider_metadata"]
        self.assertEqual(report["usage"]["future_stat"]["batch"], 2)
        self.assertEqual(report["usage"]["output_tokens_details"]["reasoning_tokens"], 11)
        self.assertEqual(report["billing"]["provider_amount"], 0.02)
        self.assertEqual(len(report["future_details"]["long_stat"]), 5100)
        self.assertEqual(len(report["future_details"]["attempt_tags"]), 125)
        self.assertNotIn("PRIVATE-", text)

    def test_metadata_review_separate_from_content_and_spend(self):
        """内容拒收仍计钱；争议报告不进入审核金额，但全部原调用费用保留。"""
        result = self.delegate()
        before = self.graph()["cost_summary"]
        self.assertEqual(before["pending_by_currency"]["USD"], 0.00008)
        self.review(result, accepted=False, metadata="disputed")
        after = self.graph()["cost_summary"]
        self.assertEqual(after["disputed_by_currency"]["USD"], 0.00008)
        self.assertEqual(after["estimated_by_currency"]["USD"], 0.00024)
        projected = project_handoffs(self.repo.turn(self.rid)["activities"])
        self.assertEqual(projected[0]["result"]["adoption"], "rejected")
        self.assertNotIn("这是回答", projected[0]["result"]["summary"])
        self.assertEqual(pending_resolutions(self.repo.turn(self.rid)["activities"]), [result["delegation_id"]])
        self.act("agent.resolve", {"delegation_id": result["delegation_id"], "content": "主模型独立补做：FACT=A"})
        self.assertEqual(pending_resolutions(self.repo.turn(self.rid)["activities"]), [])

    def test_review_requires_explicit_capability_and_matching_metadata(self):
        """主意见必须显式给出，不能由 Runtime 自动采信或套用旧报告。"""
        result = self.delegate()
        args = {"delegation_id": result["delegation_id"], "correctness": 90, "completeness": 90, "usefulness": 90,
            "accepted": True, "failure_kind": "none", "reason": "核对", "capability_tier": 3}
        with self.assertRaises(ValueError):
            self.workspace.execution.delegation.evaluate(self.repo.turn(self.rid), args)
        with self.assertRaises(ValueError):
            self.workspace.execution.delegation.evaluate(self.repo.turn(self.rid), {**args, "metadata_verdict": "accepted", "metadata_digest": "wrong"})

    def test_dependencies_require_accepted_result_and_order_is_stable(self):
        """父消费顺序单调，未评审结果不能成为依赖；输入/输出身份属于固定任务。"""
        first = self.delegate()
        with self.assertRaises(ValueError):
            self.workspace.execution.delegation.delegate(self.repo.turn(self.rid), "not-admitted", {"task": "后续", "depends_on": [first["delegation_id"]]}, ChatProvider())
        self.review(first)
        second = self.delegate(depends_on=[first["delegation_id"]])
        self.assertGreater(second["handoff"]["sequence"], first["handoff"]["sequence"])
        self.assertEqual(second["handoff"]["depends_on"], [first["delegation_id"]])
        self.assertTrue(any(x["kind"] == "dependency" for x in self.graph()["edges"]))

    def test_rejected_task_can_be_replaced_by_another_equally_strong_slot(self):
        """三个强模型无需人为角色或严格升级；同类失败避开旧槽位，采纳替代后解除缺口。"""
        self.repo.save_settings({**self.repo.settings(), "model_pool": {"children": [
            {"id": "slot", "provider": "ollama", "model": "worker", "tier": 3},
            {"id": "other", "provider": "ollama", "model": "other-worker", "tier": 3}]}})
        # Turn 已冻结原池，另准入一轮取用用户新配置。
        self.rid = self.repo.create_turn(self.repo.create_session()["id"], "任务", "replacement")["run_id"]
        first = self.delegate(profile_id="slot")
        self.review(first, accepted=False)
        second = self.delegate(replaces=first["delegation_id"])
        self.assertEqual(second["routing"]["profile"]["id"], "other")
        self.review(second)
        self.assertEqual(pending_resolutions(self.repo.turn(self.rid)["activities"]), [])
        self.assertTrue(any(x["kind"] == "replacement" for x in self.graph()["edges"]))

    def test_main_judgment_can_override_initial_tier(self):
        """明确选槽位可检验低初值模型，主模型能力判断用于后续同类更难任务。"""
        pool = clean_pool({"children": [{"id": "s", "provider": "ollama", "model": "worker", "tier": 1}]})
        self.assertIsNone(route(pool, "reason", "hard", []) ["profile"])
        self.assertEqual(route(pool, "reason", "hard", [], preferred_profile_id="s")["profile"]["id"], "s")
        history = [{"profile_key": profile_key(pool["children"][0]), "task_type": "reason", "difficulty": "easy",
                    "accepted": True, "failure_kind": "none", "score": 95, "capability_tier": 3}]
        self.assertEqual(route(pool, "reason", "hard", history)["profile"]["id"], "s")

    def test_reconnect_reuses_fixed_child_cursor_and_preserves_zero_attempt(self):
        """明确零派发的重试保持同合同；核对不请求 Provider，图包含零派发及成功两份收据。"""
        child = ChatProvider([complete("成功", "成功")])
        with patch.object(child, "invoke", side_effect=ProviderUnavailable()):
            with self.assertRaises(ProviderUnavailable):
                self.delegate(child)
        op = self.repo.operations(self.rid)[0]
        self.assertTrue(self.workspace.execution.recover(self.rid))
        proposal = self.repo.turn(self.rid)["activities"][0]
        from myth.models import StepDecision
        result = self.workspace.execution.execute(self.repo.turn(self.rid), op["decision_id"], StepDecision(**proposal["decision"]), provider=child)
        self.assertEqual(result["summary"], "成功")
        self.assertEqual(len(child.calls), 1)
        self.assertEqual(len(result["telemetry"]["attempt_ids"]), 2)
        self.assertEqual(result["telemetry"]["cost"]["amount"], 0.00008)
        self.assertEqual(self.graph()["coverage"]["unmapped_model_calls"], 0)

    def test_compact_uses_same_context_compiler_without_parent_history(self):
        """Compact 版本传到子 Context 报告，子消费不能清除父自己仍需处理的压缩义务。"""
        self.workspace.control.command(self.rid, ControlCommand.COMPACT)
        result = self.delegate(ChatProvider([complete("结果", "结果")]))
        state = self.repo.delegation_state(result["delegation_id"])
        self.assertTrue(state["last_context_report"]["compact_requested"])
        self.assertEqual(state["compact_revision"], state["last_context_report"]["control_revision"])
        self.assertTrue(self.workspace.control.view(self.rid)["compact_requested"])

    def test_checkpoint_cas_rejects_stale_driver(self):
        """恢复游标写入须核对版本，旧 Driver 不能覆盖新状态。"""
        original = self.repo.decisions.request_decision
        def crash_child(**args):
            """只在真实父准入后的子请求边界注入退出。"""
            if str(args.get("request_key", "")).startswith("subagent:"):
                raise SimulatedCrash()
            return original(**args)
        with patch.object(self.repo.decisions, "request_decision", side_effect=crash_child):
            with self.assertRaises(SimulatedCrash):
                self.delegate()
        op = self.repo.operations(self.rid)[0]
        state = self.repo.delegation_state(op["decision_id"])
        self.repo.checkpoint_delegation(op["decision_id"], state, expected_revision=state["revision"])
        with self.assertRaises(IdentityConflict):
            self.repo.checkpoint_delegation(op["decision_id"], state, expected_revision=state["revision"])

    def test_pause_after_child_receipt_resumes_without_repeating_model(self):
        """Pause 不撤销已发生花销；Resume 复用已绑定子决定，不再请求远端。"""
        child = ChatProvider([complete("已完成", "已完成")])
        original = child.invoke
        def pause_after_response(request):
            """在实际子调用返回时提交父 Pause，制造迟到安全点窗口。"""
            response = original(request)
            self.workspace.control.command(self.rid, ControlCommand.PAUSE)
            return response
        with patch.object(child, "invoke", side_effect=pause_after_response):
            with self.assertRaises(ExecutionDeferred):
                self.delegate(child)
        op = self.repo.operations(self.rid)[0]
        self.assertEqual(self.repo.delegation_state(op["decision_id"])["status"], "PAUSED")
        self.assertEqual(self.workspace.execution.delegation.telemetry(op["intent"]["delegate"])["cost"]["amount"], 0.00008)
        self.workspace.control.command(self.rid, ControlCommand.RESUME)
        from myth.models import StepDecision
        result = self.workspace.execution.execute(self.repo.turn(self.rid), op["decision_id"],
            StepDecision(**self.repo.turn(self.rid)["activities"][0]["decision"]), provider=child)
        self.assertEqual(result["summary"], "已完成")
        self.assertEqual(len(child.calls), 1)

    def test_crash_before_second_bind_recovers_entire_child_without_provider(self):
        """多步子请求最后收据已写而游标未绑定；重启仅消费原事实，图仍完整。"""
        from myth.adapters.subagent_runtime import SubagentRepository
        child = ChatProvider([decision("tool_call", "input.read", {"offset": 0, "max_chars": 20}), complete("结果", "结果")])
        bind = SubagentRepository.bind
        def crash_second(repository, run_id, step, decision_id, proposal):
            """只在第二步模型收据之后、子游标绑定之前退出。"""
            if step == 2:
                raise SimulatedCrash()
            return bind(repository, run_id, step, decision_id, proposal)
        with patch.object(SubagentRepository, "bind", new=crash_second):
            with self.assertRaises(SimulatedCrash):
                self.delegate(child)
        op = self.repo.operations(self.rid)[0]
        self.assertTrue(self.workspace.execution.recover(self.rid))
        self.assertEqual(self.repo.operation(op["decision_id"])["result"]["summary"], "结果")
        self.assertEqual(len(child.calls), 2)
        self.assertEqual(self.graph()["coverage"]["unmapped_model_calls"], 0)
