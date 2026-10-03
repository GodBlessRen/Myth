"""安全反例和延迟边界回归。
只使用临时目录、合成凭据和 loopback 服务；证明本机协议边界，不证明真实 ChatGPT 登录或模型速度。
"""

import io
import http.client
import json
import os
import socket
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, parse, request

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from myth.auth.chatgpt import ChatGPTAuthManager, ChatGPTOAuthError, ISSUER, KeyringCredentialStore, run_loopback_login
from myth.auth.transport import open_credential_request
from myth.models import ProviderKnownFailure
from myth.providers.openai import OpenAIResponsesProvider, _usage
from myth.providers.ollama import OllamaProvider
from myth.artifacts import ObjectStore
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from myth.web_workspace import ConversationWebService
from myth.web import AgentWebService, make_handler
from myth.platform.memory_store import SqliteMemoryStore
from myth.durable_executor import ensure_executor_process
from test_v019_native_oauth import MemoryCredentialStore
from test_providers import FakeStreamResponse, request_obj


# 每个测试独立拥有凭据替身；真实系统密码库不受测试写入影响。
class AuthSecurityTests(unittest.TestCase):
    # 建立已连接的固定客户端/身份，记录里的所有 token 都是合成字符串。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = MemoryCredentialStore()
        self.auth = ChatGPTAuthManager(self.root, credential_store=self.store)
        self.pid = self.auth._persist_registration("oaiapp_security_fixture")
        metadata = self.auth._load_metadata()
        metadata["profiles"][self.pid].update(subject="user", status="connected")
        metadata["active_profile_id"] = self.pid
        self.auth._save_metadata(metadata)
        self.store.save(self.pid, {"client_id": "oaiapp_security_fixture", "subject": "user",
            "scope": "resource.invoke chatgpt.tokens.use.direct", "access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh", "id_token": "synthetic-id-token",
            "expires_at": int(time.time()) + 3600})

    # 等待所有线程由各测试结束，随后清除本测试临时元数据。
    def tearDown(self):
        self.tmp.cleanup()

    # 重新授权的 Web JSON/URL 不能携带可选 ID Token，注册显示名只用于初次注册。
    def test_returning_authorization_url_contains_no_id_token(self):
        attempt = self.auth.begin_login("http://127.0.0.1:54321/auth/callback", profile_id=self.pid)
        query = parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)
        self.assertNotIn("id_token_hint", query)
        self.assertNotIn("synthetic-id-token", json.dumps(attempt))
        self.assertNotIn("agent_name_hint", query)
        self.assertNotEqual(self.auth.status().login_revision, attempt["login_id"])

    # 重复字段属于歧义，不能选择第一项消费有效登录机会。
    def test_duplicate_callback_parameters_do_not_consume_challenge(self):
        attempt = self.auth.begin_login("http://127.0.0.1:54321/auth/callback")
        state = parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)["state"][0]
        with patch.object(self.auth, "_token_request") as exchange:
            with self.assertRaises(ChatGPTOAuthError):
                self.auth.complete_callback({"state": [state], "code": ["first", "second"]})
        exchange.assert_not_called()
        self.assertIn(state, self.auth._pending)

    # 固定回调 URI 不能混入 query、认证段、缺失端口或错误路径。
    def test_redirect_uri_is_exact(self):
        for uri in ("http://127.0.0.1/auth/callback", "http://127.0.0.1:54321/auth/callback?x=1",
                    "http://x@127.0.0.1:54321/auth/callback", "http://127.0.0.1:54321/callback"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                self.auth.begin_login(uri)

    # 另一管理器退出以后，本管理器旧挑战也失效；不重新交换授权码。
    def test_logout_cancels_login_across_managers(self):
        attempt = self.auth.begin_login("http://127.0.0.1:54321/auth/callback")
        state = parse.parse_qs(parse.urlparse(attempt["auth_url"]).query)["state"][0]
        other = ChatGPTAuthManager(self.root, credential_store=self.store)
        with patch.object(other, "_revoke_refresh_token"):
            other.logout()
        with patch.object(self.auth, "_token_request") as exchange:
            with self.assertRaisesRegex(ChatGPTOAuthError, "cancelled"):
                self.auth.complete_callback({"state": state, "code": "synthetic-code", "client_id": "oaiapp_new"})
        exchange.assert_not_called()
        self.assertFalse(self.auth.status().connected)

    # 使用事件控制轮转窗口；退出必须等新凭据保存后再删除，不能产生凭据复活。
    def test_logout_waits_for_refresh_and_removes_rotated_credentials(self):
        self.store.values[self.pid]["expires_at"] = 1
        other = ChatGPTAuthManager(self.root, credential_store=self.store)
        entered, release, logout_done = threading.Event(), threading.Event(), threading.Event()
        errors = []

        # 在远端轮转替身处暂停，让另一个管理器真实竞争 OS 锁。
        def exchange(_params):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("fixture timeout")
            return {"access_token": "rotated-access", "refresh_token": "rotated-refresh", "expires_in": 3600}

        # 收集线程异常，主线程必须断言不能把后台错误吞掉。
        def refresh():
            try:
                self.auth.access_token()
            except BaseException as exc:
                errors.append(type(exc).__name__)

        # 退出完成事件只能在凭据删除及元数据发布之后发出。
        def logout():
            try:
                other.logout()
            except BaseException as exc:
                errors.append(type(exc).__name__)
            finally:
                logout_done.set()

        with patch.object(self.auth, "_token_request", side_effect=exchange), patch.object(other, "_revoke_refresh_token") as revoke:
            refresh_thread = threading.Thread(target=refresh)
            logout_thread = threading.Thread(target=logout)
            refresh_thread.start()
            self.assertTrue(entered.wait(3))
            logout_thread.start()
            self.assertFalse(logout_done.wait(0.1))
            release.set()
            refresh_thread.join(4)
            logout_thread.join(4)
            self.assertFalse(refresh_thread.is_alive() or logout_thread.is_alive())
            revoke.assert_called_once_with("rotated-refresh", "oaiapp_security_fixture")
        self.assertEqual(errors, [])
        self.assertIsNone(self.store.load(self.pid))

    # 派发后进程退出留下 refresh_pending；后续管理器必须要求重授权而非盲重放旧 token。
    def test_refresh_crash_marker_prevents_replay(self):
        self.store.values[self.pid]["expires_at"] = 1
        with patch.object(self.auth, "_token_request", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.auth.access_token()
        other = ChatGPTAuthManager(self.root, credential_store=self.store)
        with patch.object(other, "_token_request") as exchange:
            with self.assertRaisesRegex(ChatGPTOAuthError, "sign-in"):
                other.access_token()
        exchange.assert_not_called()
        self.assertFalse(other.status().ready)
        self.assertNotIn("synthetic-refresh", self.auth.metadata_path.read_text())

    # 服务明确回收 scope 以后不能沿用旧授权；短寿命也不能人为扩成六十秒。
    def test_refresh_rechecks_scope_and_exact_lifetime(self):
        self.store.values[self.pid]["expires_at"] = 1
        with patch.object(self.auth, "_token_request", return_value={
            "access_token": "new-access", "refresh_token": "new-refresh", "scope": "", "expires_in": 5}):
            before = int(time.time())
            with self.assertRaisesRegex(ChatGPTOAuthError, "permission"):
                self.auth.access_token()
        self.assertLessEqual(self.store.values[self.pid]["expires_at"], before + 6)
        self.assertFalse(self.auth.status().sharing)

    # 目录可短期复用，退出后读取系统库必须拒绝，缓存不能延续认证权。
    def test_catalog_cache_is_shared_but_does_not_authorize_after_logout(self):
        other = ChatGPTAuthManager(self.root, credential_store=self.store)
        with patch.object(ChatGPTAuthManager, "_fetch_models", return_value=[{"slug": "fixture", "display_name": "Fixture"}]) as fetch:
            first = self.auth.list_models()
            first[0]["slug"] = "mutated"
            self.assertEqual(other.list_models()[0]["slug"], "fixture")
            self.assertEqual(fetch.call_count, 1)
            with patch.object(other, "_revoke_refresh_token"):
                other.logout()
            with self.assertRaises(ChatGPTOAuthError):
                self.auth.list_models()
            self.assertEqual(fetch.call_count, 1)

    # 系统后端必须来自准确模块，第三方类名不能靠 windows 标记越过信任边界。
    def test_keyring_module_spoof_is_rejected(self):
        spoof = type("WindowsSecureKeyring", (), {"__module__": "untrusted.windows", "priority": 10})()
        with patch("myth.auth.chatgpt.keyring.get_keyring", return_value=spoof):
            with self.assertRaises(ChatGPTOAuthError):
                KeyringCredentialStore().load(self.pid)

    # 真实签名仅证明字段受 issuer 签名；多 audience 仍需核对 azp 到当前客户端。
    def test_oidc_rejects_wrong_authorized_party(self):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode({"iss": ISSUER, "aud": ["client", "another"], "azp": "another",
            "sub": "user", "iat": int(time.time()), "exp": int(time.time()) + 600}, private, algorithm="RS256")
        signing = type("SigningKey", (), {"key": private.public_key()})()
        with patch.object(self.auth._jwks, "get_signing_key_from_jwt", return_value=signing):
            with self.assertRaisesRegex(ChatGPTOAuthError, "authorized party"):
                self.auth._verify_id_token(token, client_id="client", nonce=None)

    # 非规范 compact 编码在公钥请求之前拒绝；不能接受旧 JWT 解码器忽略的垃圾签名字节。
    def test_oidc_rejects_noncanonical_encoding_before_jwks(self):
        with patch.object(self.auth._jwks, "get_signing_key_from_jwt") as fetch:
            with self.assertRaises(ChatGPTOAuthError):
                self.auth._verify_id_token("e30.e30.e30!!!!", client_id="client", nonce=None)
        fetch.assert_not_called()

    # 签名算法名并不足够，弱 RSA 公钥不能通过本应用的 OIDC 验证边界。
    def test_oidc_rejects_weak_rsa_key(self):
        private = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        token = jwt.encode({"iss": ISSUER, "aud": "client", "sub": "user", "iat": int(time.time()),
            "exp": int(time.time()) + 600}, private, algorithm="RS256")
        signing = type("SigningKey", (), {"key": private.public_key()})()
        with patch.object(self.auth._jwks, "get_signing_key_from_jwt", return_value=signing):
            with self.assertRaises(ChatGPTOAuthError):
                self.auth._verify_id_token(token, client_id="client", nonce=None)

    # 远端 error 字段也可能含秘钥；只允许固定错误码公开。
    def test_oauth_error_code_cannot_echo_secrets(self):
        rejected = error.HTTPError("https://auth.openai.com/token", 400, "error", {},
            io.BytesIO(b'{"error":"synthetic-refresh-secret"}'))
        with patch("myth.auth.chatgpt.open_credential_request", side_effect=rejected):
            with self.assertRaises(ChatGPTOAuthError) as caught:
                self.auth._token_request({})
        self.assertNotIn("synthetic-refresh-secret", str(caught.exception))

    # 元数据写入白名单也约束调用方误带的字段，凭据不能绕过系统库直接保存。
    def test_metadata_whitelist_excludes_credential_fields(self):
        metadata = self.auth._load_metadata()
        metadata["access_token"] = "synthetic-should-not-persist"
        metadata["profiles"][self.pid]["id_token"] = "synthetic-should-not-persist"
        self.auth._save_metadata(metadata)
        self.assertNotIn("synthetic-should-not-persist", self.auth.metadata_path.read_text())

    # 真实临时 CLI listener 拒绝无关回调后继续等待，只接受本次 state；不启动真实浏览器或 OAuth 网络。
    def test_cli_listener_ignores_unrelated_callback(self):
        opened = threading.Event()
        captured = {}
        result = {}

        # 捕获登录入口通知主线程，服务器端循环随后开始服务。
        def open_browser(url):
            captured["url"] = url
            opened.set()
            return True

        # CLI 登录在单独线程运行，结果/异常必须被外层核对。
        def login():
            try:
                result["status"] = run_loopback_login(self.auth, timeout=5)
            except BaseException as exc:
                result["error"] = type(exc).__name__

        with patch("myth.auth.chatgpt.webbrowser.open", side_effect=open_browser), patch.object(self.auth, "complete_callback", return_value=self.auth.status()) as complete:
            worker = threading.Thread(target=login)
            worker.start()
            self.assertTrue(opened.wait(3))
            params = parse.parse_qs(parse.urlparse(captured["url"]).query)
            callback = params["redirect_uri"][0]
            with self.assertRaises(error.HTTPError) as rejected:
                request.urlopen(callback + "?state=forged", timeout=2)
            rejected.exception.close()
            self.assertTrue(worker.is_alive())
            with request.urlopen(callback + "?" + parse.urlencode({"state": params["state"][0], "code": "synthetic"}), timeout=2) as response:
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
            worker.join(4)
            self.assertFalse(worker.is_alive())
            self.assertNotIn("error", result)
            complete.assert_called_once()


# 有限容量安全库替身，模拟 Windows UTF-16 单条 2560 字节限制；不触碰真实系统凭据。
class BoundedVault:
    # 每个替身拥有独立记录目录，测试必须断言遗留记录已清理。
    def __init__(self):
        self.values = {}

    # 读取固定键，不模拟系统后端认证与加密保证。
    def get_password(self, service, user):
        return self.values.get((service, user))

    # 大于真实单条容量的值拒绝，以验证分块存储兼容窗口。
    def set_password(self, service, user, value):
        if len(value.encode("utf-16-le")) > 2560:
            raise ValueError("fixture blob too large")
        self.values[(service, user)] = value

    # 删除测试记录，供中途崩溃和退出清理断言。
    def delete_password(self, service, user):
        self.values.pop((service, user), None)


# 分块、切换和退出清理都在系统库接口内完成，任何窗口不能降级为明文文件。
class CredentialChunkTests(unittest.TestCase):
    # 装配有限容量替身，不复用真实 service 或用户已有账号。
    def setUp(self):
        self.vault = BoundedVault()
        self.store = KeyringCredentialStore("synthetic-fixture")
        self.backend_patch = patch.object(self.store, "_backend", return_value=self.vault)
        self.backend_patch.start()

    # 撤销后端替换，避免其他测试误认为真实系统库已验证。
    def tearDown(self):
        self.backend_patch.stop()

    # 长 Token 和 Unicode 都能无损复原，每块及清单都满足 UTF-16 容量限制。
    def test_large_credentials_round_trip_without_oversized_blob(self):
        value = {"access_token": "synthetic-" * 1200, "id_token": "synthetic-id-" * 1000, "name": "中文"}
        self.store.save("profile", value)
        self.assertEqual(self.store.load("profile"), value)
        self.assertTrue(all(len(raw.encode("utf-16-le")) <= 2560 for raw in self.vault.values.values()))
        self.store.delete("profile")
        self.assertEqual(self.vault.values, {})

    # 保存新代次后旧分块及旧单条记录都清理，读写始终返回同一完整代次。
    def test_rotation_migrates_legacy_and_removes_old_chunks(self):
        self.vault.set_password(self.store.service, "profile", '{"access_token":"legacy"}')
        self.assertEqual(self.store.load("profile")["access_token"], "legacy")
        self.store.save("profile", {"access_token": "first" * 1000})
        self.store.save("profile", {"access_token": "second" * 1000})
        self.assertNotIn((self.store.service, "profile"), self.vault.values)
        manifest = self.store._manifest(self.vault, "profile")
        self.assertEqual(len(manifest["entries"]), 1)
        self.assertEqual(len(self.vault.values), manifest["entries"][0]["parts"] + 1)
        self.assertEqual(self.store.load("profile")["access_token"], "second" * 1000)

    # 部分块写入后强制退出，清单仍能定位遗留块；load 不能返回拼接不完整的 token。
    def test_mid_write_crash_retains_cleanup_manifest(self):
        original = self.vault.set_password
        calls = []

        # 在第二个分块前模拟进程退出，越过常规 Exception 分支。
        def write(service, user, value):
            if ":part:" in service:
                calls.append(service)
                if len(calls) == 2:
                    raise KeyboardInterrupt
            original(service, user, value)

        with patch.object(self.vault, "set_password", side_effect=write):
            with self.assertRaises(KeyboardInterrupt):
                self.store.save("profile", {"access_token": "synthetic" * 2000})
        self.assertIsNone(self.store.load("profile"))
        self.store.delete("profile")
        self.assertEqual(self.vault.values, {})


# 同时覆盖真实 HTTP 重定向和有界 SSE；替身凭据不会离开 loopback。
class TransportSecurityTests(unittest.TestCase):
    # Ollama 端点配置不能携带可持久化查询秘钥；拒绝码已知，远端错误正文不进入收据。
    def test_ollama_endpoint_and_http_error_are_sanitized(self):
        with self.assertRaises(ValueError):
            OllamaProvider("http://127.0.0.1:11434?api_key=synthetic-secret")
        failure = error.HTTPError("http://127.0.0.1:11434/api/chat", 429, "synthetic-secret", {},
            io.BytesIO(b'{"error":"synthetic-secret"}'))
        with patch("myth.providers.ollama.open_credential_request", side_effect=failure):
            with self.assertRaises(ProviderKnownFailure) as caught:
                OllamaProvider().invoke(request_obj())
        self.assertNotIn("synthetic-secret", str(caught.exception) + json.dumps(caught.exception.raw))

    # 真实 loopback 目标计数证明 301/302/303/307/308 均没有第二跳。
    def test_credential_transport_never_follows_redirects(self):
        reached = []

        # 测试服务只返回定向到本机另一路径的 Location；不接受真实凭据。
        class Handler(BaseHTTPRequestHandler):
            # 关闭测试访问日志，避免把合成请求内容误当真实证据。
            def log_message(self, *_):
                pass

            # 重定向目标收到请求就记录，这使漏传认证头可被外层断言发现。
            def do_GET(self):
                if self.path == "/target":
                    reached.append(self.headers.get("Authorization"))
                    self.send_response(200)
                else:
                    self.send_response(int(self.path[1:]))
                    self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/target")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for code in (301, 302, 303, 307, 308):
                req = request.Request(f"http://127.0.0.1:{server.server_port}/{code}", headers={"Authorization": "Bearer synthetic-only"})
                with self.subTest(code=code), self.assertRaises(error.HTTPError) as caught:
                    open_credential_request(req, timeout=2)
                caught.exception.close()
            self.assertEqual(reached, [])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)

    # OAuth 只允许正式 API，不能把计划 token 指向第三方或非 TLS 接收端。
    def test_plan_endpoint_and_tls_are_enforced(self):
        for endpoint in ("https://evil.invalid/v1", "http://api.openai.com/v1"):
            with self.assertRaises(ValueError):
                OpenAIResponsesProvider(provider_id="chatgpt", token_supplier=lambda: "x", base_url=endpoint, chatgpt_plan=True)

    # 实际 SSE 多行 data 能还原一个事件；完成后不等连接 EOF，首 token 只计非空 delta。
    def test_multiline_sse_and_terminal_completion(self):
        raw = b'data: {"type":"response.output_text.delta",\ndata: "delta":"{}"}\n\n'
        raw += b'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        raw += b'data: malformed-trailing-data\n\n'
        completed, text, latency = OpenAIResponsesProvider._read_stream(io.BytesIO(raw))
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(text, "{}")
        self.assertGreaterEqual(latency, 0)

    # 超长单行被有界 readline 拒绝；仅部分输出不可以被当作成功。
    def test_sse_line_limit_and_incomplete_stream(self):
        with self.assertRaisesRegex(RuntimeError, "byte limit"):
            OpenAIResponsesProvider._read_stream(io.BytesIO(b"data: " + b"x" * (2 * 1024 * 1024)))
        with self.assertRaisesRegex(RuntimeError, "without response.completed"):
            OpenAIResponsesProvider._read_stream(io.BytesIO(b'data: {"type":"response.output_text.delta","delta":"x"}\n\n'))

    # HTTP 已知拒绝只返回安全码，供应商描述和未知码不得进入异常或 raw 证据。
    def test_provider_http_error_is_known_and_sanitized(self):
        provider = OpenAIResponsesProvider(provider_id="openai", token_supplier=lambda: "synthetic-private-key")
        rejected = error.HTTPError("https://api.openai.com/v1/responses", 401, "error", {},
            io.BytesIO(b'{"error":{"code":"synthetic-private-key","message":"synthetic-private-key"}}'))
        with patch("myth.providers.openai.open_credential_request", side_effect=rejected):
            with self.assertRaises(ProviderKnownFailure) as caught:
                provider.invoke(request_obj())
        self.assertNotIn("synthetic-private-key", str(caught.exception) + json.dumps(caught.exception.raw))

    # 结果白名单和当前 token 遮蔽先于持久化，服务端未知元数据不能进入对象仓库。
    def test_echoed_credential_is_removed_from_result_and_response_id(self):
        secret = "synthetic-private-key"
        events = [{"type": "response.output_text.delta", "delta": secret},
            {"type": "response.completed", "response": {"status": "completed", "id": secret,
                "output": [{"type": "message", "content": [{"type": "output_text", "text": secret}]}],
                "headers": {"Authorization": secret}, "usage": {"input_tokens": 2, "output_tokens": 1}}}]
        provider = OpenAIResponsesProvider(provider_id="chatgpt", token_supplier=lambda: secret, chatgpt_plan=True)
        with patch("myth.providers.openai.open_credential_request", return_value=FakeStreamResponse(events)):
            result = provider.invoke(request_obj())
        self.assertNotIn(secret, result.text + json.dumps(result.raw) + (result.response_id or ""))
        self.assertNotIn("headers", result.raw)
        self.assertIn("time_to_first_token_ms", result.usage)

    # 缺失或畸形 usage 保持未知，不能把预算结算为伪造零 Token。
    def test_missing_usage_is_not_zero(self):
        self.assertEqual(_usage({}), {"model_calls": 1})
        self.assertEqual(_usage({"usage": {"input_tokens": True, "output_tokens": -1}}), {"model_calls": 1})


# 文件/对象/前端边界只读本测试自己创建的项目，不能访问用户真实秘钥目录。
class WorkspaceSecurityTests(unittest.TestCase):
    # 创建受管 Runtime 与项目快照，以相同执行适配器验证读取和 Git 路径。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.execution = self.workspace.execution
        self.turn = {"snapshot": {"project": {"root": str(self.root)}}}

    # 确保连接关闭后才清目录；不能把 Windows 文件句柄故障误报成产品成功。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 多页匹配仍按分数/新旧稳定选取；top-k 剪枝不能漏掉最后一页的最高分条目。
    def test_memory_top_k_keeps_full_scan_and_stable_ranking(self):
        memory = SqliteMemoryStore(self.runtime)
        with self.runtime.store.tx() as db:
            db.executemany("INSERT INTO workspace_memories(memory_id,kind,text,source_ref) VALUES (?,?,?,?)",
                [(f"fixture-{i:04}", "semantic", "apple " + ("banana" if i >= 590 else ""), f"source-{i}")
                 for i in range(600)])
        result = memory.search_report("apple banana", limit=6)
        self.assertEqual([item["memory_id"] for item in result["memories"]],
            [f"fixture-{i:04}" for i in range(599, 593, -1)])
        self.assertEqual(result["retrieval"]["scanned"], 600)
        self.assertEqual(result["retrieval"]["matched"], 600)
        self.assertTrue(result["retrieval"]["exhausted"])

    # 新索引必须用于实际会话过滤；旧数据库初始化可补建，不改变返回语义。
    def test_message_lookup_uses_session_index(self):
        plan = self.runtime.store.db.execute("EXPLAIN QUERY PLAN SELECT * FROM workspace_messages WHERE session_id=? ORDER BY rowid", ("fixture",)).fetchall()
        self.assertTrue(any("workspace_messages_session" in row["detail"] for row in plan))

    # 保存模型设置时拒绝查询字符串中的 API key，不让它进入 Runtime SQLite/页面 bootstrap。
    def test_model_settings_reject_query_credentials(self):
        with self.assertRaises(ValueError):
            self.workspace.repository.save_settings({"provider": "ollama", "model": "fixture",
                "ollama_url": "http://127.0.0.1:11434?api_key=synthetic-secret"})

    # 大差异只读到展示上限；截断是明确事实，不能先把所有 Git 输出积累到内存。
    def test_git_large_diff_has_bounded_output(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        (self.root / "large.txt").write_text("before\n")
        subprocess.run(["git", "-C", str(self.root), "add", "large.txt"], check=True, capture_output=True)
        (self.root / "large.txt").write_text("after\n" * 50000)
        value = self.execution._git(self.turn, "git.diff", {"path": "large.txt"})
        self.assertTrue(value["truncated"])
        self.assertLessEqual(len(value["output"].encode()), 24000)

    # Runtime 根内放同名恶意 Python 包；实际子进程 help 导入必须使用可信安装目录。
    def test_worker_launch_cannot_import_runtime_root_shadow_package(self):
        package = self.root / "myth"
        package.mkdir()
        marker = self.root / "shadow-executed"
        (package / "__init__.py").write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\nraise RuntimeError('shadow')\n")
        real_popen = subprocess.Popen
        checked = []

        # 以 help 参数运行真实导入后退出，不启动无人管理的后台 worker；环境去除测试 PYTHONPATH。
        def inspect_launch(command, **kwargs):
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            with real_popen(command + ["--help"], cwd=kwargs["cwd"], env=environment,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
                child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0)
            checked.append(kwargs["cwd"])
        with patch("myth.durable_executor.subprocess.Popen", side_effect=inspect_launch):
            ensure_executor_process(self.root)
        self.assertEqual(len(checked), 1)
        self.assertNotEqual(Path(checked[0]), self.root)
        self.assertFalse(marker.exists())

    # 解析后真实路径也必须接受敏感路径约束，内部链接不能绕过 .env 黑名单。
    def test_internal_secret_symlink_is_rejected(self):
        (self.root / ".env").write_text("synthetic-secret")
        try:
            (self.root / "public.txt").symlink_to(self.root / ".env")
        except OSError:
            # 无 symlink 权限时通过固定 resolve 替身覆盖校验分支，不宣称 OS 链接创建成功。
            original = Path.resolve

            # 固定攻击别名只用于此测试，其他 Path 保持真实解析。
            def resolve(path, *args, **kwargs):
                return self.root / ".env" if path == self.root / "public.txt" else original(path, *args, **kwargs)
            with patch.object(Path, "resolve", resolve), self.assertRaises(PermissionError):
                self.execution.project_path(self.turn, "public.txt")
        else:
            with self.assertRaises(PermissionError):
                self.execution.project_path(self.turn, "public.txt")

    # Git 自身允许跟踪 .env；适配器必须只请求逐个复核的普通文件正文。
    def test_git_diff_excludes_tracked_secrets_and_directory_pathspec(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        (self.root / ".env").write_text("old secret")
        (self.root / "safe.txt").write_text("old text")
        subprocess.run(["git", "-C", str(self.root), "add", ".env", "safe.txt"], check=True, capture_output=True)
        (self.root / ".env").write_text("synthetic-secret-to-exclude")
        (self.root / "safe.txt").write_text("new visible text")
        (self.root / ".gitattributes").write_text("*.txt diff=fixture")
        subprocess.run(["git", "-C", str(self.root), "config", "diff.fixture.textconv", "nonexistent-textconv-program"], check=True, capture_output=True)
        result = self.execution._git(self.turn, "git.diff", {})
        self.assertIn("new visible text", result["output"])
        self.assertNotIn("synthetic-secret-to-exclude", result["output"])
        self.assertNotIn(".env", result["output"])
        with self.assertRaises(ValueError):
            self.execution._git(self.turn, "git.diff", {"path": "."})

    # 目录剪枝必须发生在遍历前，不能先扫描排除目录再隐藏结果。
    def test_project_search_prunes_excluded_directories(self):
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "secret.py").write_text("needle")
        (self.root / "safe.py").write_text("needle")
        result = self.execution._search_project(self.turn, {"query": "needle"})
        self.assertEqual(result["scanned_files"], 1)
        self.assertEqual(result["matches"][0]["path"], "safe.py")

    # 对象仓库只能由固定 SHA-256 身份寻址，不能把恶意 digest 拼成本机路径。
    def test_object_digest_path_traversal_is_rejected(self):
        store = ObjectStore(self.root / "objects")
        for digest in ("../../.env", "A" * 64, "a" * 63):
            with self.assertRaises(ValueError):
                store.get(digest)

    # 五秒缓存只复用公开 Ollama 模型目录，显式检查绕过缓存，调用方修改不污染下次结果。
    def test_preflight_cache_reduces_duplicate_network_checks(self):
        from myth.models import ProviderStatus
        service = ConversationWebService(self.root)
        settings = {"provider": "ollama", "ollama_url": "http://127.0.0.1:11434"}
        with patch("myth.web_workspace.OllamaProvider.check", return_value=ProviderStatus("ollama", True, details={"models": ["fixture"]})) as check:
            first = service.connection(settings)
            first["details"]["models"].append("mutated")
            self.assertEqual(service.connection(settings)["details"]["models"], ["fixture"])
            self.assertEqual(check.call_count, 1)
            service.connection(settings, force=True)
            self.assertEqual(check.call_count, 2)

    # 明确拒绝的模型调用会发布 FAILED 收据，完整对话不能因此停在 UNKNOWN 或重复派发。
    def test_known_provider_failure_settles_once_without_replay(self):
        self.workspace.repository.save_settings({"provider": "openai", "model": "fixture"})
        sid = self.workspace.repository.create_session()["id"]
        turn = self.workspace.repository.create_turn(sid, "Explain a concept", "known-failure")
        provider = OpenAIResponsesProvider(provider_id="openai", token_supplier=lambda: "synthetic")
        rejected = error.HTTPError("https://api.openai.com/v1/responses", 429, "error", {}, io.BytesIO(b'{"error":{"code":"rate_limit_exceeded"}}'))
        with patch("myth.providers.openai.open_credential_request", side_effect=rejected) as send:
            self.workspace.run(turn["run_id"], provider)
            self.workspace.run(turn["run_id"], provider)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.workspace.repository.turn(turn["run_id"])["status"], "FAILED")
        self.assertEqual(self.workspace.repository.decisions.status(turn["run_id"])["model_invocations"][0]["state"], "RESOLVED")


# 使用真正的 loopback Handler 验证浏览器缺少 Origin 的跨站 GET 和公开异常投影。
class WebSecurityTests(unittest.TestCase):
    # 残缺 JSON 请求体在配置的读限时后结束；不能靠永久 HTTP 线程占用拖垮工作台。
    def test_incomplete_request_body_has_read_deadline(self):
        self.server.RequestHandlerClass.request_read_timeout = 0.1
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2) as connection:
            incoming = ("POST /api/auth/chatgpt/logout HTTP/1.1\r\nHost: 127.0.0.1:" + str(self.server.server_port)
                + "\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{").encode()
            start = time.monotonic()
            connection.sendall(incoming)
            response = http.client.HTTPResponse(connection)
            response.begin()
            response.read()
            self.assertEqual(response.status, 409)
            self.assertLess(time.monotonic() - start, 2)

    # 重复 Content-Length 会制造消息边界歧义，必须在 JSON/业务处理前拒绝。
    def test_duplicate_content_length_is_rejected(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        try:
            connection.putrequest("POST", "/api/auth/chatgpt/logout")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", "2")
            connection.putheader("Content-Length", "2")
            connection.endheaders(b"{}")
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 400)
        finally:
            connection.close()

    # 创建本机服务，但不启动独立执行进程或真实供应商。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = AgentWebService(Path(self.tmp.name))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.service))
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    # 先停止 socket/线程后清理目录，避免后台线程跨测试污染状态。
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)
        self.tmp.cleanup()

    # Fetch Metadata 能在 Origin 缺失时识别跨站浏览器请求；同源仍可正常读取。
    def test_cross_site_get_without_origin_is_rejected(self):
        with self.assertRaises(error.HTTPError) as caught:
            request.urlopen(request.Request(self.url + "/api/auth/chatgpt/status", headers={"Sec-Fetch-Site": "cross-site"}), timeout=3)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()
        with request.urlopen(self.url + "/api/auth/chatgpt/status", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

    # Host 的用户信息/附加路径不能被宽松 urlparse 当作本机有效身份。
    def test_host_userinfo_is_rejected(self):
        with self.assertRaises(error.HTTPError) as caught:
            request.urlopen(request.Request(self.url, headers={"Host": f"attacker@127.0.0.1:{self.server.server_port}"}), timeout=3)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    # 供应商或仓储非预期异常不能透传完整描述到页面。
    def test_unexpected_error_does_not_leak_secret(self):
        with patch.object(self.service, "chatgpt_status", side_effect=RuntimeError("synthetic-private-secret")):
            with self.assertRaises(error.HTTPError) as caught:
                request.urlopen(self.url + "/api/auth/chatgpt/status", timeout=3)
        body = caught.exception.read().decode()
        caught.exception.close()
        self.assertNotIn("synthetic-private-secret", body)


if __name__ == "__main__":
    unittest.main()
