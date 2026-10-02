from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from myth.agent_runtime import AgentRuntime
from myth.models import ModelResult, ProviderStatus
from myth.runtime import MythRuntime


class LoopProvider:
    provider_id = "fake-loop"

    def check(self) -> ProviderStatus:
        return ProviderStatus(self.provider_id, True, auth_type="none")

    def invoke(self, request) -> ModelResult:
        user_payload = json.loads(request.messages[-1].content)
        context = json.loads(user_payload["context"])
        evidence = []
        for item in context.get("history", []):
            if item.get("kind") == "tool_result":
                ref = item.get("payload", {}).get("evidence_ref")
                if ref:
                    evidence.append(ref)

        if not evidence:
            payload = {
                "decision_type": "tool_call",
                "reason": "The allowed file contains the requested source text.",
                "capability_id": "file.patch_exact",
                "arguments_json": json.dumps({
                    "path": Path(user_payload["allowed_files"][0]).name,
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
        else:
            payload = {
                "decision_type": "request_completion",
                "reason": "The durable tool result proves the requested replacement.",
                "capability_id": "",
                "arguments_json": "{}",
                "question": "",
                "missing_info_category": "",
                "claim": "Replaced foo with bar in the managed file.",
                "goal_coverage": "The one requested replacement is present in the verified managed artifact.",
                "evidence_refs": evidence,
                "remaining": [],
            }

        return ModelResult(
            text=json.dumps(payload),
            usage={"model_calls": 1, "input_tokens": 25, "output_tokens": 30},
            raw={"payload": payload},
            response_id="fake",
        )


class AskProvider:
    provider_id = "fake-ask"

    def check(self) -> ProviderStatus:
        return ProviderStatus(self.provider_id, True, auth_type="none")

    def invoke(self, request) -> ModelResult:
        payload = {
            "decision_type": "ask_user",
            "reason": "A required value is missing.",
            "capability_id": "",
            "arguments_json": "{}",
            "question": "What replacement text should I use?",
            "missing_info_category": "replacement",
            "claim": "",
            "goal_coverage": "",
            "evidence_refs": [],
            "remaining": [],
        }
        return ModelResult(
            text=json.dumps(payload),
            usage={"model_calls": 1, "input_tokens": 10, "output_tokens": 10},
            raw={"payload": payload},
        )


class AgentRuntimeTests(unittest.TestCase):
    def test_agent_executes_tool_then_verifies_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "data.txt"
            source.write_text("foo\n", encoding="utf-8")
            with MythRuntime(root) as runtime:
                agent = AgentRuntime(runtime)
                provider = LoopProvider()
                run_id = agent.create_run(
                    goal="replace foo with bar",
                    provider=provider,
                    model="fake-model",
                    allowed_files=(source,),
                    max_steps=4,
                    max_output_tokens=100,
                )
                status = agent.run(run_id, provider)

                self.assertEqual(status["run"]["state"], "SUCCEEDED")
                self.assertEqual(status["agent"]["status"], "SUCCEEDED")
                self.assertEqual(source.read_text(encoding="utf-8"), "foo\n")
                self.assertEqual(len(status["tool_actions"]), 1)
                managed = runtime.workspaces.path_for(run_id, "data.txt")
                self.assertEqual(managed.read_text(encoding="utf-8"), "bar\n")
                self.assertEqual(status["verification"][-1]["verdict"], "PASS")
                self.assertIsNotNone(status["delivery"])
                self.assertEqual(len(status["model"]["decisions"]), 2)

    def test_model_cannot_escape_allowed_file_set(self) -> None:
        class EscapeProvider(LoopProvider):
            def invoke(self, request) -> ModelResult:
                payload = {
                    "decision_type": "tool_call",
                    "reason": "try another path",
                    "capability_id": "file.patch_exact",
                    "arguments_json": json.dumps({
                        "path": "../secret.txt",
                        "old_text": "x",
                        "new_text": "y",
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
                    usage={"model_calls": 1, "input_tokens": 5, "output_tokens": 5},
                    raw={"payload": payload},
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "data.txt"
            source.write_text("foo", encoding="utf-8")
            secret = root.parent / "secret.txt"
            secret.write_text("x", encoding="utf-8")
            try:
                with MythRuntime(root) as runtime:
                    agent = AgentRuntime(runtime)
                    provider = EscapeProvider()
                    run_id = agent.create_run(
                        goal="edit only the allowed file",
                        provider=provider,
                        model="fake",
                        allowed_files=(source,),
                        max_steps=2,
                        max_output_tokens=50,
                    )
                    status = agent.run(run_id, provider)
                    self.assertEqual(status["agent"]["status"], "BUDGET_EXHAUSTED")
                    self.assertEqual(secret.read_text(encoding="utf-8"), "x")
                    self.assertEqual(len(status["tool_actions"]), 0)
            finally:
                secret.unlink(missing_ok=True)

    def test_agent_can_pause_for_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "data.txt"
            source.write_text("foo", encoding="utf-8")
            with MythRuntime(root) as runtime:
                agent = AgentRuntime(runtime)
                provider = AskProvider()
                run_id = agent.create_run(
                    goal="edit the file after clarification",
                    provider=provider,
                    model="fake",
                    allowed_files=(source,),
                    max_steps=3,
                    max_output_tokens=50,
                )
                status = agent.run(run_id, provider)
                self.assertEqual(status["agent"]["status"], "WAITING_USER")
                self.assertEqual(
                    status["agent"]["pending_question"],
                    "What replacement text should I use?",
                )


if __name__ == "__main__":
    unittest.main()
