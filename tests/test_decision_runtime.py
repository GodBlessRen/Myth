from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from myth.decision_runtime import DecisionRuntime
from myth.models import ModelResult, ProviderStatus
from myth.runtime import MythRuntime


class FakeProvider:
    provider_id = "fake"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def check(self) -> ProviderStatus:
        return ProviderStatus(self.provider_id, True, auth_type="none")

    def invoke(self, request) -> ModelResult:
        if self.fail:
            raise RuntimeError("connection lost after dispatch")
        payload = {
            "decision_type": "tool_call",
            "reason": "The explicit file can be patched.",
            "capability_id": "file.patch_exact",
            "arguments_json": json.dumps({
                "path": "data.txt",
                "old_text": "foo",
                "new_text": "bar",
                "expected_count": 1,
            }),
            "question": "",
            "missing_info_category": "",
            "claim": "",
            "goal_coverage": "",
            "evidence_refs": [],
            "remaining": [],
        }
        return ModelResult(
            text=json.dumps(payload),
            usage={"model_calls": 1, "input_tokens": 20, "output_tokens": 30},
            raw={"id": "fake-response", "payload": payload},
            response_id="fake-response",
        )


class DecisionRuntimeTests(unittest.TestCase):
    def test_model_tool_call_is_only_a_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "data.txt"
            target.write_text("foo", encoding="utf-8")
            with MythRuntime(root) as base:
                decisions = DecisionRuntime(base)
                run_id = decisions.create_goal_run(
                    goal="replace foo with bar in data.txt",
                    provider_id="fake",
                    model_id="fake-model",
                    allowed_files=(target,),
                    max_output_tokens=100,
                )
                decision_id, decision = decisions.request_decision(
                    run_id=run_id,
                    provider=FakeProvider(),
                    model="fake-model",
                    allowed_files=(target,),
                    max_output_tokens=100,
                )
                status = decisions.status(run_id)
                self.assertTrue(decision_id.startswith("dec_"))
                self.assertEqual(decision.decision_type, "tool_call")
                self.assertEqual(status["run"]["state"], "RUNNING")
                self.assertEqual(target.read_text(encoding="utf-8"), "foo")
                self.assertEqual(base.store.db.execute("SELECT COUNT(*) FROM actions").fetchone()[0], 0)
                accounts = {row["meter"]: row for row in status["budgets"]}
                self.assertEqual(accounts["model_calls"]["settled"], 1)
                self.assertEqual(accounts["input_tokens"]["settled"], 20)
                self.assertEqual(accounts["output_tokens"]["settled"], 30)

    def test_provider_exception_after_ticket_becomes_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with MythRuntime(root) as base:
                decisions = DecisionRuntime(base)
                run_id = decisions.create_goal_run(
                    goal="decide what to do",
                    provider_id="fake",
                    model_id="fake-model",
                    max_output_tokens=50,
                )
                with self.assertRaises(RuntimeError):
                    decisions.request_decision(
                        run_id=run_id,
                        provider=FakeProvider(fail=True),
                        model="fake-model",
                        max_output_tokens=50,
                    )
                status = decisions.status(run_id)
                self.assertEqual(status["model_invocations"][0]["state"], "UNKNOWN")
                accounts = {row["meter"]: row for row in status["budgets"]}
                self.assertEqual(accounts["model_calls"]["unknown_held"], 1)
                self.assertGreater(accounts["input_tokens"]["unknown_held"], 0)
                self.assertEqual(accounts["output_tokens"]["unknown_held"], 50)


if __name__ == "__main__":
    unittest.main()
