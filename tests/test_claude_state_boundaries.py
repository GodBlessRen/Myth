"""Claude 认证边界的故障回归：挑战、授权、轮转与根目录隔离。

真实公开文件和 OS 锁负责状态；安全库及远端响应使用替身，不读取真实账户。
测试先固定旧实现的失败，避免把接通状态、零派发和未知轮转混成同一个事实。
"""

import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib import error, parse

from myth.auth.claude import ClaudeOAuthError, ClaudeOAuthManager
from myth.network_recovery import ConnectionNotDispatched
from myth.models import ProviderUnavailable
from myth.providers.messages import MessagesProvider
from test_claude_login_lifecycle import MemoryCredentials


class ClaudeStateBoundaryTests(unittest.TestCase):
    """同一安全库可连接多个根目录；公开文件从不保存任何凭据正文。"""

    def setUp(self):
        """隔离环境和目录；只有用例创建的固定凭据进入内存安全库。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"MYTH_CLAUDE_OAUTH_CLIENT_ID": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.store = MemoryCredentials()
        self.manager = ClaudeOAuthManager(self.root / "first", credential_store=self.store)
        self.manager.configure("myth-a")
        self.redirect = "http://127.0.0.1:45678/auth/claude/callback"

    def credential_key(self, manager):
        """使用生产管理器的公开槽身份；不在夹具中猜测全应用别名。"""
        return manager.profile_id

    def authorized(self, manager=None, *, expired=False):
        """通过真实登录路径建立授权；随后只在安全库替身调整到期事实。"""
        manager = manager or self.manager
        login = manager.begin_login(self.redirect)
        state = parse.parse_qs(parse.urlsplit(login["auth_url"]).query)["state"][0]
        response = {"access_token": "fixture-access", "refresh_token": "fixture-refresh",
                    "expires_in": 3600, "scope": "user:inference"}
        with patch.object(manager, "_token_exchange", return_value=response):
            manager.complete_callback({"state": [state], "code": ["fixture-code"]})
        if expired:
            key = self.credential_key(manager)
            credential = self.store.load(key)
            credential["expires_at"] = time.time() - 1
            self.store.save(key, credential)

    def test_begin_and_denial_preserve_current_authorization(self):
        """打开另一登录页或拒绝授权，不应提前使当前已登录账户失效。"""
        self.authorized()
        original = self.store.load(self.credential_key(self.manager))
        login = self.manager.begin_login(self.redirect)
        state = parse.parse_qs(parse.urlsplit(login["auth_url"]).query)["state"][0]
        self.assertTrue(self.manager.status().connected)
        self.assertEqual(self.manager.access_token(), original["access_token"])
        with self.assertRaises(ClaudeOAuthError):
            self.manager.complete_callback({"state": [state], "error": ["access_denied"]})
        self.assertTrue(self.manager.status().connected)
        self.assertEqual(self.store.load(self.credential_key(self.manager)), original)

    def test_proven_zero_dispatch_refresh_can_retry(self):
        """只信任 connect 阶段签发的零派发证据；它不能永久占住轮转。"""
        self.authorized(expired=True)
        with patch("myth.auth.claude.open_credential_request",
                   side_effect=error.URLError(ConnectionNotDispatched())):
            with self.assertRaises(ConnectionNotDispatched):
                self.manager.access_token()
        self.assertFalse(json.loads(self.manager.metadata_path.read_text())["refresh_pending"])
        other = ClaudeOAuthManager(self.manager.root, credential_store=self.store)
        with patch.object(other, "_read_token_response", return_value={
            "access_token": "fixture-rotated-access", "refresh_token": "fixture-rotated-refresh",
            "expires_in": 3600,
        }) as exchange:
            self.assertEqual(other.access_token(), "fixture-rotated-access")
        self.assertEqual(exchange.call_count, 1)

    def test_unproven_connection_error_remains_pending_after_restart(self):
        """任意 URLError 的异常类型不含派发进度；禁止据名称重放旧 refresh token。"""
        self.authorized(expired=True)
        with patch("myth.auth.claude.open_credential_request",
                   side_effect=error.URLError(ConnectionRefusedError())):
            with self.assertRaises(ClaudeOAuthError):
                self.manager.access_token()
        other = ClaudeOAuthManager(self.manager.root, credential_store=self.store)
        with patch.object(other, "_read_token_response") as exchange:
            with self.assertRaises(ClaudeOAuthError):
                other.access_token()
        exchange.assert_not_called()
        self.assertTrue(json.loads(self.manager.metadata_path.read_text())["refresh_pending"])

    def test_zero_dispatch_refresh_allows_provider_network_recovery(self):
        """认证连接失败也发生在模型派发前；Provider 必须保留有证据的恢复分类。"""
        self.authorized(expired=True)
        provider = MessagesProvider("claude_oauth", self.manager.access_token)
        with patch("myth.auth.claude.open_credential_request",
                   side_effect=error.URLError(ConnectionNotDispatched())), \
             patch("myth.providers.messages.open_credential_request") as model_send:
            with self.assertRaises(ProviderUnavailable):
                provider._request("/messages", {})
        model_send.assert_not_called()
        self.assertFalse(json.loads(self.manager.metadata_path.read_text())["refresh_pending"])

    def test_distinct_roots_do_not_share_or_delete_credential_slot(self):
        """相同系统安全库、不同 Runtime 根必须有独立身份；配置与退出只影响自己。"""
        self.authorized()
        other = ClaudeOAuthManager(self.root / "second", credential_store=self.store)
        other.configure("myth-b")
        self.assertTrue(self.manager.status().connected)
        self.authorized(other)
        self.assertNotEqual(self.credential_key(self.manager), self.credential_key(other))
        other.logout()
        self.assertTrue(self.manager.status().connected)
        self.assertFalse(other.status().connected)

    def test_callback_state_echo_never_enters_public_projection(self):
        """回调已知 state 也属于挑战秘密；只比较是否泄漏，不打印其字面值。"""
        login = self.manager.begin_login(self.redirect)
        state = parse.parse_qs(parse.urlsplit(login["auth_url"]).query)["state"][0]
        with patch.object(self.manager, "_token_exchange", return_value={
            "access_token": "fixture-access", "refresh_token": "fixture-refresh", "expires_in": 3600,
            "account": {"email_address": state}, "scope": "user:inference " + state,
        }):
            self.manager.complete_callback({"state": [state], "code": ["fixture-code"]})
        public = self.manager.metadata_path.read_text() + json.dumps(self.manager.status().serializable())
        self.assertFalse(state in public, "callback state entered the public projection")

    def test_new_challenge_from_another_instance_invalidates_only_old_challenge(self):
        """不同实例开始新挑战时，旧回调失效，已登录授权仍保持可用。"""
        self.authorized()
        login = self.manager.begin_login(self.redirect)
        old_state = parse.parse_qs(parse.urlsplit(login["auth_url"]).query)["state"][0]
        other = ClaudeOAuthManager(self.manager.root, credential_store=self.store)
        other.begin_login(self.redirect)
        with patch.object(self.manager, "_token_exchange") as exchange:
            with self.assertRaises(ClaudeOAuthError):
                self.manager.complete_callback({"state": [old_state], "code": ["fixture-code"]})
        exchange.assert_not_called()
        self.assertTrue(other.status().connected)

    def test_relogin_redacts_echo_of_previous_credential(self):
        """重新授权的账号字段也可能回显旧凭据；当前已知秘密必须一起脱敏。"""
        self.authorized()
        login = self.manager.begin_login(self.redirect)
        state = parse.parse_qs(parse.urlsplit(login["auth_url"]).query)["state"][0]
        previous = self.store.load(self.manager.profile_id)
        with patch.object(self.manager, "_token_exchange", return_value={
            "access_token": "fixture-new-access", "refresh_token": "fixture-new-refresh", "expires_in": 3600,
            "account": {"email_address": previous["refresh_token"]},
        }):
            self.manager.complete_callback({"state": [state], "code": ["fixture-code"]})
        public = self.manager.metadata_path.read_text() + json.dumps(self.manager.status().serializable())
        self.assertFalse(previous["refresh_token"] in public, "previous credential entered public projection")

    def test_logout_serializes_with_inflight_refresh_and_stays_signed_out(self):
        """两个真实线程争抢同根 OS 锁；退出返回后旧轮转不能重新建立连接。"""
        self.authorized(expired=True)
        other = ClaudeOAuthManager(self.manager.root, credential_store=self.store)
        entered, resume, logout_entered = threading.Event(), threading.Event(), threading.Event()
        failures = []

        def response(*args):
            """固定远端窗口，只阻塞有界时间；真实线程负责互斥顺序。"""
            entered.set()
            if not resume.wait(5):
                raise RuntimeError("fixture synchronization timeout")
            return {"access_token": "fixture-new-access", "refresh_token": "fixture-new-refresh",
                    "expires_in": 3600}

        def refresh():
            """捕获线程失败类型供断言，不把任何可能敏感的异常正文写入输出。"""
            try:
                self.manager.access_token()
            except Exception as exc:
                failures.append(type(exc).__name__)

        def logout():
            """退出必须经另一个真实 manager；不能把实例锁误当共享锁。"""
            logout_entered.set()
            try:
                other.logout()
            except Exception as exc:
                failures.append(type(exc).__name__)

        with patch.object(self.manager, "_read_token_response", side_effect=response):
            worker = threading.Thread(target=refresh)
            stopper = threading.Thread(target=logout)
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                stopper.start()
                self.assertTrue(logout_entered.wait(5))
            finally:
                resume.set()
                worker.join(5)
                if stopper.ident is not None:
                    stopper.join(5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual(failures, [])
        self.assertIsNone(self.store.load(self.credential_key(other)))
        self.assertFalse(other.status().connected)
