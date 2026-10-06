"""Core 仓储事实边界：未派发不结算、终态不复活、验收身份不能串用。
真实 SQLite 与精确替换准入构成夹具；不执行模型或外部文件效果。
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.domain import IdentityConflict, InvalidTransition, Outcome, ReceiptData, RunState, Verdict
from myth.runtime import MythRuntime


class CoreFactGuardTests(unittest.TestCase):
    """直接调用状态所有者，确保防线不会依赖某一个上游调用者自觉检查。"""

    # 每例独立仓储；准入只创建 Intent，Ticket 在用例内显式签发。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "source.txt"
        self.source.write_text("before", encoding="utf-8")
        self.runtime = MythRuntime(self.root)
        self.store = self.runtime.store
        self.rid = self.runtime.submit_patch(self.source, old_text="before", new_text="after", expected_count=1)
        self.action = self.store.get_action_for_run(self.rid)
        self.attempt = self.store.get_attempt_for_run(self.rid)

    # Windows 必须先释放连接再删除目录。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 收据身份与冻结 envelope 相同，单独改变派发资格来刻画攻击窗口。
    def receipt(self, outcome=Outcome.SUCCEEDED):
        return ReceiptData("receipt", self.attempt["attempt_id"], self.attempt["envelope_digest"], outcome, "fixture:evidence", {"tool_calls": 1, "write_bytes": 5})

    # 默认创建本 Action 的固定候选报告；参数覆盖用于跨 Run 身份回归。
    def report(self, **overrides):
        # PASS 报告必须先有真实已解决效果；独立验收仍由本测试显式创建。
        if self.store.get_attempt_for_run(self.rid)["state"] == "INTENT":
            self.runtime.execute_patch_action(self.rid)
        args = dict(run_id=self.rid, action_id=self.action["action_id"], candidate_digest=self.action["after_digest"], acceptance_version=self.store.get_run(self.rid)["acceptance_version"], verdict=Verdict.PASS, evidence_ref="fixture:verification")
        args.update(overrides)
        return self.store.create_verification_report(**args)

    # Intent 没有派发资格，伪造已知效果收据不能释放预留或完成机会。
    def test_receipt_requires_actual_ticket(self):
        before = self.store.get_accounts(self.rid)
        with self.assertRaises(InvalidTransition):
            self.store.settle_receipt(self.receipt())
        self.assertEqual(self.store.get_attempt_for_run(self.rid)["state"], "INTENT")
        self.assertEqual(self.store.get_accounts(self.rid), before)

    # 未发机会不能被伪装成 UNKNOWN 来占住恢复通道。
    def test_unknown_requires_actual_ticket(self):
        with self.assertRaises(InvalidTransition):
            self.store.mark_attempt_unknown(self.attempt["attempt_id"], "not dispatched")

    # 只有已结算效果的未知计量才允许补账；不能提前清空 Intent 预留。
    def test_usage_resolution_cannot_settle_unstarted_intent(self):
        with self.assertRaises(InvalidTransition):
            self.store.resolve_unknown_usage(self.attempt["attempt_id"], {"tool_calls": 1})

    # 已派发效果未定与费用已知是两条事实，补账不能把 UNKNOWN 改成已完成。
    def test_known_usage_can_resolve_cost_of_unknown_effect(self):
        self.store.start_attempt(self.attempt["attempt_id"], "ticket")
        self.store.mark_attempt_unknown(self.attempt["attempt_id"], "no effect receipt")
        self.store.resolve_unknown_usage(self.attempt["attempt_id"], {"tool_calls": 1})
        self.assertEqual(self.store.get_attempt_for_run(self.rid)["state"], "UNKNOWN")
        self.assertEqual(len(self.store.get_pending_attempts(self.rid)), 1)

    # 已发晚到收据仍是真实事实，取消仅阻止新工作；重复回调不重复扣费。
    def test_late_receipt_after_cancellation_is_idempotent(self):
        self.store.start_attempt(self.attempt["attempt_id"], "ticket")
        self.store.transition_run(self.rid, RunState.CANCELLED, event_kind="UserCancelled")
        self.store.settle_receipt(self.receipt())
        before = self.store.get_accounts(self.rid)
        self.store.settle_receipt(self.receipt())
        self.assertEqual(self.store.get_accounts(self.rid), before)
        self.assertEqual(self.store.get_run(self.rid)["state"], "CANCELLED")

    # UNKNOWN 收据不能把机会标成 RESOLVED；保留先核对再结算的单独入口。
    def test_unknown_receipt_cannot_resolve_attempt(self):
        self.store.start_attempt(self.attempt["attempt_id"], "ticket")
        with self.assertRaises(InvalidTransition):
            self.store.settle_receipt(self.receipt(Outcome.UNKNOWN))

    # 只报告一个 meter 时，其余预留继续 UNKNOWN；后续补账也只释放明确报告的项。
    def test_partial_usage_preserves_unreported_meter(self):
        self.store.start_attempt(self.attempt["attempt_id"], "ticket")
        partial = ReceiptData("receipt", self.attempt["attempt_id"], self.attempt["envelope_digest"], Outcome.SUCCEEDED, "fixture:evidence", {"tool_calls": 1})
        self.store.settle_receipt(partial)
        accounts = {row["meter"]: row for row in self.store.get_accounts(self.rid)}
        self.assertEqual(accounts["tool_calls"]["settled"], 1)
        self.assertEqual(accounts["write_bytes"]["unknown_held"], 5)
        self.store.resolve_unknown_usage(self.attempt["attempt_id"], {"tool_calls": 1})
        self.assertEqual({row["meter"]: row for row in self.store.get_accounts(self.rid)}["write_bytes"]["unknown_held"], 5)
        self.store.resolve_unknown_usage(self.attempt["attempt_id"], {"write_bytes": 5})
        self.assertEqual({row["meter"]: row for row in self.store.get_accounts(self.rid)}["write_bytes"]["unknown_held"], 0)

    # 外来 Action 即使真实存在，也不能挂在另一个 Run 的验收报告上。
    def test_verification_rejects_foreign_action(self):
        other = self.runtime.submit_patch(self.source, old_text="before", new_text="other", expected_count=1)
        foreign = self.store.get_action_for_run(other)
        with self.assertRaises(IdentityConflict):
            self.report(action_id=foreign["action_id"])
        self.assertEqual(self.store.get_run(self.rid)["state"], "RUNNING")

    # 所有终态都不可被旧报告入口改回 VERIFYING。
    def test_verification_cannot_reopen_terminal_run(self):
        for terminal in (RunState.CANCELLED, RunState.FAILED, RunState.SUCCEEDED):
            with self.subTest(terminal=terminal):
                self.store.db.execute("UPDATE runs SET state=? WHERE run_id=?", (terminal.value, self.rid))
                with self.assertRaises(InvalidTransition):
                    self.report()
                self.assertEqual(self.store.get_run(self.rid)["state"], terminal.value)

    # 报告生成后合同版本变化，交付仍必须重新核对，不能借用旧 PASS。
    def test_delivery_rechecks_acceptance_version(self):
        report_id = self.report()
        self.store.db.execute("UPDATE runs SET acceptance_version='changed' WHERE run_id=?", (self.rid,))
        with self.assertRaises(IdentityConflict):
            self.store.deliver(run_id=self.rid, action_id=self.action["action_id"], candidate_digest=self.action["after_digest"], report_id=report_id)

    # 唯一交付只对同一内容幂等；新候选不能拿旧 delivery_id 冒充成功。
    def test_delivery_identity_is_not_reused_for_another_candidate(self):
        first = self.report()
        args = dict(run_id=self.rid, action_id=self.action["action_id"], candidate_digest=self.action["after_digest"], report_id=first)
        delivery = self.store.deliver(**args)
        self.assertEqual(self.store.deliver(**args), delivery)
        self.store.db.execute("UPDATE verification_reports SET candidate_digest='other' WHERE report_id=?", (first,))
        with self.assertRaises(IdentityConflict):
            self.store.deliver(**dict(args, candidate_digest="other"))


if __name__ == "__main__":
    unittest.main()
