"""模型池端到端合同与故障回归。

通过真实 SQLite/Runtime/Conversation 验证路由、计量、评分与恢复；可控 Provider
隔离网络，不能据本文件的通过宣称真实远端模型的语义质量或计费准确性。
"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.models import ProviderKnownFailure, ProviderUnavailable
from myth.domain import RecoveryRequired, SimulatedCrash
from myth.platform.model_pool import clean_pool, route, profile_key, estimate_cost
from test_workspace import ChatProvider, decision


def child_profile(pid="small", tier=1, **extra):
    """显式测试模型配置，单价只是固定断言输入，不是供应商报价。"""
    return {"id": pid, "provider": "kimi", "model": pid, "tier": tier,
            "pricing": {"currency": "USD", "input": 1, "output": 2}, **extra}


class ParentProvider(ChatProvider):
    """根据已结算子任务 ID 产生主模型评分，避免伪造持久身份。"""

    def __init__(self, repository, rid, score=90, failure_kind=None):
        """测试中主模型独立于子模型实例；评分读取实际子结果身份。"""
        super().__init__()
        self.repository, self.rid, self.score = repository, rid, score
        self.failure_kind = failure_kind or ("none" if score >= 70 else "quality")

    def invoke(self, request):
        """先派发，再评分，再汇总；回退结果直接由主模型接手。"""
        if not self.calls:
            output = decision("tool_call", "agent.delegate", {"task": "提取 FACT=A", "context": "FACT=A", "task_type": "extract", "difficulty": "easy"})
        else:
            ops = self.repository.operations(self.rid)
            target = next((x for x in ops if (x.get("result") or {}).get("review_required")), None)
            if target and not any(x["capability"] == "agent.evaluate" for x in ops):
                failed = bool(target["result"].get("fallback_to_parent"))
                output = decision("tool_call", "agent.evaluate", {
                    "delegation_id": target["decision_id"], "correctness": self.score, "completeness": self.score,
                    "usefulness": self.score, "accepted": self.score >= 70 and not failed,
                    "failure_kind": "infrastructure" if failed else self.failure_kind,
                    "capability_tier": target["result"]["routing"]["profile"]["tier"],
                    "metadata_verdict": "accepted", "metadata_digest": target["result"]["telemetry"]["report_digest"],
                    "reason": "根据 FACT=A 与预期结果核对"})
            elif target and any(not (x.get("result") or {}).get("review", {}).get("accepted", True) for x in ops) and not any(x["capability"] == "agent.resolve" for x in ops):
                output = decision("tool_call", "agent.resolve", {"delegation_id": target["decision_id"], "content": "主模型独立核对 FACT=A", "evidence_refs": []})
            else:
                output = decision(claim="主模型完成并汇总")
        self.outputs = [output] * (len(self.calls) + 1)
        return super().invoke(request)


class ModelPoolTests(unittest.TestCase):
    """跨提供方协作、评分经验及缺测语义以实际仓储结果断言。"""

    def setUp(self):
        """每例使用新 Runtime 与两个独立 Provider 实例。"""
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = MythRuntime(self.root)
        self.child = ChatProvider([decision(claim="FACT=A")])
        self.child.provider_id = "kimi"
        self.workspace = Workspace(self.runtime, child_provider_factory=lambda profile: self.child)
        self.repo = self.workspace.repository
        self.configure([child_profile(), child_profile("large", 3)])

    def configure(self, profiles):
        """通过生产设置入口保存配置，不能直接修改 Turn 快照。"""
        return self.repo.save_settings({"provider": "ollama", "model": "parent", "model_pool": {
            "children": profiles, "main_pricing": {"currency": "USD", "input": 3, "output": 4}}})

    def tearDown(self):
        """关闭连接后删除本例临时状态。"""
        self.runtime.close()
        self.temp.cleanup()

    def run_task(self, score=90, failure_kind=None):
        """正常准入一个任务并跑完真实用例循环。"""
        sid = self.repo.create_session()["id"]
        rid = self.repo.create_turn(sid, "请提取给定事实", "pool-task-" + sid)["run_id"]
        parent = ParentProvider(self.repo, rid, score, failure_kind)
        self.workspace.run(rid, parent)
        return rid, parent

    def test_cross_provider_feedback_graph_and_cost(self):
        """四次模型调用含评分，总价不重复计父工具；图含供应商和评分回边。"""
        rid, parent = self.run_task()
        self.assertEqual(self.repo.turn(rid)["status"], "COMPLETED")
        self.assertEqual(len(parent.calls), 3)
        self.assertEqual(len(self.child.calls), 1)
        result = self.repo.operations(rid)[0]["result"]
        self.assertEqual(result["telemetry"]["provider"], "kimi")
        self.assertEqual(result["telemetry"]["cost"]["amount"], 0.00008)
        self.assertIsInstance(result["telemetry"]["provider_wall_ms"], int)
        feedback = self.repo.model_feedback()
        self.assertEqual(feedback[0]["score"], 90)
        self.assertEqual(feedback[0]["evidence_level"], "model_judgment")
        graph = self.workspace.components.observability.execution_graph(run_id=rid, status="COMPLETED",
            model_state=self.repo.decisions.status(rid), operations=self.repo.operations(rid),
            main_pricing=self.repo.turn(rid)["settings"]["model_pool"]["main_pricing"])
        self.assertEqual(graph["cost_summary"]["estimated_by_currency"]["USD"], 0.00062)
        self.assertEqual(graph["cost_summary"]["unknown_calls"], 0)
        self.assertTrue(any(x["kind"] == "review" for x in graph["edges"]))

    def test_quality_failure_promotes_next_similar_task_after_restart(self):
        """低质量反馈跨重启保留，下一个同类任务选择更高档配置。"""
        self.run_task(score=45)
        self.runtime.close()
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime, child_provider_factory=lambda profile: self.child)
        self.repo = self.workspace.repository
        rid, _ = self.run_task()
        self.assertEqual(self.repo.operations(rid)[0]["result"]["routing"]["profile"]["id"], "large")
        self.assertEqual([r.model for r in self.child.calls], ["small", "large"])

    def test_context_failure_does_not_claim_model_incapability(self):
        """上下文不足的低评分不抬高同类任务的能力门槛。"""
        self.run_task(score=45, failure_kind="context")
        rid, _ = self.run_task()
        self.assertEqual(self.repo.operations(rid)[0]["result"]["routing"]["profile"]["id"], "small")

    def test_empty_pool_falls_back_without_child_spend(self):
        """模型池为空时主模型接手，不偷偷用主模型再生成一个子请求。"""
        self.configure([])
        rid, parent = self.run_task()
        self.assertEqual(self.repo.turn(rid)["status"], "COMPLETED")
        self.assertEqual(len(parent.calls), 2)
        self.assertEqual(self.child.calls, [])
        self.assertTrue(self.repo.operations(rid)[0]["result"]["fallback_to_parent"])

    def test_known_provider_failure_falls_back_but_unknown_never_replays(self):
        """明确失败可接手；超时无收据必须保持 UNKNOWN，重启核对不能再次派发。"""
        with patch.object(self.child, "invoke", side_effect=ProviderKnownFailure("offline", usage={"model_calls": 0})):
            rid, _ = self.run_task()
        self.assertEqual(self.repo.turn(rid)["status"], "COMPLETED")
        self.assertTrue(self.repo.operations(rid)[0]["result"]["fallback_to_parent"])
        with patch.object(self.child, "invoke", side_effect=TimeoutError()) as invoke:
            rid, _ = self.run_task()
            self.assertEqual(self.repo.turn(rid)["status"], "UNKNOWN")
            self.assertFalse(self.workspace.execution.recover(rid))
            self.assertEqual(invoke.call_count, 1)

    def test_zero_dispatch_receipt_keeps_child_identity_and_zero_cost(self):
        """零派发允许释放活动去重键，但图和返回元数据仍须归属子模型且保留实测零。"""
        with patch.object(self.child, "invoke", side_effect=ProviderUnavailable()):
            rid, _ = self.run_task()
        self.assertEqual(self.repo.turn(rid)["status"], "INTERRUPTED")
        op = self.repo.operations(rid)[0]
        self.assertIsNone(op["result"])
        telemetry = self.workspace.execution.delegation.telemetry(op["intent"]["delegate"])
        self.assertEqual(telemetry["usage"]["model_calls"], 0)
        self.assertEqual(telemetry["cost"]["amount"], 0)
        calls = self.repo.decisions.status(rid)["model_invocations"]
        self.assertEqual(sum(str(x.get("request_key") or "").startswith("subagent:") for x in calls), 1)

    def test_settings_frozen_and_changed_model_has_separate_history(self):
        """执行中的子配置不跟随设置页变化；换模型不继承旧评分。"""
        sid = self.repo.create_session()["id"]
        rid = self.repo.create_turn(sid, "任务", "frozen")["run_id"]
        self.configure([child_profile("replacement", 3)])
        self.workspace.run(rid, ParentProvider(self.repo, rid))
        self.assertEqual(self.child.calls[0].model, "small")
        self.assertNotEqual(profile_key(child_profile()), profile_key(child_profile(model="new-model")))

    def test_validation_and_missing_cost(self):
        """拒绝第四槽位和秘密字段；缺失用量不是零费用，非法数值不能持久化。"""
        with self.assertRaises(ValueError):
            clean_pool({"children": [child_profile(str(i)) for i in range(4)]})
        with self.assertRaises(ValueError):
            clean_pool({"children": [child_profile(api_key="secret")]})
        with self.assertRaises(ValueError):
            clean_pool({"main_pricing": {"input": float("nan"), "output": 1}})
        self.assertIsNone(estimate_cost({"input_tokens": 20}, {"input": 1, "output": 2, "currency": "USD"})["amount"])

    def test_failed_models_allow_another_candidate_and_disabled_learning_is_static(self):
        """避开同类失败配置后仍可尝试未失败候选；关闭学习使用初值档位。"""
        pool = clean_pool({"children": [child_profile(), child_profile("medium", 2), child_profile("large", 3)]})
        history = [{"profile_key": profile_key(p), "task_type": "extract", "difficulty": "easy",
                    "failure_kind": "quality", "accepted": False, "score": 40} for p in (pool["children"][0], pool["children"][2])]
        self.assertEqual(route(pool, "extract", "easy", history)["profile"]["id"], "medium")
        pool["adaptive"] = False
        self.assertEqual(route(pool, "extract", "easy", history)["profile"]["id"], "small")

    def test_score_rejects_foreign_run_and_duplicate_feedback(self):
        """真实评分不能被另一个 Run 引用，重复评分在 Ticket 事务内拒绝。"""
        rid = self.repo.create_turn(self.repo.create_session()["id"], "任务", "duplicate-score")["run_id"]
        with patch.object(self.repo, "finish_reply", side_effect=SimulatedCrash()):
            with self.assertRaises(SimulatedCrash):
                self.workspace.run(rid, ParentProvider(self.repo, rid))
        operations = self.repo.operations(rid)
        child_id = operations[0]["decision_id"]
        args = {"delegation_id": child_id, "correctness": 90, "completeness": 90, "usefulness": 90,
                "accepted": True, "failure_kind": "none", "reason": "再次评价"}
        other = self.repo.create_turn(self.repo.create_session()["id"], "另一个任务", "other-run")["run_id"]
        with self.assertRaises(ValueError):
            self.workspace.execution._evaluate_delegate(self.repo.turn(other), args)
        self.assertEqual(self.repo.turn(rid)["status"], "RUNNING")
        # 相同 Run 在继续运行时也不能生成第二份评分，重复核对发生在 Ticket 事务内。
        with self.assertRaisesRegex(ValueError, "已经评分"):
            self.repo.start_operation(rid, "new-review", "agent.evaluate", operations[1]["intent"])
        self.assertEqual(len(self.repo.model_feedback()), 1)

    def test_crash_after_cross_provider_receipt_preserves_metadata(self):
        """子收据已写、父收据未写时重启，只还原原配置/费用，不请求另一家模型。"""
        sid = self.repo.create_session()["id"]
        rid = self.repo.create_turn(sid, "任务", "receipt-crash")["run_id"]
        parent = ParentProvider(self.repo, rid)
        with patch.object(self.workspace.execution, "_record_tool_receipt", side_effect=SimulatedCrash()):
            with self.assertRaises(SimulatedCrash):
                self.workspace.run(rid, parent)
        self.runtime.close()
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime, child_provider_factory=lambda profile: self.fail("恢复不能调用 Provider"))
        self.repo = self.workspace.repository
        self.assertTrue(self.workspace.execution.recover(rid))
        result = self.repo.operations(rid)[0]["result"]
        self.assertEqual(result["telemetry"]["cost"]["amount"], 0.00008)
        self.assertEqual(result["telemetry"]["model"], "small")
        self.assertEqual(len(self.child.calls), 1)

    def test_unrated_child_prevents_completion(self):
        """主模型跳过评分时完成守卫拒绝停止，不把未评分结果写进经验。"""
        sid = self.repo.create_session()["id"]
        rid = self.repo.create_turn(sid, "任务", "unrated")["run_id"]
        provider = ChatProvider([decision("tool_call", "agent.delegate", {"task": "任务", "difficulty": "easy"}), decision()])
        self.workspace.run(rid, provider)
        self.assertNotEqual(self.repo.turn(rid)["status"], "COMPLETED")
        self.assertEqual(self.repo.model_feedback(), [])
        self.assertTrue(any((x.get("result") or {}).get("error") for x in self.repo.turn(rid)["activities"]))
