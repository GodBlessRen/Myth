from __future__ import annotations

import json
import unittest

from myth.models import DecisionValidationError, parse_step_decision


class DecisionTests(unittest.TestCase):
    def test_tool_call_transport(self) -> None:
        raw = {
            "decision_type": "tool_call",
            "reason": "Apply the requested exact patch.",
            "capability_id": "file.patch_exact",
            "arguments_json": json.dumps({"path": "a.txt", "old_text": "foo", "new_text": "bar", "expected_count": 2}),
            "question": "",
            "missing_info_category": "",
            "claim": "",
            "goal_coverage": "",
            "evidence_refs": [],
            "remaining": [],
        }
        decision = parse_step_decision(json.dumps(raw))
        self.assertEqual(decision.decision_type, "tool_call")
        self.assertEqual(decision.arguments["expected_count"], 2)

    def test_ask_user_requires_question(self) -> None:
        raw = {
            "decision_type": "ask_user",
            "reason": "Need a target.",
            "capability_id": "",
            "arguments_json": "{}",
            "question": "",
            "missing_info_category": "target",
            "claim": "",
            "goal_coverage": "",
            "evidence_refs": [],
            "remaining": [],
        }
        with self.assertRaises(DecisionValidationError):
            parse_step_decision(json.dumps(raw))
