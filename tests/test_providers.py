from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from myth.models import ContextTruncated, ModelMessage, ModelRequest, STEP_DECISION_SCHEMA
from myth.providers.ollama import OllamaProvider
from myth.providers.openai import OpenAIResponsesProvider


class FakeResponse:
    def __init__(self, value: dict) -> None:
        self.payload = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return self.payload


class FakeStreamResponse:
    def __init__(self, events):
        self.lines=[("data: "+json.dumps(event)+"\n").encode() for event in events]

    def __enter__(self):
        return self

    def __exit__(self,*_):
        return False

    def __iter__(self):
        return iter(self.lines)


def request_obj() -> ModelRequest:
    return ModelRequest(
        model="demo",
        messages=(ModelMessage("system", "system"), ModelMessage("user", "goal")),
        response_schema=STEP_DECISION_SCHEMA,
        max_output_tokens=128,
        num_ctx=4096,
        temperature=0.2,
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
        self.assertEqual(captured["body"]["keep_alive"], "5m")
        self.assertEqual(captured["body"]["options"]["num_ctx"], 4096)
        self.assertEqual(captured["body"]["options"]["temperature"], 0.2)
        self.assertEqual(result.usage["input_tokens"], 12)
        self.assertEqual(result.usage["output_tokens"], 7)


    def test_context_ceiling_is_reported_as_known_failure(self) -> None:
        def fake_urlopen(req, timeout):
            return FakeResponse({
                "message":{"role":"assistant","content":"{}"},
                "prompt_eval_count":4090,
                "eval_count":2,
            })

        with patch("myth.providers.ollama.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(ContextTruncated) as caught:
                OllamaProvider().invoke(request_obj())
        self.assertEqual(caught.exception.usage["input_tokens"],4090)
        self.assertEqual(caught.exception.usage["output_tokens"],2)
        self.assertEqual(caught.exception.raw["prompt_eval_count"],4090)


class OpenAIProviderTests(unittest.TestCase):
    def test_chatgpt_plan_streams_and_does_not_persist_token(self) -> None:
        captured = {}
        completed={
            "id":"resp_1",
            "status":"completed",
            "output":[{"type":"message","content":[{"type":"output_text","text":"{}"}]}],
            "usage":{"input_tokens":8,"output_tokens":4,"input_tokens_details":{"cached_tokens":5}},
        }

        def fake_urlopen(req, timeout):
            captured["auth"] = req.headers.get("Authorization") or req.headers.get("authorization")
            captured["body"] = json.loads(req.data)
            return FakeStreamResponse([
                {"type":"response.output_text.delta","delta":"{}"},
                {"type":"response.completed","response":completed},
            ])

        provider = OpenAIResponsesProvider(
            provider_id="chatgpt",
            token_supplier=lambda: "secret-token",
            chatgpt_plan=True,
            auth_type="oauth",
        )
        with patch("myth.providers.openai.request.urlopen", side_effect=fake_urlopen):
            result = provider.invoke(request_obj())
        self.assertEqual(captured["auth"], "Bearer secret-token")
        self.assertTrue(captured["body"]["stream"])
        self.assertFalse(captured["body"]["store"])
        self.assertNotIn("max_output_tokens", captured["body"])
        self.assertNotIn("secret-token", json.dumps(result.raw))
        self.assertEqual(result.usage["input_tokens"], 8)
        self.assertEqual(result.usage["cached_input_tokens"], 5)

    def test_chatgpt_plan_requires_completed_terminal_event(self) -> None:
        provider = OpenAIResponsesProvider(
            provider_id="chatgpt",
            token_supplier=lambda: "secret-token",
            chatgpt_plan=True,
            auth_type="oauth",
        )
        with patch(
            "myth.providers.openai.request.urlopen",
            return_value=FakeStreamResponse([{"type":"response.output_text.delta","delta":"partial"}]),
        ):
            with self.assertRaisesRegex(RuntimeError,"without response.completed"):
                provider.invoke(request_obj())

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
            chatgpt_plan=False,
        )
        with patch("myth.providers.openai.request.urlopen", side_effect=fake_urlopen):
            provider.invoke(request_obj())
        self.assertEqual(captured["body"]["max_output_tokens"], 128)
