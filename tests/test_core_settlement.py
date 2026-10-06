"""Core 状态所有者的真实边界回归：权限、未知计量与终态不能被结算覆盖。"""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.domain import IdentityConflict, InvalidTransition, Outcome, ReceiptData, RunState, SimulatedCrash, Verdict
from myth.runtime import MythRuntime


class CoreFixture(unittest.TestCase):
    """每个用例使用真实 SQLite/文件，不以 mock 预算冒充持久原子性。"""

    def setUp(self):
        """注册逆序清理：先关连接再删临时文件。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'input.txt'
        self.source.write_text('old', encoding='utf-8')
        self.rt = MythRuntime(self.tmp.name)
        self.addCleanup(self.rt.close)
        self.run = self.rt.submit_patch(self.source, old_text='old', new_text='new', expected_count=1)
        self.attempt = self.rt.store.get_attempt_for_run(self.run)
        self.aid = self.attempt['attempt_id']

    def accounts(self):
        """通过公开账本读取两个不同单位的资源。"""
        return {a['meter']: a for a in self.rt.store.get_accounts(self.run)}

    def uncertain(self):
        """真实文件效果后收据前注入崩溃；恢复证明字节但不证明成本。"""
        with self.assertRaises(SimulatedCrash):
            self.rt.execute(self.run, failpoint='after_write_before_receipt')
        self.rt.recover(self.run)

    def receipt(self, usage):
        """构造绑定既有机会的测试收据，授权仍由真实仓库校验。"""
        return ReceiptData('test-receipt', self.aid, self.attempt['envelope_digest'], Outcome.SUCCEEDED, 'test:receipt', usage)


class CoreSettlementTests(CoreFixture):
    """用量字段、授权和重试必须保持原子性。"""

    def test_empty_resolution_cannot_release_unknown_hold(self):
        """空报告不是零成本，也不新增伪造已解决事件。"""
        self.uncertain()
        before, events = self.accounts(), self.rt.store.get_events(self.run)
        self.rt.store.resolve_unknown_usage(self.aid, {})
        self.assertEqual(before, self.accounts())
        self.assertEqual(events, self.rt.store.get_events(self.run))

    def test_partial_usage_retains_unreported_meter(self):
        """调用次数和写字节数独立解决，补一项不得清空另一项。"""
        self.uncertain()
        self.rt.store.resolve_unknown_usage(self.aid, {'tool_calls': 1})
        accounts = self.accounts()
        self.assertEqual(accounts['tool_calls']['settled'], 1)
        self.assertEqual(accounts['write_bytes']['unknown_held'], 3)
        self.rt.store.resolve_unknown_usage(self.aid, {'write_bytes': 0})
        self.assertEqual(self.accounts()['write_bytes']['unknown_held'], 0)
        self.assertEqual(self.rt.store.get_run(self.run)['state'], 'SUCCEEDED')

    def test_resolution_before_ticket_or_before_uncertainty_is_rejected(self):
        """未开始与在途请求不是可结算的未知成本。"""
        before = self.accounts()
        with self.assertRaises(InvalidTransition):
            self.rt.store.resolve_unknown_usage(self.aid, {'tool_calls': 0})
        self.rt.store.start_attempt(self.aid, 'ticket')
        with self.assertRaises(InvalidTransition):
            self.rt.store.resolve_unknown_usage(self.aid, {'tool_calls': 0})
        self.assertEqual(before, self.accounts())

    def test_invalid_meter_and_values_roll_back_entire_resolution(self):
        """非整数、布尔、未授权 meter 均不得部分落账。"""
        self.uncertain()
        before, events = self.accounts(), self.rt.store.get_events(self.run)
        invalid = [True, -1, -0.5, 1.5, '1', None, 2**63]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.rt.store.resolve_unknown_usage(self.aid, {'tool_calls': 1, 'write_bytes': value})
        with self.assertRaises(ValueError):
            self.rt.store.resolve_unknown_usage(self.aid, {'tool_calls': 1, 'missing_meter': 2})
        self.assertEqual(before, self.accounts())
        self.assertEqual(events, self.rt.store.get_events(self.run))

    def test_equal_resolution_is_idempotent_and_conflict_is_rejected(self):
        """重复不重扣、不重发事件；冲突金额不覆盖历史。"""
        self.uncertain()
        usage = {'tool_calls': 1, 'write_bytes': 0}
        self.rt.store.resolve_unknown_usage(self.aid, usage)
        before, events = self.accounts(), self.rt.store.get_events(self.run)
        self.rt.store.resolve_unknown_usage(self.aid, usage)
        self.assertEqual(before, self.accounts())
        self.assertEqual(events, self.rt.store.get_events(self.run))
        with self.assertRaises(IdentityConflict):
            self.rt.store.resolve_unknown_usage(self.aid, {'write_bytes': 2})
        self.assertEqual(before, self.accounts())

    def test_partial_receipt_preserves_effect_and_holds_missing_usage(self):
        """收据效果可以确认，缺报成本仍须持续占用。"""
        self.rt.store.start_attempt(self.aid, 'ticket')
        receipt = self.receipt({'tool_calls': 1})
        self.rt.store.settle_receipt(receipt)
        self.assertEqual(self.rt.store.get_attempt_for_run(self.run)['state'], 'RESOLVED')
        self.assertEqual(self.accounts()['write_bytes']['unknown_held'], 3)
        self.rt.store.resolve_unknown_usage(self.aid, {'write_bytes': 2})
        self.assertEqual(self.accounts()['write_bytes']['settled'], 2)
        events = self.rt.store.get_events(self.run)
        self.rt.store.settle_receipt(receipt)
        self.assertEqual(events, self.rt.store.get_events(self.run))
        with self.assertRaises(IdentityConflict):
            self.rt.store.resolve_unknown_usage(self.aid, {'tool_calls': 0})

    def test_receipt_and_unknown_need_actual_ticket(self):
        """机会名字与 envelope 不能代替已签发授权。"""
        before = self.accounts()
        with self.assertRaises(InvalidTransition):
            self.rt.store.settle_receipt(self.receipt({'tool_calls': 1, 'write_bytes': 3}))
        with self.assertRaises(InvalidTransition):
            self.rt.store.mark_attempt_unknown(self.aid, 'not issued')
        self.assertEqual(before, self.accounts())
        self.assertEqual(self.rt.store.get_attempt_for_run(self.run)['state'], 'INTENT')

    def test_unknown_resolution_does_not_block_later_receipt_or_double_charge(self):
        """先补成本再到收据，成本和效果的顺序可独立。"""
        self.rt.store.start_attempt(self.aid, 'ticket')
        self.rt.store.mark_attempt_unknown(self.aid, 'in flight')
        self.rt.store.resolve_unknown_usage(self.aid, {'tool_calls': 1})
        self.rt.store.settle_receipt(self.receipt({'tool_calls': 1, 'write_bytes': 3}))
        self.assertEqual(self.accounts()['tool_calls']['settled'], 1)
        self.assertEqual(self.accounts()['write_bytes']['settled'], 3)

    def test_zero_reservation_unknown_can_be_measured_after_reopen(self):
        """零预留不是已测零；用原事件区分未知和已结算。"""
        run = self.rt.submit_patch(self.source, old_text='old', new_text='', expected_count=1, budgets={'tool_calls': 2, 'write_bytes': 5})
        attempt = self.rt.store.get_attempt_for_run(run)
        aid = attempt['attempt_id']
        self.rt.store.start_attempt(aid, 'empty-ticket')
        self.rt.store.mark_attempt_unknown(aid, 'missing receipt')
        with MythRuntime(self.tmp.name) as reopened:
            reopened.store.resolve_unknown_usage(aid, {'write_bytes': 2})
            accounts = {a['meter']: a for a in reopened.store.get_accounts(run)}
            self.assertEqual(accounts['write_bytes']['settled'], 2)
            self.assertEqual(accounts['tool_calls']['unknown_held'], 1)
            with self.assertRaises(IdentityConflict):
                reopened.store.resolve_unknown_usage(aid, {'write_bytes': 0})

    def test_valid_usage_above_estimate_is_not_clamped(self):
        """实测超预估仍完整记账，不伪造满足预算。"""
        self.uncertain()
        self.rt.store.resolve_unknown_usage(self.aid, {'tool_calls': 7})
        self.assertEqual(self.accounts()['tool_calls']['settled'], 7)

    def test_event_failure_rolls_back_resolution(self):
        """账本和用量证据同一事务，事件失败不能只剩金额。"""
        self.uncertain()
        before = self.accounts()
        with patch.object(self.rt.store, '_event', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.rt.store.resolve_unknown_usage(self.aid, {'tool_calls': 1})
        self.assertEqual(before, self.accounts())


class CoreVerificationTests(CoreFixture):
    """终态与验收主体必须在仓库提交事务内再次核对。"""

    def report(self, **overrides):
        """固定当前原子操作的候选与验收合同。"""
        action = self.rt.store.get_action_for_run(self.run)
        params = dict(run_id=self.run, action_id=action['action_id'], candidate_digest=action['after_digest'], acceptance_version=self.rt.ACCEPTANCE_VERSION, verdict=Verdict.PASS, evidence_ref='test:verification')
        params.update(overrides)
        return self.rt.store.create_verification_report(**params)

    def test_cancelled_or_failed_run_cannot_reopen_at_verification(self):
        """效果结算后取消，迟到验收不得将终态改成 SUCCEEDED。"""
        self.rt.execute_patch_action(self.run)
        self.rt.store.transition_run(self.run, RunState.CANCELLED, event_kind='UserStopped')
        with self.assertRaises(InvalidTransition):
            self.rt.execute(self.run)
        self.assertEqual(self.rt.store.get_run(self.run)['state'], 'CANCELLED')
        self.assertIsNone(self.rt.store.get_delivery(self.run))
        self.assertEqual(self.rt.store.db.execute('SELECT count(*) FROM verification_reports').fetchone()[0], 0)

    def test_report_for_another_runs_action_is_rejected(self):
        """合法主键存在不等于属于这个 Run。"""
        other = self.rt.submit_patch(self.source, old_text='old', new_text='other', expected_count=1)
        action = self.rt.store.get_action_for_run(other)
        with self.assertRaises(IdentityConflict):
            self.report(action_id=action['action_id'])
        self.assertEqual(self.rt.store.get_run(self.run)['state'], 'RUNNING')

    def test_verification_requires_resolved_successful_effect(self):
        """已知期望摘要不代表真实执行完成。"""
        with self.assertRaises(InvalidTransition):
            self.report()
        self.rt.store.start_attempt(self.aid, 'ticket')
        self.rt.store.settle_receipt(replace(self.receipt({'tool_calls': 0, 'write_bytes': 0}), outcome=Outcome.FAILED))
        with self.assertRaises(InvalidTransition):
            self.report()

    def test_stop_between_verification_and_delivery_still_wins(self):
        """验收成功不会取消交付时的控制复核。"""
        self.rt.execute_patch_action(self.run)
        report = self.report()
        self.rt.store.transition_run(self.run, RunState.CANCELLED, event_kind='UserStopped')
        action = self.rt.store.get_action_for_run(self.run)
        with self.assertRaises(InvalidTransition):
            self.rt.store.deliver(run_id=self.run, action_id=action['action_id'], candidate_digest=action['after_digest'], report_id=report)
        self.assertIsNone(self.rt.store.get_delivery(self.run))

    def test_completed_run_cannot_be_reopened_by_another_report(self):
        """已交付的终态不回到 VERIFYING。"""
        self.rt.execute(self.run)
        before = self.rt.store.get_events(self.run)
        with self.assertRaises(InvalidTransition):
            self.report()
        self.assertEqual(self.rt.store.get_run(self.run)['state'], 'SUCCEEDED')
        self.assertEqual(before, self.rt.store.get_events(self.run))
