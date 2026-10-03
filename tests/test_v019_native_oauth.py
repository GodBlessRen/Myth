"""回归边界：独立 OAuth 边界与安全存储。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib import error, parse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from myth.auth.chatgpt import (
    ChatGPTAuthManager,
    ChatGPTOAuthError,
    DYNAMIC_CLIENT_ID,
    ISSUER,
    KeyringCredentialStore,
    RESOURCE,
)


# 独立 OAuth 边界与安全存储的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class MemoryCredentialStore:
    # 保存可控测试条件；这些字段属于替身，不模拟远端真实保证。
    def __init__(self):
        self.values = {}

    # 读取测试内存凭据；只模拟存储接口，不证明 OS 安全后端可用。
    def load(self, profile_id):
        value = self.values.get(profile_id)
        return dict(value) if value else None

    # 保存测试内存凭据并保留调用事实；不是生产秘钥存储。
    def save(self, profile_id, value):
        self.values[profile_id] = dict(value)

    # 删除测试内存凭据，供退出/重授权边界核对。
    def delete(self, profile_id):
        self.values.pop(profile_id, None)


# 独立 OAuth 边界与安全存储的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class NativeOAuthTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = MemoryCredentialStore()
        self.manager = ChatGPTAuthManager(self.root, credential_store=self.store)

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        self.tmp.cleanup()

    # 回归断言：登录创建随机 PKCE/state/nonce，动态注册使用稳定本机身份。
    def test_begin_login_uses_dynamic_registration_pkce_nonce_and_stable_host(self):
        redirect = "http://127.0.0.1:45678/auth/callback"
        first = self.manager.begin_login(redirect)
        query = parse.parse_qs(parse.urlparse(first["auth_url"]).query)
        self.assertEqual(query["client_id"], [DYNAMIC_CLIENT_ID])
        self.assertEqual(query["redirect_uri"], [redirect])
        self.assertEqual(query["resource"], [RESOURCE])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertIn("chatgpt.tokens.use.direct", query["scope"][0])
        self.assertIn("nonce", query)
        self.assertIn("state", query)
        self.assertTrue(query["ext_agent_host_id"][0].startswith("urn:uuid:"))
        second = self.manager.begin_login(redirect)
        query2 = parse.parse_qs(parse.urlparse(second["auth_url"]).query)
        self.assertEqual(query["ext_agent_host_id"], query2["ext_agent_host_id"])
        self.assertNotEqual(query["state"], query2["state"])
        self.assertNotEqual(query["nonce"], query2["nonce"])

    # 回归断言：合法回调先校验身份再保存系统凭据；元数据不含 token。
    def test_dynamic_callback_saves_registration_then_verified_credentials_without_metadata_secrets(
        self,
    ):
        redirect = "http://127.0.0.1:45678/auth/callback"
        attempt = self.manager.begin_login(redirect)
        state = parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)["state"][0]
        pending = self.manager._pending[state]
        tokens = {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "id_token": "id-secret",
            "expires_in": 3600,
            "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
        }
        with (
            patch.object(self.manager, "_token_request", return_value=tokens),
            patch.object(
                self.manager,
                "_verify_id_token",
                return_value={
                    "sub": "subject-1",
                    "email": "user@example.com",
                    "name": "User",
                },
            ),
        ):
            status = self.manager.complete_callback(
                {
                    "state": state,
                    "code": "one-time-code",
                    "client_id": "oaiapp_issued_123",
                }
            )
        self.assertTrue(status.ready)
        self.assertTrue(status.sharing)
        self.assertEqual(status.email, "user@example.com")
        metadata = self.manager.metadata_path.read_text(encoding="utf-8")
        for secret in (
            "access-secret",
            "refresh-secret",
            "id-secret",
            "one-time-code",
            state,
            pending.nonce,
            pending.code_verifier,
        ):
            self.assertNotIn(secret, metadata)
        profile_id = status.profile_id
        self.assertEqual(self.store.values[profile_id]["access_token"], "access-secret")

    # 回归断言：未知 OAuth state 在 token exchange 前拒绝，避免消费伪造回调。
    def test_unknown_state_is_rejected_before_exchange(self):
        with patch.object(self.manager, "_token_request") as exchange:
            with self.assertRaisesRegex(ChatGPTOAuthError, "state"):
                self.manager.complete_callback(
                    {"state": "forged", "code": "code", "client_id": "oaiapp_x"}
                )
        exchange.assert_not_called()

    # 回归断言：原账号重新登录不能交换成另一 client_id。
    def test_returning_login_rejects_client_id_swap(self):
        redirect = "http://127.0.0.1:45678/auth/callback"
        first = self.manager.begin_login(redirect)
        state = parse.parse_qs(parse.urlparse(first["auth_url"]).query)["state"][0]
        tokens = {
            "access_token": "a",
            "refresh_token": "r",
            "id_token": "i",
            "expires_in": 3600,
            "scope": "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
        }
        with (
            patch.object(self.manager, "_token_request", return_value=tokens),
            patch.object(
                self.manager,
                "_verify_id_token",
                return_value={"sub": "sub", "email": "a@example.com"},
            ),
        ):
            status = self.manager.complete_callback(
                {"state": state, "code": "c", "client_id": "oaiapp_original"}
            )
        second = self.manager.begin_login(redirect, profile_id=status.profile_id)
        state2 = parse.parse_qs(parse.urlparse(second["auth_url"]).query)["state"][0]
        with self.assertRaisesRegex(ChatGPTOAuthError, "different client"):
            self.manager.complete_callback(
                {
                    "state": state2,
                    "code": "c2",
                    "client_id": "oaiapp_attacker",
                }
            )

    # 回归断言：刷新轮转凭据仍绑定同 profile；固定替身不证明真实服务连通。
    def test_refresh_rotates_token_under_same_profile(self):
        profile_id = self.manager._persist_registration("oaiapp_refresh")
        metadata = self.manager._load_metadata()
        metadata["profiles"][profile_id].update(
            {"subject": "sub", "email": "u@example.com", "status": "connected"}
        )
        metadata["active_profile_id"] = profile_id
        self.manager._save_metadata(metadata)
        self.store.save(
            profile_id,
            {
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "id_token": "id",
                "expires_at": int(time.time()) - 1,
                "scope": "openid resource.invoke chatgpt.tokens.use.direct",
                "subject": "sub",
                "client_id": "oaiapp_refresh",
            },
        )
        with patch.object(
            self.manager,
            "_token_request",
            return_value={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
        ):
            self.assertEqual(self.manager.access_token(), "new-access")
        self.assertEqual(self.store.values[profile_id]["refresh_token"], "new-refresh")

    # 回归断言：真实签名夹具核对 issuer/audience/nonce，拒绝未验证 claims。
    def test_id_token_verification_checks_signature_issuer_audience_and_nonce(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        now = int(time.time())
        token = jwt.encode(
            {
                "iss": ISSUER,
                "aud": "oaiapp_verified",
                "sub": "subject",
                "exp": now + 600,
                "iat": now,
                "nonce": "nonce-123",
                "email": "user@example.com",
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )

        # 独立 OAuth 边界与安全存储的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
        class SigningKey:
            key = public_key

        with patch.object(
            self.manager._jwks, "get_signing_key_from_jwt", return_value=SigningKey()
        ):
            claims = self.manager._verify_id_token(
                token,
                client_id="oaiapp_verified",
                nonce="nonce-123",
            )
            self.assertEqual(claims["sub"], "subject")
            with self.assertRaisesRegex(ChatGPTOAuthError, "verification failed"):
                self.manager._verify_id_token(
                    token,
                    client_id="oaiapp_wrong",
                    nonce="nonce-123",
                )
            with self.assertRaisesRegex(ChatGPTOAuthError, "nonce mismatch"):
                self.manager._verify_id_token(
                    token,
                    client_id="oaiapp_verified",
                    nonce="wrong-nonce",
                )

    # 回归断言：不可证明为安全系统后端时拒绝存储，不降级为明文。
    def test_keyring_store_fails_closed_for_unapproved_backend(self):
        # 独立 OAuth 边界与安全存储的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
        class InsecureBackend:
            priority = 10

        store = KeyringCredentialStore()
        with patch(
            "myth.auth.chatgpt.keyring.get_keyring", return_value=InsecureBackend()
        ):
            with self.assertRaisesRegex(
                ChatGPTOAuthError, "secure OS credential store"
            ):
                store.load("profile")

    # 回归断言：远端拒绝码可公开，原始描述/敏感响应不透传日志和 UI。
    def test_oauth_http_error_never_echoes_provider_description(self):
        body = b'{"error":"invalid_grant","error_description":"refresh-secret-should-not-leak"}'
        rejected = error.HTTPError(
            "https://auth.openai.com/token",
            400,
            "Bad Request",
            {},
            io.BytesIO(body),
        )
        with patch("myth.auth.chatgpt.open_credential_request", side_effect=rejected):
            with self.assertRaises(ChatGPTOAuthError) as caught:
                self.manager._token_request({"grant_type": "refresh_token"})
        message = str(caught.exception)
        self.assertIn("invalid_grant", message)
        self.assertNotIn("refresh-secret-should-not-leak", message)

    # 回归断言：远端撤销未确认仍可清本地凭据，保留两项不同事实。
    def test_logout_clears_local_tokens_even_if_remote_revocation_is_unconfirmed(self):
        profile_id = self.manager._persist_registration("oaiapp_logout")
        metadata = self.manager._load_metadata()
        metadata["active_profile_id"] = profile_id
        self.manager._save_metadata(metadata)
        self.store.save(
            profile_id,
            {
                "access_token": "a",
                "refresh_token": "r",
                "id_token": "i",
                "expires_at": int(time.time()) + 3600,
                "scope": "resource.invoke chatgpt.tokens.use.direct",
                "subject": "sub",
                "client_id": "oaiapp_logout",
            },
        )
        with patch.object(
            self.manager,
            "_revoke_refresh_token",
            side_effect=ChatGPTOAuthError("network"),
        ):
            result = self.manager.logout()
        self.assertTrue(result["signed_out"])
        self.assertFalse(result["remote_revoked"])
        self.assertIsNone(self.store.load(profile_id))


if __name__ == "__main__":
    unittest.main()
