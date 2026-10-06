"""Claude OAuth 与 bearer Messages 传输的固定回归。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib import parse

from myth.auth.claude import ClaudeOAuthManager, OAUTH_BETA
from myth.providers.messages import MessagesProvider


# 测试内存凭据端口；只隔离 OS keyring，不代表生产存储安全性。
class MemoryCredentialStore:
    # 建立每个测试独立的内存字典，不跨用例共享 token。
    def __init__(self):
        self.values = {}

    # 读取凭据副本，避免测试调用方原地修改存储事实。
    def load(self, profile_id):
        value = self.values.get(profile_id)
        return dict(value) if value else None

    # 保存凭据副本并模拟安全存储端口的覆盖语义。
    def save(self, profile_id, value):
        self.values[profile_id] = dict(value)

    # 幂等删除测试凭据，模拟退出或更换客户端身份。
    def delete(self, profile_id):
        self.values.pop(profile_id, None)


# 固定 JSON HTTP 响应替身；只验证请求映射，不模拟真实网络。
class FakeResponse:
    # 编码固定 JSON 响应供有界读取函数消费。
    def __init__(self, value):
        self.value = json.dumps(value).encode("utf-8")

    # 支持传输层上下文管理协议并返回自身。
    def __enter__(self):
        return self

    # 退出替身上下文时不吞业务异常。
    def __exit__(self, *_):
        return None

    # 按请求上限返回固定字节，模拟 HTTP response.read。
    def read(self, limit=-1):
        return self.value if limit < 0 else self.value[:limit]


# Claude OAuth PKCE、凭据分离、刷新和 bearer 传输的固定回归。
class ClaudeOAuthTests(unittest.TestCase):
    # 每个用例使用独立根目录和内存凭据，避免认证状态串扰。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = MemoryCredentialStore()
        self.manager = ClaudeOAuthManager(self.root, credential_store=self.store)

    # 清理临时根；测试凭据只存在于进程内替身。
    def tearDown(self):
        self.tmp.cleanup()

    # 登录 URL 必须使用 Myth 配置的客户端身份、PKCE 和 user:inference scope。
    def test_begin_login_uses_configured_myth_client_and_pkce(self):
        self.manager.configure("myth-client-123")
        redirect = "http://127.0.0.1:45678/auth/claude/callback"
        attempt = self.manager.begin_login(redirect)
        query = parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)
        self.assertEqual(query["client_id"], ["myth-client-123"])
        self.assertEqual(query["redirect_uri"], [redirect])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertIn("user:inference", query["scope"][0])
        self.assertNotIn("41077d10-94b8-4194-be48-d251e9eb21b4", attempt["auth_url"])

    # 回调保存 token 到凭据端口，但公开 metadata 文件绝不包含 token。
    def test_callback_keeps_tokens_out_of_public_metadata(self):
        self.manager.configure("myth-client-123")
        redirect = "http://127.0.0.1:45678/auth/claude/callback"
        attempt = self.manager.begin_login(redirect)
        state = parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)["state"][0]
        token = {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": 3600,
            "scope": "user:profile user:inference",
            "account": {"email_address": "person@example.com"},
            "organization": {"name": "Example Org"},
        }
        with patch.object(self.manager, "_token_exchange", return_value=token):
            status = self.manager.complete_callback({"state": [state], "code": ["code-secret"]})
        self.assertTrue(status.connected)
        self.assertEqual(self.store.values["default"]["access_token"], "access-secret")
        raw = self.manager.metadata_path.read_text("utf-8")
        self.assertNotIn("access-secret", raw)
        self.assertNotIn("refresh-secret", raw)
        self.assertEqual(status.email, "person@example.com")

    # 到期 token 使用原客户端绑定刷新，并发送 Anthropic OAuth beta 合同。
    def test_expiring_access_token_refreshes_with_same_client_binding(self):
        self.manager.configure("myth-client-123")
        self.store.save("default", {
            "access_token": "old-access",
            "refresh_token": "refresh-secret",
            "expires_at": time.time() - 1,
            "scope": "user:inference",
            "client_id": "myth-client-123",
        })
        refreshed = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "scope": "user:inference",
        }
        with patch.object(self.manager, "_read_token_response", return_value=refreshed) as call:
            self.assertEqual(self.manager.access_token(), "new-access")
        req = call.call_args.args[0]
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["client_id"], "myth-client-123")
        self.assertEqual(body["refresh_token"], "refresh-secret")
        self.assertEqual(req.headers["Anthropic-beta"], OAUTH_BETA)

    # Claude OAuth Messages 使用 Bearer+beta，不混入 API Key 认证头。
    def test_oauth_messages_use_bearer_and_beta_not_x_api_key(self):
        provider = MessagesProvider("claude_oauth", lambda: "oauth-access")
        captured = {}

        # 捕获真实 Request 头并返回固定目录响应，验证认证映射。
        def fake_open(req, timeout):
            captured["authorization"] = req.headers.get("Authorization")
            captured["x_api_key"] = req.headers.get("X-api-key")
            captured["beta"] = req.headers.get("Anthropic-beta")
            return FakeResponse({
                "data": [{"id": "claude-test"}],
            })

        with patch("myth.providers.messages.open_credential_request", side_effect=fake_open):
            status = provider.check()
        self.assertTrue(status.ready)
        self.assertEqual(status.auth_type, "oauth")
        self.assertEqual(captured["authorization"], "Bearer oauth-access")
        self.assertIsNone(captured["x_api_key"])
        self.assertEqual(captured["beta"], OAUTH_BETA)


if __name__ == "__main__":
    unittest.main()
