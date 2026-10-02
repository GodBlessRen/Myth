from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from myth.models import ModelMessage, ModelRequest, STEP_DECISION_SCHEMA
from myth.providers.ollama import OllamaProvider
from myth.providers.openai import OpenAIResponsesProvider, PiBearerTokenSource


class FakeResponse:
    def __init__(self, value: dict) -> None:
        self.payload = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return self.payload


def request_obj() -> ModelRequest:
    return ModelRequest(
        model="demo",
        messages=(ModelMessage("system", "system"), ModelMessage("user", "goal")),
        response_schema=STEP_DECISION_SCHEMA,
        max_output_tokens=128,
    )


class OllamaProviderTests(unittest.TestCase):
    def test_usage_and_schema_are_forwarded(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return FakeResponse({
                "message": {"role": "assistant", "content": "{}"},
                "prompt_eval_count": 12,
                "eval_count": 7,
                "total_duration": 99,
            })

        with patch("myth.providers.ollama.request.urlopen", side_effect=fake_urlopen):
            result = OllamaProvider().invoke(request_obj())
        self.assertEqual(captured["body"]["format"], STEP_DECISION_SCHEMA)
        self.assertEqual(captured["body"]["stream"], False)
        self.assertEqual(result.usage["input_tokens"], 12)
        self.assertEqual(result.usage["output_tokens"], 7)


class OpenAIProviderTests(unittest.TestCase):
    def test_subscription_omits_max_output_tokens_and_does_not_persist_token(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["auth"] = req.headers.get("Authorization") or req.headers.get("authorization")
            captured["body"] = json.loads(req.data)
            return FakeResponse({
                "id": "resp_1",
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
                "usage": {"input_tokens": 3, "output_tokens": 4},
            })

        provider = OpenAIResponsesProvider(
            provider_id="pi-openai",
            token_supplier=lambda: "secret-token",
            subscription_token=True,
            auth_type="oauth",
        )
        with patch("myth.providers.openai.request.urlopen", side_effect=fake_urlopen):
            result = provider.invoke(request_obj())
        self.assertEqual(captured["auth"], "Bearer secret-token")
        self.assertNotIn("max_output_tokens", captured["body"])
        self.assertNotIn("secret-token", json.dumps(result.raw))
        self.assertEqual(result.usage["model_calls"], 1)

    def test_api_key_path_includes_max_output_tokens(self) -> None:
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return FakeResponse({
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
                "usage": {},
            })

        provider = OpenAIResponsesProvider(
            provider_id="openai",
            token_supplier=lambda: "sk-test",
            subscription_token=False,
        )
        with patch("myth.providers.openai.request.urlopen", side_effect=fake_urlopen):
            provider.invoke(request_obj())
        self.assertEqual(captured["body"]["max_output_tokens"], 128)


class PiTokenSourceTests(unittest.TestCase):
    @patch("myth.providers.openai.subprocess.run")
    def test_token_is_requested_through_public_pi_cli(self, run) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "oauth-token\n"
        run.return_value.stderr = ""
        source = PiBearerTokenSource(pi_command="pi")
        self.assertEqual(source.token(), "oauth-token")
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ["pi", "auth", "print-bearer-token", "--provider"])
        self.assertIn("--min-expiry", args)
