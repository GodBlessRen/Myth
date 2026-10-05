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
from myth.models import ModelRequest, Message
from myth.providers.messages import MessagesProvider


class MemoryCredentialStore:
    def __init__(self):
        self.values = {}

    def load(self, profile_id):
        value = self.values.get(profile_id)
        return dict(value) if value else None

    def save(self, profile_id, value):
        self.values[profile_id] = dict(value)

    def delete(self, profile_id):
        self.values.pop(profile_id, None)


class FakeResponse:
    def __init__(self, value):
        self.value = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, limit=-1):
        return self.value if limit < 0 else self.value[:limit]


class ClaudeOAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = MemoryCredentialStore()
        self.manager = ClaudeOAuthManager(self.root, credential_store=self.store)

    def tearDown(self):
        self.tmp.cleanup()

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

    def test_oauth_messages_use_bearer_and_beta_not_x_api_key(self):
        provider = MessagesProvider("claude_oauth", lambda: "oauth-access")
        captured = {}

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
