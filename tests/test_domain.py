"""回归边界：纯字节替换规则。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

import unittest

from myth.domain import PatchContractError, exact_patch


# 纯字节替换规则的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class ExactPatchTests(unittest.TestCase):
    # 回归断言：精确替换以原始字节合同保留 UTF-8 BOM 和 CRLF。
    def test_preserves_utf8_bom_and_crlf(self) -> None:
        before = b"\xef\xbb\xbfhello\r\nfoo\r\nfoo\r\n"
        plan = exact_patch(before, "foo", "bar", 2)
        self.assertEqual(plan.after, b"\xef\xbb\xbfhello\r\nbar\r\nbar\r\n")

    # 回归断言：实际匹配次数与固定规则不符时拒绝，不猜测用户意图。
    def test_rejects_wrong_match_count(self) -> None:
        with self.assertRaises(PatchContractError):
            exact_patch(b"foo foo", "foo", "bar", 1)

    # 回归断言：候选含旧文本也只按固定基线应用一次，防止恢复重复替换。
    def test_new_text_may_contain_old_text_without_repeat_application(self) -> None:
        plan = exact_patch(b"a", "a", "aa", 1)
        self.assertEqual(plan.after, b"aa")


if __name__ == "__main__":
    unittest.main()
