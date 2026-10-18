"""Context Governance 纯策略与真实 Conversation 编译回归。"""

import unittest

from myth.acceptance import ContextBudgetError
from myth.conversation import conversation_request
from myth.platform.context_governance import build_causal_guard, lexical_relevance


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


if __name__ == "__main__":
    unittest.main()
