"""Conversation Turn 的集中状态迁移合同回归。"""

import unittest

from myth.domain import InvalidTransition
from myth.domains.conversation_state import (
    can_transition,
    is_active,
    is_drivable,
    is_executor_candidate,
    is_pausable,
    require_transition,
)


# 集中状态合同的固定回归；只证明纯迁移语义，不替代数据库并发测试。
class ConversationStateTests(unittest.TestCase):
    # UNKNOWN 可人工恢复但不能被后台当作可自动派发状态。
    def test_named_guards_keep_unknown_out_of_background_dispatch(self):
        self.assertTrue(is_active("UNKNOWN"))
        self.assertTrue(is_drivable("UNKNOWN"))
        self.assertFalse(is_executor_candidate("UNKNOWN"))
        self.assertTrue(is_pausable("UNKNOWN"))

    # 所有终态都拒绝重新进入 RUNNING，避免用状态改写覆盖历史事实。
    def test_terminal_states_cannot_reopen(self):
        for state in ("COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"):
            with self.subTest(state=state):
                self.assertFalse(can_transition(state, "RUNNING"))
                with self.assertRaises(InvalidTransition):
                    require_transition(state, "RUNNING")

    # WAITING_USER 只能由匹配问题身份的用户回答路径恢复，不由后台驱动。
    def test_waiting_user_resumes_only_through_explicit_answer_path(self):
        self.assertTrue(can_transition("WAITING_USER", "RUNNING"))
        self.assertFalse(can_transition("WAITING_USER", "PAUSED"))
        self.assertFalse(is_drivable("WAITING_USER"))

    # UNKNOWN 必须先 reconcile/reopen，不能直接跳到完成态。
    def test_unknown_must_reopen_before_completion(self):
        self.assertTrue(can_transition("UNKNOWN", "RUNNING"))
        self.assertFalse(can_transition("UNKNOWN", "COMPLETED"))


if __name__ == "__main__":
    unittest.main()
