"""Claude/Kimi 官方协议形状的传输合同回归；固定 HTTP 替身不证明账号可用性。"""

import io
import json
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from myth.models import ModelMessage, ModelRequest, ProviderKnownFailure, ProviderUnavailable, STEP_DECISION_SCHEMA
from myth.network_recovery import ConnectionNotDispatched
from myth.providers.messages import MessagesProvider
from myth.providers import create_provider
from test_workspace import decision


class MessagesProviderTests(unittest.TestCase):
    """断言实际 URL、认证头、JSON、用量、脱敏与故障分类。"""

    def request(self):
        """供应商无关请求包含系统约束、普通消息和结果 Schema。"""
        return ModelRequest("fixture-model", (ModelMessage("system", "系统约束"), ModelMessage("user", "任务")), STEP_DECISION_SCHEMA)

    def response(self, value):
        """BytesIO 实现传输读取与上下文管理，响应从不接触真实账号。"""
        return io.BytesIO(json.dumps(value).encode())

    def test_claude_system_tool_output_usage_and_redaction(self):
        """Claude 系统角色上提且强制单工具输出；缓存输入计入总量，密钥回显被遮蔽。"""
        secret = "fixture-secret-abcdef"
        provider = create_provider("anthropic", runtime_root="unused", token_supplier=lambda: secret)
        value = {"id": "message-" + secret, "stop_reason": "tool_use", "content": [
            {"type": "tool_use", "name": "myth_decision", "input": json.loads(decision(claim=secret))}],
            "usage": {"input_tokens": 5, "output_tokens": 10, "cache_read_input_tokens": 20, "cache_creation_input_tokens": 3}}
        with patch("myth.providers.messages.open_credential_request", return_value=self.response(value)) as send:
            result = provider.invoke(self.request())
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), secret)
        self.assertEqual(payload["system"], "系统约束")
        self.assertEqual([x["role"] for x in payload["messages"]], ["user"])
        self.assertEqual(payload["tool_choice"]["name"], "myth_decision")
        self.assertEqual(result.usage["input_tokens"], 28)
        self.assertNotIn(secret, str(result))

    def test_kimi_chat_usage_and_hidden_reasoning_excluded(self):
        """Kimi 使用 Chat Completions/JSON mode，输出只保留答案而非隐藏推理。"""
        provider = MessagesProvider("kimi", lambda: "fixture-secret")
        value = {"id": "chat-1", "choices": [{"finish_reason": "stop", "message": {
            "content": decision(), "reasoning_content": "private-thought"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 34}}
        with patch("myth.providers.messages.open_credential_request", return_value=self.response(value)) as send:
            result = provider.invoke(self.request())
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(send.call_args.args[0].full_url, "https://api.moonshot.ai/v1/chat/completions")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(result.usage, {"model_calls": 1, "input_tokens": 12, "output_tokens": 34})
        self.assertNotIn("private-thought", str(result))

    def test_missing_usage_and_incomplete_response(self):
        """缺测保持空；截断不是可交付子结果，仍保留已经测得的费用。"""
        provider = MessagesProvider("kimi", lambda: "fixture-secret")
        value = {"choices": [{"finish_reason": "length", "message": {"content": "{"}}], "usage": {"completion_tokens": 128}}
        with patch("myth.providers.messages.open_credential_request", return_value=self.response(value)):
            with self.assertRaises(ProviderKnownFailure) as failed:
                provider.invoke(self.request())
        self.assertEqual(failed.exception.usage, {"model_calls": 1, "output_tokens": 128})

    def test_failure_classification_no_credential_echo(self):
        """连接前断开可证明未派发；读取超时/5xx 不可推断无费用或重试。"""
        provider = MessagesProvider("kimi", lambda: "fixture-secret")
        cases = [(URLError(ConnectionNotDispatched()), ProviderUnavailable),
                 (TimeoutError("fixture-secret"), RuntimeError),
                 (HTTPError("url", 500, "fixture-secret", {}, None), RuntimeError),
                 (HTTPError("url", 401, "fixture-secret", {}, None), ProviderKnownFailure)]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__), patch("myth.providers.messages.open_credential_request", side_effect=error):
                with self.assertRaises(expected) as failed:
                    provider.invoke(self.request())
                self.assertNotIn("fixture-secret", str(failed.exception))

    def test_catalog_is_actual_read_and_auth_failure_is_not_ready(self):
        """目录成功需要真实响应结构，失败不能返回虚构支持模型。"""
        provider = MessagesProvider("anthropic", lambda: "fixture-secret")
        with patch("myth.providers.messages.open_credential_request", return_value=self.response({"data": [{"id": "fixture-model"}]})):
            self.assertEqual(provider.check().details["models"], ["fixture-model"])
        with patch("myth.providers.messages.open_credential_request", side_effect=TimeoutError()):
            self.assertFalse(provider.check().ready)
