from __future__ import annotations

import unittest

from myth.domain import PatchContractError, exact_patch


class ExactPatchTests(unittest.TestCase):
    def test_preserves_utf8_bom_and_crlf(self) -> None:
        before = b"\xef\xbb\xbfhello\r\nfoo\r\nfoo\r\n"
        plan = exact_patch(before, "foo", "bar", 2)
        self.assertEqual(plan.after, b"\xef\xbb\xbfhello\r\nbar\r\nbar\r\n")

    def test_rejects_wrong_match_count(self) -> None:
        with self.assertRaises(PatchContractError):
            exact_patch(b"foo foo", "foo", "bar", 1)

    def test_new_text_may_contain_old_text_without_repeat_application(self) -> None:
        plan = exact_patch(b"a", "a", "aa", 1)
        self.assertEqual(plan.after, b"aa")


if __name__ == "__main__":
    unittest.main()
