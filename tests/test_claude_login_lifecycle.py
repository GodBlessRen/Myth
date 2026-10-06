"""Claude 登录生命周期回归。

凭据用内存端口，token exchange 用固定响应；公开元数据走真实 atomic_write。
测试本实例串行化及已可观察的客户端变化，不证明跨进程认证事务或供应商可用性。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib import parse

from myth.auth.claude import ClaudeOAuthError, ClaudeOAuthManager, LOGIN_TTL_SECONDS


class MemoryCredentials:
    """每个用例独立的 CredentialStore 替身，不读取本机账户或任何真实 token。"""

    def __init__(self) -> None:
        """由用例拥有内存状态；生产 Manager 仍负责串行读改写。"""
        self.values: dict[str, dict] = {}

    def load(self, profile_id: str) -> dict | None:
        """返回副本，避免调用者原地改动持久凭据的测试事实。"""
        value = self.values.get(profile_id)
        return dict(value) if value else None

    def save(self, profile_id: str, value: dict) -> None:
        """模拟安全凭据端口的一次覆盖；不代表真实 keyring 原子性。"""
        self.values[profile_id] = dict(value)

    def delete(self, profile_id: str) -> None:
        """模拟幂等删除；失败窗口由具体用例在端口边界注入。"""
        self.values.pop(profile_id, None)


class ClaudeLoginLifecycleTests(unittest.TestCase):
    """通过授权 URL、回调结果、存储事实与网络调用次数验证身份边界。"""

    def setUp(self) -> None:
        """隔离环境变量、根目录和凭据；清理只撤销本用例拥有的替身。"""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {"MYTH_CLAUDE_OAUTH_CLIENT_ID": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.store = MemoryCredentials()
        self.manager = ClaudeOAuthManager(self.root, credential_store=self.store)
        self.redirect = "http://127.0.0.1:45678/auth/claude/callback"

    def token_response(self) -> dict:
        """固定的非真实授权响应；任何用例都不得联到供应商换取 token。"""
        return {"access_token": "fixture-access", "refresh_token": "fixture-refresh",
                "expires_in": 3600, "scope": "user:inference"}

    def credential(self, client: str = "myth-a") -> dict:
        """构造有明确客户端身份的测试凭据，默认尚未到刷新窗口。"""
        return {"access_token": "fixture-access", "refresh_token": "fixture-refresh",
                "client_id": client, "scope": "user:inference", "expires_at": time.time() + 3600}

    def begin(self, configure: str | None = "myth-a") -> str:
        """经公开入口创建挑战，None 表示本用例已经选择环境变量配置。"""
        if configure is not None:
            self.manager.configure(configure)
        attempt = self.manager.begin_login(self.redirect)
        return parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)["state"][0]

    def callback(self, state: str) -> dict[str, list[str]]:
        """构造 loopback 已解析参数，不包含真实授权码。"""
        return {"state": [state], "code": ["fixture-code"]}

    def assert_rejected_before_exchange(self, state: str) -> None:
        """拒绝必须先于远端效果与凭据保存，不能先交换再报错。"""
        with patch.object(self.manager, "_token_exchange", return_value=self.token_response()) as exchange:
            with self.assertRaises(ClaudeOAuthError):
                self.manager.complete_callback(self.callback(state))
        exchange.assert_not_called()

    def test_changing_client_invalidates_previous_challenge(self) -> None:
        """先登录 A 再切到 B，迟到的 A 回调不能把配置改回去。"""
        state = self.begin()
        self.manager.configure("myth-b")
        self.assert_rejected_before_exchange(state)
        self.assertEqual(json.loads(self.manager.metadata_path.read_text())["client_id"], "myth-b")
        self.assertIsNone(self.store.load("default"))

    def test_environment_binding_is_considered_when_configuring(self) -> None:
        """没有 metadata client_id 时，显式配置仍需撤销旧环境身份与挑战。"""
        os.environ["MYTH_CLAUDE_OAUTH_CLIENT_ID"] = "myth-a"
        state = self.begin(configure=None)
        self.store.save("default", self.credential())
        self.manager.configure("myth-b")
        self.assertIsNone(self.store.load("default"))
        self.assert_rejected_before_exchange(state)

    def test_environment_change_is_checked_at_callback(self) -> None:
        """绕过 configure 的可见环境变化，也不能借旧挑战恢复旧客户端。"""
        os.environ["MYTH_CLAUDE_OAUTH_CLIENT_ID"] = "myth-a"
        state = self.begin(configure=None)
        os.environ["MYTH_CLAUDE_OAUTH_CLIENT_ID"] = "myth-b"
        self.assert_rejected_before_exchange(state)
        self.assertFalse(self.manager.metadata_path.exists())

    def test_visible_configuration_change_after_exchange_is_rejected(self) -> None:
        """交换期间另一实例已改客户端时，返回凭据不能再覆盖新配置；不外推原子性。"""
        state = self.begin()
        other = ClaudeOAuthManager(self.root, credential_store=self.store)

        def changed_during_exchange(*args) -> dict:
            """在远端返回边界注入已落盘的配置变化，不模拟真实跨进程事务。"""
            other.configure("myth-b")
            return self.token_response()

        with patch.object(self.manager, "_token_exchange", side_effect=changed_during_exchange) as exchange:
            with self.assertRaises(ClaudeOAuthError):
                self.manager.complete_callback(self.callback(state))
        exchange.assert_called_once()
        self.assertEqual(json.loads(self.manager.metadata_path.read_text())["client_id"], "myth-b")
        self.assertIsNone(self.store.load("default"))

    def test_same_client_configuration_preserves_current_challenge(self) -> None:
        """重复保存同一个客户端不是退出，不能误杀当前有效登录。"""
        state = self.begin()
        self.manager.configure("myth-a")
        with patch.object(self.manager, "_token_exchange", return_value=self.token_response()):
            status = self.manager.complete_callback(self.callback(state))
        self.assertTrue(status.connected)
        self.assertEqual(self.store.load("default")["client_id"], "myth-a")

    def test_invalid_configuration_does_not_cancel_valid_challenge(self) -> None:
        """无效输入在改变状态前拒绝，用户输错不能破坏旧的可用流程。"""
        state = self.begin()
        with self.assertRaises(ValueError):
            self.manager.configure(" ")
        with patch.object(self.manager, "_token_exchange", return_value=self.token_response()):
            self.assertTrue(self.manager.complete_callback(self.callback(state)).connected)

    def test_failed_configuration_still_invalidates_pending_login(self) -> None:
        """删除凭据失败不能声称已切换；但未完成挑战必须取消，不能随后偷偷登录。"""
        state = self.begin()
        self.store.save("default", self.credential())
        with patch.object(self.store, "delete", side_effect=RuntimeError("fixture delete failure")):
            with self.assertRaises(RuntimeError):
                self.manager.configure("myth-b")
        self.assert_rejected_before_exchange(state)
        self.assertEqual(json.loads(self.manager.metadata_path.read_text())["client_id"], "myth-a")
        self.assertIsNotNone(self.store.load("default"))

    def test_logout_invalidates_pending_login(self) -> None:
        """已退出后晚到的页面回调不能重新连接。"""
        state = self.begin()
        result = self.manager.logout()
        self.assertTrue(result["signed_out"])
        self.assertEqual(result["remote_revocation"], "not_claimed")
        self.assert_rejected_before_exchange(state)

    def test_failed_logout_cancels_pending_without_claiming_signout(self) -> None:
        """凭据删除失败仍抛错且保留原凭据事实，但不得保留可完成的登录挑战。"""
        state = self.begin()
        self.store.save("default", self.credential())
        with patch.object(self.store, "delete", side_effect=RuntimeError("fixture delete failure")):
            with self.assertRaises(RuntimeError):
                self.manager.logout()
        self.assert_rejected_before_exchange(state)
        self.assertIsNotNone(self.store.load("default"))

    def test_denial_consumes_only_its_own_challenge(self) -> None:
        """用户拒绝授权也结束对应一次性挑战，不得被之后的回调复活。"""
        state = self.begin()
        with self.assertRaises(ClaudeOAuthError):
            self.manager.complete_callback({"state": [state], "error": ["access_denied"]})
        self.assert_rejected_before_exchange(state)

    def test_unknown_denial_does_not_cancel_current_challenge(self) -> None:
        """不认识的 state 不应取消另一个合法挑战。"""
        state = self.begin()
        with self.assertRaises(ClaudeOAuthError):
            self.manager.complete_callback({"state": ["unknown-fixture"], "error": ["access_denied"]})
        with patch.object(self.manager, "_token_exchange", return_value=self.token_response()):
            self.assertTrue(self.manager.complete_callback(self.callback(state)).connected)

    def test_expiry_boundary_is_already_expired(self) -> None:
        """到期时间是排他边界，等于 expires_at 不能再交换授权码。"""
        with patch("myth.auth.claude.time.time", return_value=1000):
            state = self.begin()
        with patch("myth.auth.claude.time.time", return_value=1000 + LOGIN_TTL_SECONDS):
            self.assert_rejected_before_exchange(state)

    def test_empty_code_is_rejected_before_exchange(self) -> None:
        """空字符串不是有效授权码，不能发送无意义的认证请求。"""
        state = self.begin()
        with patch.object(self.manager, "_token_exchange", return_value=self.token_response()) as exchange:
            with self.assertRaises(ClaudeOAuthError):
                self.manager.complete_callback({"state": [state], "code": [""]})
        exchange.assert_not_called()

    def test_foreign_credentials_cannot_be_used_or_shown_connected(self) -> None:
        """共享凭据槽中若出现另一个客户端的 token，状态与使用入口都拒绝。"""
        self.manager.configure("myth-b")
        self.store.save("default", self.credential("myth-a"))
        status = self.manager.status()
        self.assertFalse(status.connected)
        self.assertEqual(status.reason, "client_binding_mismatch")
        self.assertEqual(status.scopes, ())
        with patch.object(self.manager, "_refresh") as refresh:
            with self.assertRaises(ClaudeOAuthError):
                self.manager.access_token()
        refresh.assert_not_called()

    def test_missing_credential_binding_is_not_inferred_from_configuration(self) -> None:
        """凭据缺少身份就拒绝，不补造绑定或保留旧格式猜测。"""
        self.manager.configure("myth-a")
        credential = self.credential()
        del credential["client_id"]
        self.store.save("default", credential)
        self.assertFalse(self.manager.status().connected)
        with self.assertRaises(ClaudeOAuthError):
            self.manager.access_token()

    def test_whitespace_environment_is_not_configured(self) -> None:
        """状态页与登录页使用相同的空白归一规则，不能一边已配置一边拒绝。"""
        os.environ["MYTH_CLAUDE_OAUTH_CLIENT_ID"] = " \t "
        self.assertFalse(self.manager.status().client_id_configured)
        with self.assertRaises(ClaudeOAuthError):
            self.manager.begin_login(self.redirect)

    def test_non_string_token_is_not_connected(self) -> None:
        """有值不代表有合法 token；状态不能把整数等异常形状显示成已连接。"""
        self.manager.configure("myth-a")
        credential = self.credential()
        credential["access_token"] = 123
        self.store.save("default", credential)
        self.assertFalse(self.manager.status().connected)

    def test_begin_reads_client_after_entering_owner_lock(self) -> None:
        """在取锁前精确注入一次配置变化，避免靠线程 sleep 猜测竞态窗口。"""
        self.manager.configure("myth-a")
        manager = self.manager
        original_lock = manager._lock
        pending = [True]

        class BeforeAcquire:
            """受控调度替身：模拟另一个请求恰好在本次取得锁之前完成配置。"""

            def __enter__(self):
                """只在最外层插入一次变化，重入 configure/status 仍使用真实 RLock。"""
                if pending[0]:
                    pending[0] = False
                    manager.configure("myth-b")
                original_lock.acquire()
                return self

            def __exit__(self, *args):
                """释放对应真实锁，不吞掉业务异常。"""
                original_lock.release()

        with patch.object(manager, "_lock", BeforeAcquire()):
            attempt = self.manager.begin_login(self.redirect)
        query = parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)
        self.assertEqual(query["client_id"], ["myth-b"])

    def test_duplicate_callbacks_exchange_once_under_real_threads(self) -> None:
        """两个真实线程同时提交同一 state，只能有一次远端交换与连接成功。"""
        state = self.begin()
        ready = threading.Barrier(2)

        def complete() -> bool:
            """在共同起点竞争回调，已消费的挑战按明确拒绝返回。"""
            ready.wait(timeout=5)
            try:
                return self.manager.complete_callback(self.callback(state)).connected
            except ClaudeOAuthError:
                return False

        with patch.object(self.manager, "_token_exchange", return_value=self.token_response()) as exchange:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(complete) for _ in range(2)]
                results = [future.result(timeout=5) for future in futures]
        self.assertEqual(sorted(results), [False, True])
        exchange.assert_called_once()

    def test_matching_binding_refresh_still_uses_original_client(self) -> None:
        """收紧身份检查不能破坏正常刷新，也不能换另一个 client_id。"""
        self.manager.configure("myth-a")
        credential = self.credential()
        credential["expires_at"] = time.time() - 1
        self.store.save("default", credential)
        with patch.object(self.manager, "_read_token_response", return_value=self.token_response()) as response:
            self.assertEqual(self.manager.access_token(), "fixture-access")
        self.assertEqual(json.loads(response.call_args.args[0].data)["client_id"], "myth-a")
