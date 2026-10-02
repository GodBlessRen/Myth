from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from myth.domain import BudgetExceeded, IdentityConflict, RecoveryRequired, SimulatedCrash
from myth.runtime import MythRuntime


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "input.txt"
        self.source.write_text("foo\nkeep\nfoo\n", encoding="utf-8", newline="")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_end_to_end_delivery(self) -> None:
        with MythRuntime(self.root) as rt:
            run_id = rt.submit_patch(self.source, old_text="foo", new_text="bar", expected_count=2)
            status = rt.execute(run_id)
            self.assertEqual(status["state"], "SUCCEEDED")
            self.assertEqual(Path(status["managed_file"]).read_text(encoding="utf-8"), "bar\nkeep\nbar\n")
            self.assertIsNotNone(status["delivery"])
            self.assertEqual(self.source.read_text(encoding="utf-8"), "foo\nkeep\nfoo\n")

    def test_receipt_survives_settlement_crash_and_recovery(self) -> None:
        with MythRuntime(self.root) as rt:
            run_id = rt.submit_patch(self.source, old_text="foo", new_text="bar", expected_count=2)
            with self.assertRaises(SimulatedCrash):
                rt.execute(run_id, failpoint="after_receipt_before_settle")
            self.assertEqual(rt.store.get_attempt_for_run(run_id)["state"], "TICKETED")
        with MythRuntime(self.root) as rt:
            [status] = rt.recover(run_id)
            self.assertEqual(status["state"], "SUCCEEDED")
            accounts = {a["meter"]: a for a in status["budgets"]}
            self.assertEqual(accounts["tool_calls"]["settled"], 1)
            self.assertEqual(accounts["tool_calls"]["unknown_held"], 0)

    def test_content_reconciliation_keeps_usage_unknown(self) -> None:
        with MythRuntime(self.root) as rt:
            run_id = rt.submit_patch(self.source, old_text="foo", new_text="bar", expected_count=2)
            with self.assertRaises(SimulatedCrash):
                rt.execute(run_id, failpoint="after_write_before_receipt")
        with MythRuntime(self.root) as rt:
            [status] = rt.recover(run_id)
            accounts = {a["meter"]: a for a in status["budgets"]}
            self.assertEqual(accounts["tool_calls"]["settled"], 0)
            self.assertEqual(accounts["tool_calls"]["unknown_held"], 1)

    def test_unknown_usage_can_be_resolved_without_reexecuting_effect(self) -> None:
        with MythRuntime(self.root) as rt:
            run_id = rt.submit_patch(self.source, old_text="foo", new_text="bar", expected_count=2)
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

    def test_ticketed_attempt_cannot_be_blindly_redispatched(self) -> None:
        with MythRuntime(self.root) as rt:
            run_id = rt.submit_patch(self.source, old_text="foo", new_text="bar", expected_count=2)
            attempt = rt.store.get_attempt_for_run(run_id)
            rt.store.start_attempt(attempt["attempt_id"], "ticket-manual")
            with self.assertRaises(RecoveryRequired):
                rt.execute(run_id)

    def test_same_request_id_different_request_conflicts(self) -> None:
        with MythRuntime(self.root) as rt:
            rt.submit_patch(
                self.source, old_text="foo", new_text="bar", expected_count=2, request_id="stable-request"
            )
            with self.assertRaises(IdentityConflict):
                rt.submit_patch(
                    self.source, old_text="foo", new_text="baz", expected_count=2, request_id="stable-request"
                )

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
            run_row = rt.store.db.execute(
                "SELECT run_id FROM runs ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            run_id = run_row[0]
            accounts = {a["meter"]: a for a in rt.store.get_accounts(run_id)}
            self.assertEqual(accounts["tool_calls"]["reserved"], 0)
            self.assertEqual(accounts["write_bytes"]["reserved"], 0)
            self.assertEqual(rt.store.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
