"""回归边界：固定供应商传输夹具。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

import json
import io
import unittest
from unittest.mock import patch

from myth.models import (
    ContextTruncated,
    ModelMessage,
    ModelRequest,
    STEP_DECISION_SCHEMA,
)
from myth.providers.deepseek import DeepSeekApiKeyProvider
from myth.providers.ollama import OllamaProvider
from myth.providers.openai import OpenAIResponsesProvider


# 固定供应商传输夹具的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class FakeResponse:
    # 保存可控测试条件；这些字段属于替身，不模拟远端真实保证。
    def __init__(self, value: dict) -> None:
        self.payload = json.dumps(value).encode()

    # 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def __enter__(self):
        return self

    # 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def __exit__(self, *_):
        return False

    # 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def read(self, size=-1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]


# 固定供应商传输夹具的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class FakeStreamResponse:
    # 保存可控测试条件；这些字段属于替身，不模拟远端真实保证。
    def __init__(self, events):
        # headers：声明与真实 Responses 流一致的媒体类型，确保传输实现走 SSE 解析分支。
        self.headers = {"Content-Type": "text/event-stream"}
        self.lines = [
            ("data: " + json.dumps(event) + "\n\n").encode() for event in events
        ]
        self.stream = io.BytesIO(b"".join(self.lines))

    # 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def __enter__(self):
        return self

    # 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def __exit__(self, *_):
        return False

    # 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def __iter__(self):
        return iter(self.lines)

    # 模拟有界读取真实 HTTP 流；固定 SSE 帧不能代表远端模型成功。
    def readline(self, size=-1):
        return self.stream.readline(size)


# 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
def request_obj() -> ModelRequest:
    return ModelRequest(
        model="demo",
        messages=(ModelMessage("system", "system"), ModelMessage("user", "goal")),
        response_schema=STEP_DECISION_SCHEMA,
        max_output_tokens=128,
        num_ctx=4096,
        temperature=0.2,
    )


# 固定供应商传输夹具的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class OllamaProviderTests(unittest.TestCase):
    # 回归断言：固定供应商替身核对统一 schema 和计量字段；不等同真实后端集成。
    def test_usage_and_schema_are_forwarded(self) -> None:
        captured = {}

        # 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return FakeResponse(
                {
                    "message": {"role": "assistant", "content": "{}"},
                    "prompt_eval_count": 12,
                    "eval_count": 7,
                    "total_duration": 99,
                }
            )

        with patch("myth.providers.ollama.open_credential_request", side_effect=fake_urlopen):
            result = OllamaProvider().invoke(request_obj())
        self.assertEqual(captured["body"]["format"], STEP_DECISION_SCHEMA)
        self.assertEqual(captured["body"]["stream"], False)
        self.assertEqual(captured["body"]["keep_alive"], "5m")
        self.assertEqual(captured["body"]["options"]["num_ctx"], 4096)
        self.assertEqual(captured["body"]["options"]["temperature"], 0.2)
        self.assertEqual(result.usage["input_tokens"], 12)
        self.assertEqual(result.usage["output_tokens"], 7)

    # 回归断言：供应商明确上下文拒绝作为已知失败，不能与超时 UNKNOWN 混用。
    def test_context_ceiling_is_reported_as_known_failure(self) -> None:
        # 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def fake_urlopen(req, timeout):
            return FakeResponse(
                {
                    "message": {"role": "assistant", "content": "{}"},
                    "prompt_eval_count": 4090,
                    "eval_count": 2,
                }
            )

        with patch("myth.providers.ollama.open_credential_request", side_effect=fake_urlopen):
            with self.assertRaises(ContextTruncated) as caught:
                OllamaProvider().invoke(request_obj())
        self.assertEqual(caught.exception.usage["input_tokens"], 4090)
        self.assertEqual(caught.exception.usage["output_tokens"], 2)
        self.assertEqual(caught.exception.raw["prompt_eval_count"], 4090)


# 固定供应商传输夹具的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class OpenAIProviderTests(unittest.TestCase):
    # 回归断言：固定 SSE 夹具核对输出与终结事实，token 不进入 ModelResult。
    def test_chatgpt_plan_streams_and_does_not_persist_token(self) -> None:
        captured = {}
        completed = {
            "id": "resp_1",
            "status": "completed",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "{}"}]}
            ],
            "usage": {
                "input_tokens": 8,
                "output_tokens": 4,
                "input_tokens_details": {"cached_tokens": 5},
            },
        }

        # 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def fake_urlopen(req, timeout):
            captured["auth"] = req.headers.get("Authorization") or req.headers.get(
                "authorization"
            )
            captured["body"] = json.loads(req.data)
            return FakeStreamResponse(
                [
                    {"type": "response.output_text.delta", "delta": "{}"},
                    {"type": "response.completed", "response": completed},
                ]
            )

        provider = OpenAIResponsesProvider(
            provider_id="chatgpt",
            token_supplier=lambda: "secret-token",
            chatgpt_plan=True,
            auth_type="oauth",
        )
        with patch("myth.providers.openai.open_credential_request", side_effect=fake_urlopen):
            result = provider.invoke(request_obj())
        self.assertEqual(captured["auth"], "Bearer secret-token")
        self.assertTrue(captured["body"]["stream"])
        self.assertFalse(captured["body"]["store"])
        self.assertNotIn("max_output_tokens", captured["body"])
        self.assertNotIn("secret-token", json.dumps(result.raw))
        self.assertEqual(result.usage["input_tokens"], 8)
        self.assertEqual(result.usage["cached_input_tokens"], 5)

    # 回归断言：推理模型公开摘要/推理 Token 被保留为可观察证据，但不冒充原始 Chain-of-Thought。
    def test_reasoning_summary_and_cost_are_observable(self) -> None:
        captured = {}
        completed = {
            "id": "resp_reasoning",
            "status": "completed",
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [
                        {
                            "type": "summary_text",
                            "text": "先定位最小相关范围，再验证候选修改。",
                        }
                    ],
                    "encrypted_content": "opaque-secret-state",
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "{}"}],
                },
            ],
            "usage": {
                "input_tokens": 20,
                "output_tokens": 12,
                "output_tokens_details": {"reasoning_tokens": 7},
            },
        }

        # 固定供应商传输夹具的局部夹具协作；只核对公开摘要合同，不模拟隐藏思维。
        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return FakeStreamResponse(
                [{"type": "response.completed", "response": completed}]
            )

        request = ModelRequest(
            model="gpt-5-demo",
            messages=(ModelMessage("system", "system"), ModelMessage("user", "goal")),
            response_schema=STEP_DECISION_SCHEMA,
            max_output_tokens=128,
            thinking=True,
        )
        provider = OpenAIResponsesProvider(
            provider_id="chatgpt",
            token_supplier=lambda: "secret-token",
            chatgpt_plan=True,
            auth_type="oauth",
        )
        with patch(
            "myth.providers.openai.open_credential_request",
            side_effect=fake_urlopen,
        ):
            result = provider.invoke(request)

        self.assertEqual(captured["body"]["reasoning"]["summary"], "auto")
        self.assertEqual(result.usage["reasoning_tokens"], 7)
        self.assertEqual(
            result.raw["reasoning_summary"],
            ["先定位最小相关范围，再验证候选修改。"],
        )
        self.assertNotIn("opaque-secret-state", json.dumps(result.raw))

    # 回归断言：缺完整 SSE 终结事件不能把局部文本当成功。
    def test_chatgpt_plan_requires_completed_terminal_event(self) -> None:
        provider = OpenAIResponsesProvider(
            provider_id="chatgpt",
            token_supplier=lambda: "secret-token",
            chatgpt_plan=True,
            auth_type="oauth",
        )
        with patch(
            "myth.providers.openai.open_credential_request",
            return_value=FakeStreamResponse(
                [{"type": "response.output_text.delta", "delta": "partial"}]
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "without response.completed"):
                provider.invoke(request_obj())

    # 回归断言：API key 传输包含明确输出上限，不默默突破预算。
    def test_api_key_path_includes_max_output_tokens(self) -> None:
        captured = {}

        # 固定供应商传输夹具的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return FakeResponse(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "{}"}],
                        }
                    ],
                    "usage": {},
                }
            )

        provider = OpenAIResponsesProvider(
            provider_id="openai",
            token_supplier=lambda: "sk-test",
            chatgpt_plan=False,
        )
        with patch("myth.providers.openai.open_credential_request", side_effect=fake_urlopen):
            provider.invoke(request_obj())
        self.assertEqual(captured["body"]["max_output_tokens"], 128)



# DeepSeek Responses 适配器回归；固定 wire 夹具证明角色/thinking/usage/脱敏边界，不等同真实远端可用性。
class DeepSeekProviderTests(unittest.TestCase):
    # 缺失 key 属派发前已知未就绪；公开模型目录仍可供 UI 选择，不泄露任何凭据。
    def test_check_reports_env_key_and_public_models(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            status = DeepSeekApiKeyProvider().check()
        self.assertFalse(status.ready)
        self.assertEqual(status.provider_id, "deepseek")
        self.assertEqual(status.auth_type, "api_key")
        self.assertIn("DEEPSEEK_API_KEY", status.details["error"])

        catalog = {
            "object": "list",
            "data": [
                {
                    "id": "deepseek-flash",
                    "name": "DeepSeek-V4.1-Flash",
                    "context_window": 1048576,
                    "max_output_tokens": 393216,
                    "input_modalities": ["text", "image"],
                    "output_modalities": ["text"],
                    "effort": {
                        "supported_levels": ["low", "high", "max"],
                        "default_level": "high",
                    },
                }
            ],
        }
        with (
            patch.dict("os.environ", {"DEEPSEEK_API_KEY": "ds-secret"}, clear=True),
            patch(
                "myth.providers.deepseek.open_credential_request",
                return_value=FakeResponse(catalog),
            ),
        ):
            ready = DeepSeekApiKeyProvider().check()
        self.assertTrue(ready.ready)
        self.assertEqual(ready.details["endpoint"], "https://api.deepseek.com")
        profile = ready.details["model_capabilities"]["deepseek-flash"]
        self.assertEqual(profile["reasoning"]["levels"], ["low", "high", "max"])
        self.assertEqual(profile["reasoning"]["default"], "high")
        self.assertEqual(profile["reasoning"]["off"], "none")
        self.assertEqual(profile["context_window"], 1048576)
        self.assertEqual(profile["max_output_tokens"], 393216)

    # DeepSeek 的 developer 会退化为 user，因此 system 必须原样发送；thinking 显式映射到 reasoning.effort。
    def test_request_preserves_system_role_and_maps_thinking(self) -> None:
        captured = {}
        completed = {
            "id": "resp_ds",
            "status": "completed",
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_ds",
                    "status": "completed",
                    "content": [
                        {"type": "reasoning_text", "text": "private reasoning body"}
                    ],
                    "summary": [],
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "{}"}],
                },
            ],
            "usage": {
                "input_tokens": 21,
                "input_tokens_details": {"cached_tokens": 8},
                "output_tokens": 13,
                "output_tokens_details": {"reasoning_tokens": 9},
            },
        }

        # 固定 DeepSeek HTTP/SSE 替身只捕获 wire 请求并返回终结事件；不代表真实远端连通或模型质量。
        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["auth"] = req.headers.get("Authorization") or req.headers.get(
                "authorization"
            )
            captured["body"] = json.loads(req.data)
            return FakeStreamResponse(
                [{"type": "response.completed", "response": completed}]
            )

        request = ModelRequest(
            model="deepseek-v4-pro",
            messages=(
                ModelMessage("system", "system"),
                ModelMessage("user", "goal"),
            ),
            response_schema=STEP_DECISION_SCHEMA,
            max_output_tokens=256,
            thinking="max",
            temperature=0.3,
        )
        with (
            patch.dict("os.environ", {"DEEPSEEK_API_KEY": "ds-secret"}, clear=True),
            patch(
                "myth.providers.openai.open_credential_request",
                side_effect=fake_urlopen,
            ),
        ):
            result = DeepSeekApiKeyProvider().invoke(request)

        self.assertEqual(captured["url"], "https://api.deepseek.com/responses")
        self.assertEqual(captured["auth"], "Bearer ds-secret")
        self.assertEqual(captured["body"]["input"][0]["role"], "system")
        self.assertEqual(captured["body"]["reasoning"], {"effort": "max"})
        self.assertEqual(captured["body"]["temperature"], 0.3)
        self.assertEqual(captured["body"]["max_output_tokens"], 256)
        self.assertEqual(result.usage["cached_input_tokens"], 8)
        self.assertEqual(result.usage["reasoning_tokens"], 9)
        self.assertNotIn("private reasoning body", json.dumps(result.raw))
        self.assertNotIn("ds-secret", json.dumps(result.raw))

    # thinking=False 明确关闭 DeepSeek 默认思考，避免 UI 关闭开关却仍产生 reasoning token。
    def test_false_thinking_maps_to_none_effort(self) -> None:
        provider = DeepSeekApiKeyProvider()
        request = ModelRequest(
            model="deepseek-flash",
            messages=(ModelMessage("user", "goal"),),
            response_schema=STEP_DECISION_SCHEMA,
            thinking=False,
        )
        self.assertEqual(provider._reasoning_options(request), {"effort": "none"})


# 能力投影只验证 Provider 原生值，不建立跨厂商 effort 对照表。
class AdaptiveCapabilityTests(unittest.TestCase):
    # DeepSeek 原生档位必须原样通过；不存在的 medium 不应被 Myth 悄悄映射成 high。
    def test_deepseek_does_not_cross_map_reasoning_levels(self) -> None:
        provider = DeepSeekApiKeyProvider()
        request = ModelRequest(
            model="deepseek-flash",
            messages=(ModelMessage("user", "goal"),),
            response_schema=STEP_DECISION_SCHEMA,
            thinking="medium",
        )
        self.assertEqual(provider._reasoning_options(request), {"effort": "medium"})
