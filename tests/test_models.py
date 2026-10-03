"""回归边界：统一模型决定解析。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

import json
import unittest

from myth.models import DecisionValidationError, parse_step_decision


# 统一模型决定解析的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class DecisionTests(unittest.TestCase):
    # 回归断言：统一工具线协议严格解析为领域决定，参数仍由执行器校验。
    def test_tool_call_transport(self) -> None:
        raw = {
            "decision_type": "tool_call",
            "reason": "Apply the requested exact patch.",
            "capability_id": "file.patch_exact",
            "arguments_json": json.dumps(
                {
                    "path": "a.txt",
                    "old_text": "foo",
                    "new_text": "bar",
                    "expected_count": 2,
                }
            ),
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

    # 回归断言：提问决定必须有实际问题文本，不能用空值创建等待。
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
