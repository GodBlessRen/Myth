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


class ConversationStateTests(unittest.TestCase):
    def test_named_guards_keep_unknown_out_of_background_dispatch(self):
        self.assertTrue(is_active("UNKNOWN"))
        self.assertTrue(is_drivable("UNKNOWN"))
        self.assertFalse(is_executor_candidate("UNKNOWN"))
        self.assertTrue(is_pausable("UNKNOWN"))

    def test_terminal_states_cannot_reopen(self):
        for state in ("COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"):
            with self.subTest(state=state):
                self.assertFalse(can_transition(state, "RUNNING"))
                with self.assertRaises(InvalidTransition):
                    require_transition(state, "RUNNING")

    def test_waiting_user_resumes_only_through_explicit_answer_path(self):
        self.assertTrue(can_transition("WAITING_USER", "RUNNING"))
        self.assertFalse(can_transition("WAITING_USER", "PAUSED"))
        self.assertFalse(is_drivable("WAITING_USER"))

    def test_unknown_must_reopen_before_completion(self):
        self.assertTrue(can_transition("UNKNOWN", "RUNNING"))
        self.assertFalse(can_transition("UNKNOWN", "COMPLETED"))


if __name__ == "__main__":
    unittest.main()
