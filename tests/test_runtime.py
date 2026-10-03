"""回归边界：精确文件效果、预算与恢复。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.domain import (
    BudgetExceeded,
    IdentityConflict,
    RecoveryRequired,
    SimulatedCrash,
)
from myth.runtime import MythRuntime


# 精确文件效果、预算与恢复的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class RuntimeTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "input.txt"
        self.source.write_text("foo\nkeep\nfoo\n", encoding="utf-8", newline="")

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self) -> None:
        self.tmp.cleanup()

    # 回归断言：精确文件用例走准入、工具、收据和独立字节验收后交付。
    def test_end_to_end_delivery(self) -> None:
        with MythRuntime(self.root) as rt:
            run_id = rt.submit_patch(
                self.source, old_text="foo", new_text="bar", expected_count=2
            )
            status = rt.execute(run_id)
            self.assertEqual(status["state"], "SUCCEEDED")
            self.assertEqual(
                Path(status["managed_file"]).read_text(encoding="utf-8"),
                "bar\nkeep\nbar\n",
            )
            self.assertIsNotNone(status["delivery"])
            self.assertEqual(
                self.source.read_text(encoding="utf-8"), "foo\nkeep\nfoo\n"
            )

    # 回归断言：收据发布后 DB 结算前崩溃，重开可据原收据完成结算。
    def test_receipt_survives_settlement_crash_and_recovery(self) -> None:
        with MythRuntime(self.root) as rt:
            run_id = rt.submit_patch(
                self.source, old_text="foo", new_text="bar", expected_count=2
            )
            with self.assertRaises(SimulatedCrash):
                rt.execute(run_id, failpoint="after_receipt_before_settle")
            self.assertEqual(rt.store.get_attempt_for_run(run_id)["state"], "TICKETED")
        with MythRuntime(self.root) as rt:
            [status] = rt.recover(run_id)
            self.assertEqual(status["state"], "SUCCEEDED")
            accounts = {a["meter"]: a for a in status["budgets"]}
            self.assertEqual(accounts["tool_calls"]["settled"], 1)
            self.assertEqual(accounts["tool_calls"]["unknown_held"], 0)

    # 回归断言：字节已证明效果仍不能证明成本；未知计量占用保留。
    def test_content_reconciliation_keeps_usage_unknown(self) -> None:
        with MythRuntime(self.root) as rt:
            run_id = rt.submit_patch(
                self.source, old_text="foo", new_text="bar", expected_count=2
            )
            with self.assertRaises(SimulatedCrash):
                rt.execute(run_id, failpoint="after_write_before_receipt")
        with MythRuntime(self.root) as rt:
            [status] = rt.recover(run_id)
            accounts = {a["meter"]: a for a in status["budgets"]}
            self.assertEqual(accounts["tool_calls"]["settled"], 0)
            self.assertEqual(accounts["tool_calls"]["unknown_held"], 1)

    # 回归断言：补齐实际计量只结算账本，不再次执行文件效果。
    def test_unknown_usage_can_be_resolved_without_reexecuting_effect(self) -> None:
        with MythRuntime(self.root) as rt:
            run_id = rt.submit_patch(
                self.source, old_text="foo", new_text="bar", expected_count=2
            )
            with self.assertRaises(SimulatedCrash):
                rt.execute(run_id, failpoint="after_write_before_receipt")
        with MythRuntime(self.root) as rt:
            [status] = rt.recover(run_id)
            rt.store.resolve_unknown_usage(
                status["attempt_id"],
                {"tool_calls": 1, "write_bytes": len("bar\nkeep\nbar\n".encode())},
            )
            after = {a["meter"]: a for a in rt.store.get_accounts(run_id)}
            self.assertEqual(after["tool_calls"]["unknown_held"], 0)
            self.assertEqual(after["tool_calls"]["settled"], 1)
            self.assertEqual(rt.store.get_run(run_id)["state"], "SUCCEEDED")

    # 回归断言：已发 Ticket 的机会禁止直接重派；需原机会核对。
    def test_ticketed_attempt_cannot_be_blindly_redispatched(self) -> None:
        with MythRuntime(self.root) as rt:
            run_id = rt.submit_patch(
                self.source, old_text="foo", new_text="bar", expected_count=2
            )
            attempt = rt.store.get_attempt_for_run(run_id)
            rt.store.start_attempt(attempt["attempt_id"], "ticket-manual")
            with self.assertRaises(RecoveryRequired):
                rt.execute(run_id)

    # 回归断言：稳定入口身份不能绑定两种内容，拒绝隐式覆盖。
    def test_same_request_id_different_request_conflicts(self) -> None:
        with MythRuntime(self.root) as rt:
            rt.submit_patch(
                self.source,
                old_text="foo",
                new_text="bar",
                expected_count=2,
                request_id="stable-request",
            )
            with self.assertRaises(IdentityConflict):
                rt.submit_patch(
                    self.source,
                    old_text="foo",
                    new_text="baz",
                    expected_count=2,
                    request_id="stable-request",
                )

    # 回归断言：任一 meter 不足时初始 Run 和全部预留一起回滚，不能提交半成品入口。
    def test_budget_reservation_is_atomic(self) -> None:
        with MythRuntime(self.root) as rt:
            with self.assertRaises(BudgetExceeded):
                rt.submit_patch(
                    self.source,
                    old_text="foo",
                    new_text="bar",
                    expected_count=2,
                    budgets={"tool_calls": 1, "write_bytes": 1},
                )
            for table in (
                "runs",
                "accounts",
                "actions",
                "attempts",
                "reservations",
                "events",
            ):
                self.assertEqual(
                    rt.store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
                    0,
                    table,
                )


if __name__ == "__main__":
    unittest.main()
