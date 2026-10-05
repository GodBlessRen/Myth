"""CompletionGuard 的规则顺序与单入口回归。"""

import unittest

from myth.models import StepDecision
from myth.platform.completion import CompletionGuard


class CompletionGuardRuleTests(unittest.TestCase):
    def test_pending_review_precedes_model_remaining_work(self):
        turn = {
            "snapshot": {},
            "activities": [{
                "decision": {"capability_id": "agent.delegate"},
                "result": {"delegation_id": "child-1"},
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
