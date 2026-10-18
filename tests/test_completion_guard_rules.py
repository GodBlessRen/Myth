"""CompletionGuard 的规则顺序与单入口回归。"""

import unittest

from myth.models import StepDecision
from myth.platform.completion import CompletionGuard


# 完成守卫单入口与内部规则优先级的固定回归。
class CompletionGuardRuleTests(unittest.TestCase):
    # 子任务待评审比模型自报 remaining 更早暴露，保持既有产品语义。
    def test_pending_review_precedes_model_remaining_work(self):
        turn = {
            "snapshot": {},
            "activities": [{
                "decision": {"capability_id": "agent.delegate"},
                "result": {"delegation_id": "child-1", "review_required": True},
            }],
        }
        decision = StepDecision(
            decision_type="request_completion",
            reason="done",
            claim="done",
            goal_coverage="all",
            remaining=("still unfinished",),
        )
        verdict = CompletionGuard().evaluate(turn, decision)
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.observation.code, "subagent_review_pending")

    # 原项目 PASS 不能证明隔离输出的候选，也不能证明之后出现的新版本。
    def test_source_only_pass_cannot_prove_candidate(self):
        artifact = {"name": "main.py", "digest": "aaa", "decision_id": "patch-1"}
        turn = {"snapshot": {}, "activities": [
            {"decision": {"capability_id": "project.patch_exact"}, "result": {"artifact": artifact}},
            {"decision": {"capability_id": "test.run"}, "result": {"status": "PASSED"}},
        ]}
        proposal = StepDecision(decision_type="request_completion", reason="done", claim="done")
        verdict = CompletionGuard().evaluate(turn, proposal)
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.observation.code, "verification_subject_mismatch")
        turn["activities"][-1]["result"]["tested_subject"] = {
            "kind": "candidate_overlay", "candidates": [
                {"path": "main.py", "digest": "aaa", "decision_id": "patch-1"},
            ],
        }
        self.assertTrue(CompletionGuard().evaluate(turn, proposal).allowed)
        turn["activities"].append({
            "decision": {"capability_id": "project.patch_exact"},
            "result": {"artifact": {"name": "main.py", "digest": "bbb", "decision_id": "patch-2"}},
        })
        self.assertEqual(
            CompletionGuard().evaluate(turn, proposal).observation.code,
            "verification_subject_mismatch",
        )

    # 不同文件必须同时进入候选测试集合；仅最后一个文件 PASS 不代表完整工作树 PASS。
    def test_multifile_candidate_requires_exact_subject_set(self):
        turn = {"snapshot": {}, "activities": [
            {"decision": {"capability_id": "project.patch_exact"},
             "result": {"artifact": {"name": "a.py", "digest": "a", "decision_id": "p1"}}},
            {"decision": {"capability_id": "project.patch_exact"},
             "result": {"artifact": {"name": "b.py", "digest": "b", "decision_id": "p2"}}},
            {"decision": {"capability_id": "test.run"}, "result": {
                "status": "PASSED", "tested_subject": {
                    "kind": "candidate_overlay",
                    "candidates": [{"path": "b.py", "digest": "b", "decision_id": "p2"}],
                },
            }},
        ]}
        proposal = StepDecision(decision_type="request_completion", reason="done", claim="done")
        self.assertEqual(
            CompletionGuard().evaluate(turn, proposal).observation.code,
            "verification_subject_mismatch",
        )

    # 所有规则通过时仍由同一个 evaluate 入口批准，不要求调用方了解内部链。
    def test_all_rules_pass_through_same_public_entrypoint(self):
        decision = StepDecision(
            decision_type="request_completion",
            reason="done",
            claim="done",
            goal_coverage="all",
        )
        verdict = CompletionGuard().evaluate({"snapshot": {}, "activities": []}, decision)
        self.assertTrue(verdict.allowed)


if __name__ == "__main__":
    unittest.main()
