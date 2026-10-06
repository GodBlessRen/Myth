"""Claude 公开元数据回归：只用固定假 token，验证字段形状与字面回显边界。

网络交换和凭据库为替身，公开文件真实写入；不证明远端行为、任意编码秘密检测
或 keyring/文件/网络的跨系统事务。当前可观察的客户端切换必须在保存前拒绝。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib import parse

from myth.auth.claude import ClaudeOAuthError, ClaudeOAuthManager
from test_claude_login_lifecycle import MemoryCredentials


class ClaudePublicMetadataTests(unittest.TestCase):
    """通过真实公开文件、公开 status 和内存凭据副本检查保真与脱敏。"""

    def setUp(self) -> None:
        """每个用例拥有独立目录和环境，禁止从真实账户加载凭据。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"MYTH_CLAUDE_OAUTH_CLIENT_ID": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.store = MemoryCredentials()
        self.manager = ClaudeOAuthManager(self.root, credential_store=self.store)
        self.manager.configure("myth-a")

    def response(self) -> dict:
        """返回合法形状的非真实 token；它们只用于验证不可流入公开文件。"""
        return {"access_token": "fixture-new-access", "refresh_token": "fixture-new-refresh",
                "expires_in": 3600, "scope": "user:inference"}

    def login(self, response: dict):
        """走完整管理器回调，只在外部交换边界注入响应。"""
        attempt = self.manager.begin_login("http://127.0.0.1:45678/auth/claude/callback")
        state = parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)["state"][0]
        with patch.object(self.manager, "_token_exchange", return_value=response):
            return self.manager.complete_callback({"state": [state], "code": ["fixture-code"]})

    def public_text(self) -> str:
        """拼接真实公开文件和公开状态；不读取或打印凭据正文。"""
        return self.manager.metadata_path.read_text("utf-8") + json.dumps(self.manager.status().serializable())

    def test_callback_echoed_tokens_never_enter_public_fields(self) -> None:
        """白名单字段可能回显 token；字段名正确不能代替内容脱敏。"""
        response = self.response()
        response["account"] = {"email_address": "prefix " + response["access_token"]}
        response["organization"] = {"name": "prefix " + response["refresh_token"]}
        response["scope"] += " " + response["access_token"]
        self.login(response)
        public = self.public_text()
        for key in ("access_token", "refresh_token"):
            self.assertNotIn(response[key], public)
            self.assertEqual(self.store.load("default")[key], response[key])
        self.assertIn("[REDACTED]", public)

    def test_nested_account_fields_are_not_serialized_as_public_metadata(self) -> None:
        """账号展示字段只接受字符串，不能把任意嵌套响应对象整块写入。"""
        response = self.response()
        response["account"] = {"email_address": {"unrelated_secret": "fixture-nested-secret"}}
        response["organization"] = {"name": ["fixture-nested-secret"]}
        response["workspace"] = {"name": 123}
        status = self.login(response)
        self.assertNotIn("fixture-nested-secret", self.public_text())
        self.assertIsNone(status.email)
        self.assertIsNone(status.organization)
        self.assertIsNone(status.workspace)
        self.assertTrue(status.connected)

    def test_status_redacts_current_credential_echo_without_mutating_store(self) -> None:
        """即使安全库的公开 scope 异常，也不能把当前 token 带进 Web JSON。"""
        credential = {**self.response(), "client_id": "myth-a", "expires_at": time.time() + 3600}
        credential["scope"] = "user:inference " + credential["refresh_token"]
        self.store.save("default", credential)
        status = self.manager.status()
        self.assertNotIn(credential["refresh_token"], json.dumps(status.serializable()))
        self.assertEqual(self.store.load("default"), credential)

    def test_refresh_redacts_old_and_new_token_echoes(self) -> None:
        """轮换响应可能回显旧 refresh token，脱敏必须同时包含旧、新凭据。"""
        old = {"access_token": "fixture-old-access", "refresh_token": "fixture-old-refresh",
               "client_id": "myth-a", "expires_at": time.time() - 1, "scope": "user:inference"}
        self.store.save("default", old)
        response = self.response()
        response["account"] = {"email_address": old["refresh_token"] + " " + response["access_token"]}
        response["organization"] = {"name": old["access_token"] + " " + response["refresh_token"]}
        response["scope"] += " " + old["refresh_token"]
        with patch.object(self.manager, "_read_token_response", return_value=response):
            self.assertEqual(self.manager.access_token(), response["access_token"])
        for source in (old, response):
            for key in ("access_token", "refresh_token"):
                self.assertNotIn(source[key], self.public_text())
        self.assertEqual(self.store.load("default")["refresh_token"], response["refresh_token"])

    def test_visible_client_change_during_refresh_is_rejected_before_save(self) -> None:
        """刷新期间已经可见的客户端切换也要核对，不能保存迟到的旧绑定。"""
        old = {"access_token": "fixture-old-access", "refresh_token": "fixture-old-refresh",
               "client_id": "myth-a", "expires_at": time.time() - 1}
        self.store.save("default", old)
        other = ClaudeOAuthManager(self.root, credential_store=self.store)

        def changed(*args):
            """在响应边界注入已落盘变更；本用例不声称任意跨进程竞争都已解决。"""
            other.configure("myth-b")
            return self.response()

        with patch.object(self.manager, "_read_token_response", side_effect=changed):
            with self.assertRaises(ClaudeOAuthError):
                self.manager.access_token()
        self.assertIsNone(self.store.load("default"))
        self.assertEqual(json.loads(self.manager.metadata_path.read_text("utf-8"))["client_id"], "myth-b")

    def test_normal_account_labels_and_scopes_are_preserved(self) -> None:
        """正常中英文展示信息原样保留；脱敏不删除可用账号与真实 scope。"""
        response = self.response()
        response.update({"account": {"email_address": "person@example.com"},
                         "organization": {"name": "测试组织"}, "workspace": {"id": "space-one"}})
        status = self.login(response)
        self.assertEqual(status.email, "person@example.com")
        self.assertEqual(status.organization, "测试组织")
        self.assertEqual(status.workspace, "space-one")
        self.assertEqual(status.scopes, ("user:inference",))
        self.assertNotIn("access_token", self.manager.metadata_path.read_text("utf-8"))

    def test_callback_code_and_verifier_echoes_are_not_public(self) -> None:
        """一次性授权码和 PKCE verifier 同样是秘密，不能被账号响应字段带进公开文件。"""
        attempt = self.manager.begin_login("http://127.0.0.1:45678/auth/claude/callback")
        state = parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)["state"][0]
        echoed = []

        def echo(pending, code, state_value):
            """在真实交换边界捕获测试挑战，只构造字面回显，不访问网络。"""
            echoed.extend((code, pending["verifier"]))
            response = self.response()
            response["account"] = {"email_address": code}
            response["organization"] = {"name": pending["verifier"]}
            return response

        with patch.object(self.manager, "_token_exchange", side_effect=echo):
            self.manager.complete_callback({"state": [state], "code": ["fixture-code"]})
        for secret in echoed:
            self.assertNotIn(secret, self.public_text())

    def test_non_string_scope_is_not_stringified_into_public_json(self) -> None:
        """异常 scope 对象不能先 str() 再绕过公开字段的类型约束。"""
        response = self.response()
        response["scope"] = {"unrelated_secret": "fixture-unrelated-secret"}
        status = self.login(response)
        self.assertEqual(status.scopes, ())
        self.assertNotIn("fixture-unrelated-secret", self.public_text())
        credential = self.store.load("default")
        credential["scope"] = ["fixture-other-secret"]
        self.store.save("default", credential)
        self.assertEqual(self.manager.status().scopes, ())
        self.assertNotIn("fixture-other-secret", self.public_text())

    def test_unknown_expiry_and_empty_scope_do_not_reuse_stale_metadata(self) -> None:
        """凭据事实为 None/0 或空 scope 时，公开缓存不得覆盖权威事实。"""
        self.manager._save_metadata({"client_id": "myth-a", "scope": "user:profile", "expires_at": 9999999999})
        for expires_at in (None, 0):
            with self.subTest(expires_at=expires_at):
                credential = {**self.response(), "client_id": "myth-a", "expires_at": expires_at, "scope": ""}
                self.store.save("default", credential)
                status = self.manager.status()
                self.assertEqual(status.expires_at, expires_at)
                self.assertEqual(status.scopes, ())

    def test_refresh_preserves_unknown_scope_when_response_omits_it(self) -> None:
        """刷新没补充 scope 时沿用原事实，不能把未知范围补成全部请求范围。"""
        credential = {**self.response(), "client_id": "myth-a", "expires_at": 0, "scope": ""}
        self.store.save("default", credential)
        response = self.response()
        del response["scope"]
        with patch.object(self.manager, "_read_token_response", return_value=response):
            self.manager.access_token()
        self.assertEqual(self.store.load("default")["scope"], "")
        self.assertEqual(self.manager.status().scopes, ())
