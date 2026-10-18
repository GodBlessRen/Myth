"""Context Governance 纯策略与真实 Conversation 编译回归。"""

import unittest
from pathlib import Path
import tempfile

from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.web_workspace import ConversationWebService

from myth.acceptance import ContextBudgetError
from myth.conversation import conversation_request
from myth.platform.context_governance import build_causal_guard, lexical_relevance
from myth.model_capabilities import remote_context_budget


SETTINGS = {
    "provider": "ollama", "model": "test", "max_output_tokens": 512,
    "num_ctx": 8192, "temperature": 0.0,
}


class ContextGovernanceTests(unittest.TestCase):
    """验证因果状态不会被相关性、预算或来源推测静默覆盖。"""

    def test_causal_guard_only_uses_reported_status_and_explicit_edges(self):
        """仅已记录关键结果与显式依赖进入保护链；未记录关系保持缺失。"""
        activities = [
            {"step": 1, "decision_id": "prepare", "capability": "project.read",
             "result": {"content": "input"}},
            {"step": 2, "decision_id": "write", "capability": "artifact.write",
             "declared_dependencies": ["prepare", "missing-op"],
             "result": {"status": "UNKNOWN", "evidence_ref": "attempt:2"}},
            {"step": 3, "decision_id": "review", "capability": "test.run",
             "result": {"status": "PASSED"}},
        ]
        guard = build_causal_guard(activities)
        self.assertEqual(guard["critical_count"], 1)
        self.assertEqual([row["source"] for row in guard["records"]],
                         ["activity:1", "activity:2"])
        self.assertEqual(guard["missing_declared_dependencies"], ["missing-op"])
        self.assertIsNone(build_causal_guard([activities[0], activities[2]]))

    def test_bounded_lexical_relevance_is_only_a_ranking_hint(self):
        """词面重合只改变可选候选排序，不证明因果或事实等级。"""
        self.assertGreater(
            lexical_relevance("fix payment timeout", "payment timeout logs"),
            lexical_relevance("fix payment timeout", "unrelated astronomy"),
        )

    def test_compaction_keeps_causal_guard_and_reports_provenance(self):
        """强制 Compact 仍保留状态导航与来源摘要，不能吞掉 UNKNOWN。"""
        snapshot = {
            "messages": [{"role": "user", "content": "核对支付后再决定是否重试"}],
            "memory": [{"memory_id": "m1", "text": "无关资料" * 4000}],
        }
        activities = [
            {"step": 1, "decision_id": "pay-1", "capability": "mcp.call",
             "result": {"status": "UNKNOWN", "error": "transport timeout"}},
            {"step": 2, "decision_id": "read-2", "capability": "knowledge.search",
             "result": {"content": "unrelated"}},
        ]
        request = conversation_request(
            SETTINGS, snapshot, snapshot["messages"], activities,
            control={"compact_requested": True},
        )
        content = "\n".join(msg.content for msg in request.messages)
        self.assertIn("UNKNOWN", content)
        self.assertIn("pay-1", content)
        self.assertIn("causal-guard", request.context_report["selected"])
        self.assertEqual(request.context_report["governance"]["causal_critical_count"], 1)
        self.assertTrue(request.context_report["governance"]["causal_guard_selected"])

    def test_required_causal_guard_fails_closed_when_budget_exhausted(self):
        """固定预算容纳不了关键状态时停止模型请求而不是静默截断。"""
        from myth.conversation_context import compile_conversation_context
        snapshot = {"messages": [{"role": "user", "content": "task"}]}
        activities = [
            {"step": i, "decision_id": f"op-{i}", "capability": "mcp.call",
             "result": {"status": "UNKNOWN"}}
            for i in range(100)
        ]
        with self.assertRaises(ContextBudgetError):
            compile_conversation_context(
                "system", snapshot, snapshot["messages"], activities,
                max_bytes=200, compact_mode=True,
            )


    def test_structured_failure_and_parallel_children_are_protected(self):
        """已记录的结构化失败与并行子结果需要进入同一状态导航。"""
        guard = build_causal_guard([
            {"step": 1, "decision_id": "base", "result": {"content": "sample"}},
            {"step": 2, "decision_id": "batch", "capability": "agent.parallel",
             "result": {"results": [
                 {"delegation_id": "child-1", "status": "FAILED",
                  "handoff": {"depends_on": ["base"]}},
                 {"delegation_id": "child-2", "status": "COMPLETED"},
             ]}},
        ])
        self.assertEqual(guard["critical_count"], 1)
        self.assertEqual([item["source"] for item in guard["records"]],
                         ["activity:1", "activity:2"])
        self.assertEqual(guard["records"][-1]["child_delegation_ids"],
                         ["child-1", "child-2"])
        self.assertIn("child_0:FAILED", guard["records"][-1]["reported_outcomes"])
        self.assertEqual(guard["missing_declared_dependencies"], [])
        failure = build_causal_guard([{
            "step": 3, "decision_id": "write",
            "result": {"failure": {"code": "permission_denied", "retryable": False}},
        }])
        self.assertIn("known_failure:permission_denied",
                      failure["records"][0]["reported_outcomes"])

    def test_relevance_prefers_matching_memory_only_when_both_do_not_fit(self):
        """保留原权威来源和用户任务，在预算压力下优先选择词面相关的可选记忆。"""
        snapshot = {
            "messages": [{"role": "user", "content": "payment timeout"}],
            "memory": [
                {"memory_id": "old", "text": "astronomy " * 1600},
                {"memory_id": "important", "text": "payment timeout " * 800},
            ],
        }
        request = conversation_request(SETTINGS, snapshot, snapshot["messages"], [])
        selected = request.context_report["selected"]
        self.assertIn("memory:important@", " ".join(selected))
        self.assertNotIn("memory:old@", " ".join(selected))

    def test_relevant_memory_can_outrank_unrelated_knowledge(self):
        """两种已准入检索来源在同一量尺排序，相关 Memory 不被无关 Knowledge 压制。"""
        snapshot = {
            "messages": [{"role": "user", "content": "payment timeout"}],
            "knowledge": [{"document_id": "unrelated", "citation": "doc:u:0",
                           "title": "astronomy", "content": "astronomy " * 1600}],
            "memory": [{"memory_id": "relevant",
                        "text": "payment timeout " * 800}],
        }
        request = conversation_request(
            SETTINGS, snapshot, snapshot["messages"], [],
        )
        selected = request.context_report["selected"]
        self.assertIn("memory:relevant@", " ".join(selected))
        self.assertNotIn("knowledge:doc:u:0", selected)
        self.assertEqual(request.context_report["delivered"]["memory"], 1)
        self.assertEqual(request.context_report["delivered"]["knowledge"], 0)

    def test_web_send_freezes_provider_window_and_replays_same_intent(self):
        """真实准入持久化公开模型窗口，重复 request_id 不再依赖当前目录或网络。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as runtime:
                repository = Workspace(runtime).repository
                repository.save_settings({
                    "provider": "openai", "model": "fixture",
                    "max_output_tokens": 1024,
                })
                sid = repository.create_session()["id"]
            web = ConversationWebService(root)
            web.model_catalog.quote_settings = lambda settings: settings
            web._spawn = lambda run_id: None
            profile = {
                "id": "fixture", "provider": "openai",
                "context_window": 65536, "source": "provider-preflight",
            }
            calls = []
            def preflight(settings, *, entry):
                """离线预检替身记录请求次数；不联网也不授予执行权。"""
                calls.append(entry)
                return profile
            web._require_model_preflight = preflight
            first = web.send(sid, {"text": "Explain timeout", "request_id": "fixed"})
            with MythRuntime(root) as runtime:
                turn = Workspace(runtime).repository.turn(first["run_id"])
            self.assertEqual(turn["settings"]["admitted_model_profile"], profile)
            self.assertEqual(turn["settings"]["model"], "fixture")
            second = web.send(sid, {"text": "Explain timeout", "request_id": "fixed"})
            self.assertEqual(first, second)
            self.assertEqual(calls, ["send"])

    def test_controlled_mechanisms_change_real_context_behavior(self):
        """真实 Context 编译验证全开、全关、单项开启的差异，不用标签伪造消融。"""
        from myth.evaluation_runner import CONTROLLED_HARNESS_MECHANISMS
        from myth.conversation_context import compile_conversation_context
        self.assertIn("context_causal_guard", CONTROLLED_HARNESS_MECHANISMS)
        self.assertIn("context_relevance_ranking", CONTROLLED_HARNESS_MECHANISMS)
        original = {
            "messages": [{"role": "user", "content": "payment timeout"}],
            "knowledge": [{"document_id": "unrelated", "citation": "doc:u:0",
                           "title": "astronomy", "content": "astronomy " * 1250}],
            "memory": [{"memory_id": "relevant",
                        "text": "payment timeout " * 650}],
        }
        activities = [{"step": 1, "decision_id": "attempt-1",
                       "result": {"status": "UNKNOWN", "error": "timeout"}}]
        def compile_with(enabled):
            """隔离同一输入下的一组机制，使所选内容的变化可直接比较。"""
            snapshot = {**original, "evaluation_harness_mechanisms": list(enabled)}
            return compile_conversation_context(
                "test", snapshot, snapshot["messages"], activities,
                max_bytes=15_000,
            )[1]
        baseline = compile_with(())
        full = compile_with(("context_causal_guard", "context_relevance_ranking"))
        only_causal = compile_with(("context_causal_guard",))
        only_relevance = compile_with(("context_relevance_ranking",))
        self.assertNotIn("causal-guard", baseline["selected"])
        self.assertIn("causal-guard", full["selected"])
        self.assertIn("causal-guard", only_causal["selected"])
        self.assertNotIn("causal-guard", only_relevance["selected"])
        self.assertIn("knowledge:doc:u:0", baseline["selected"])
        self.assertIn("memory:relevant@", " ".join(full["selected"]))
        self.assertIn("memory:relevant@", " ".join(only_relevance["selected"]))

    def test_remote_model_window_requires_frozen_matching_preflight(self):
        """仅身份匹配的冻结公开窗口可以扩大远端软预算，切换模型立即退回保守上限。"""
        remote = {"provider": "openai", "model": "fixture", "max_output_tokens": 1024}
        profile = {"id": "fixture", "provider": "openai",
                   "context_window": 65536, "source": "provider-preflight"}
        budget = remote_context_budget({**remote, "admitted_model_profile": profile})
        self.assertEqual(budget["window_tokens"], 65536)
        self.assertGreater(budget["max_bytes"], 42_000)
        self.assertEqual(remote_context_budget({
            **remote, "model": "another", "admitted_model_profile": profile,
        })["max_bytes"], 42_000)
        self.assertEqual(remote_context_budget(remote)["max_bytes"], 42_000)
        snapshot = {"messages": [{"role": "user", "content": "hello"}]}
        req = conversation_request(
            {**remote, "admitted_model_profile": profile},
            snapshot, snapshot["messages"], [],
        )
        self.assertEqual(req.context_report["max_bytes"], budget["max_bytes"])
        self.assertEqual(req.context_report["declared_model_context_window"], 65536)
        self.assertEqual(req.context_report["model_budget_source"],
                         "provider-preflight-frozen")


if __name__ == "__main__":
    unittest.main()
