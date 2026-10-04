"""回归边界：真实本机 HTTP 合同、入口去重及跨站拒绝。
本文件固定夹具、输入和断言；通过只证明这些窗口，替身调用不等同真实模型质量或远端集成。"""

from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from urllib import error, request
from unittest.mock import Mock, patch
from test_workspace import ChatProvider, decision
from myth.agent_runtime import AgentRuntime
from myth.providers.scripted import ScriptedPatchProvider
from myth.runtime import MythRuntime
from myth.web import AgentWebService, make_handler


# 真实本机 HTTP 合同、入口去重及跨站拒绝的固定测试集合/替身；临时资源由本用例拥有，生产状态必须从实际仓储核对。
class WebContractTests(unittest.TestCase):
    # 建立本用例独立夹具/临时状态；状态不能跨测试共享，故障窗口以本方法固定条件为准。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = AgentWebService(self.root)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.service))
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    # 关闭本用例连接/服务并清理临时状态；清理失败不能覆盖被测异常。
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        deadline = time.monotonic() + 5
        while (
            self.service._active or self.service.workspace.active
        ) and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        self.tmp.cleanup()

    # 经本机 HTTP 发送固定测试参数并还原 JSON；响应状态与业务断言分别核对。
    def call(self, path, payload=None, headers=None):
        body = json.dumps(payload).encode() if payload is not None else None
        return request.urlopen(
            request.Request(
                self.url + path,
                data=body,
                headers={"Content-Type": "application/json", **(headers or {})},
            ),
            timeout=5,
        )

    # 真实本机 HTTP 合同、入口去重及跨站拒绝的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def settled(self, rid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = self.service.status(rid)
            if not status["driver_active"]:
                return status
            threading.Event().wait(0.01)
        self.fail("local worker did not finish")

    # 回归断言：Driver 返回仍是 RUNNING 时 Web 继续安全驱动；不能仅清本机 active。
    def test_web_worker_reenters_if_driver_returns_running_without_yield(self):
        original = AgentRuntime.run
        calls = {"count": 0}

        # 真实本机 HTTP 合同、入口去重及跨站拒绝的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def first_return_is_spurious(agent, run_id, provider):
            calls["count"] += 1
            if calls["count"] == 1:
                return agent.status(run_id)
            return original(agent, run_id, provider)

        with patch.object(AgentRuntime, "run", new=first_return_is_spurious):
            with self.call("/api/demo", {}) as response:
                rid = json.load(response)["run_id"]
            status = self.settled(rid)

        self.assertEqual(status["agent"]["status"], "SUCCEEDED")
        self.assertGreaterEqual(calls["count"], 2)

    # 回归断言：通过真实本机 HTTP 下载固定验收字节；范围只覆盖确定性演示。
    def test_http_demo_downloads_exact_verified_bytes(self):
        with self.call("/api/demo", {}) as response:
            rid = json.load(response)["run_id"]
        status = self.settled(rid)
        self.assertEqual(status["agent"]["status"], "SUCCEEDED")
        with self.call(f"/api/runs/{rid}/artifacts/0") as response:
            data = response.read()
            self.assertIn("attachment", response.headers["Content-Disposition"])
        source = Path(status["acceptance"]["files"][0]["path"])
        self.assertEqual(data, source.read_bytes().replace(b"foo", b"bar"))
        self.assertIn(b"\r\n", data)
        # 下载来自验收固定的不可变对象，受管展示副本后来变化也不会污染交付。
        (self.root / ".runtime" / "workspaces" / rid / source.name).write_text(
            "tampered"
        )
        with self.call(f"/api/runs/{rid}/artifacts/0") as response:
            self.assertEqual(response.read(), data)

    # 回归断言：HTTP 同入口身份返回原 Run；已开始工作不再派发。
    def test_same_request_returns_same_run_and_does_not_restart(self):
        source = self.root / "data.txt"
        source.write_text("foo")
        payload = {
            "request_id": "same",
            "goal": "replace",
            "provider": "scripted",
            "model": "test",
            "files": [str(source)],
            "acceptance": [
                {
                    "path": str(source),
                    "old_text": "foo",
                    "new_text": "bar",
                    "expected_count": 1,
                }
            ],
        }
        with self.call("/api/runs", payload) as response:
            rid = json.load(response)["run_id"]
        self.settled(rid)
        with self.call("/api/runs", payload) as response:
            self.assertEqual(json.load(response)["run_id"], rid)
        self.assertEqual(len(self.service.list_runs()), 1)
        self.assertEqual(len(self.service.status(rid)["model"]["model_invocations"]), 3)


    # 回归断言：API Key 可完全在 Myth Web 内连接，响应与状态都不能回显 secret。
    def test_provider_api_key_connect_is_in_app_and_never_echoes_secret(self):
        secret = "deepseek-secret-never-echo"
        with (
            patch.object(
                self.service.provider_keys,
                "prepare",
                return_value=secret,
            ) as prepare,
            patch.object(
                self.service.provider_keys,
                "save",
                return_value={
                    "provider": "deepseek",
                    "label": "DeepSeek",
                    "configured": True,
                    "source": "myth",
                },
            ) as save,
            patch.object(
                self.service,
                "_provider",
            ),
        ):
            # provider_key_save uses create_provider directly for candidate validation,
            # so patch the factory at the module boundary rather than the service helper.
            fake_provider = Mock()
            fake_provider.check.return_value = unittest.mock.Mock(
                ready=True,
                details={"models": ["deepseek-test"]},
            )
            with patch("myth.web.create_provider", return_value=fake_provider):
                with self.call(
                    "/api/auth/providers/connect",
                    {"provider": "deepseek", "api_key": secret},
                ) as response:
                    value = json.load(response)

        prepare.assert_called_once_with("deepseek", secret)
        save.assert_called_once_with("deepseek", secret)
        self.assertTrue(value["ready"])
        self.assertNotIn(secret, json.dumps(value))

    # 回归断言：候选 API Key 验证失败时不得覆盖已有安全凭据。
    def test_invalid_provider_api_key_never_replaces_existing_secret(self):
        secret = "bad-secret-never-save"
        with (
            patch.object(self.service.provider_keys, "prepare", return_value=secret),
            patch.object(self.service.provider_keys, "save") as save,
        ):
            fake_provider = Mock()
            fake_provider.check.return_value = unittest.mock.Mock(
                ready=False,
                details={"error": "invalid credential"},
            )
            with patch("myth.web.create_provider", return_value=fake_provider):
                with self.assertRaises(error.HTTPError) as raised:
                    self.call(
                        "/api/auth/providers/connect",
                        {"provider": "openai", "api_key": secret},
                    )
        self.assertEqual(raised.exception.code, 400)
        save.assert_not_called()

    # 回归断言：授权入口固定到本机 callback，不能由外部 Host 诱导重定向。
    def test_chatgpt_oauth_start_uses_exact_loopback_callback(self):
        captured = {}

        # 真实本机 HTTP 合同、入口去重及跨站拒绝的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
        def begin(redirect_uri, payload):
            captured["redirect_uri"] = redirect_uri
            return {
                "auth_url": "https://auth.openai.com/example",
                "expires_in": 600,
                "return_to": redirect_uri,
            }

        with patch.object(self.service, "chatgpt_begin", side_effect=begin):
            with self.call("/api/auth/chatgpt/start", {}) as response:
                value = json.load(response)
        self.assertEqual(
            captured["redirect_uri"],
            f"http://127.0.0.1:{self.server.server_port}/auth/callback",
        )
        self.assertEqual(value["return_to"], captured["redirect_uri"])

    # 回归断言：认证回调日志去除 query，防止单次 code/state 泄露。
    def test_oauth_callback_query_is_never_written_to_web_log(self):
        secret_code = "oauth-code-must-not-log"
        secret_state = "oauth-state-must-not-log"
        output = io.StringIO()
        with (
            patch.object(
                self.service, "chatgpt_complete", return_value={"ready": True}
            ),
            redirect_stdout(output),
        ):
            with request.urlopen(
                self.url + f"/auth/callback?code={secret_code}&state={secret_state}",
                timeout=5,
            ) as response:
                self.assertEqual(response.status, 200)
        logged = output.getvalue()
        self.assertIn("/auth/callback", logged)
        self.assertNotIn(secret_code, logged)
        self.assertNotIn(secret_state, logged)

    # 回归断言：跨 Origin 写入与非本机 Host 都被 HTTP 边界拒绝。
    def test_cross_origin_and_rebound_host_are_rejected(self):
        for path, payload, headers in [
            ("/api/demo", {}, {"Origin": "https://evil.invalid"}),
            ("/api/demo", {}, {"Content-Type": "text/plain"}),
            ("/api/runs", None, {"Host": f"evil.invalid:{self.server.server_port}"}),
        ]:
            with self.assertRaises(error.HTTPError) as raised:
                self.call(path, payload, headers)
            self.assertIn(raised.exception.code, (400, 403))
        self.assertEqual(self.service.list_runs(), [])

    # 回归断言：缺少可信 PASS 时不能下载成已验收交付物。
    def test_no_download_before_pass(self):
        source = self.root / "data.txt"
        source.write_text("foo")
        with MythRuntime(self.root) as runtime:
            rid = AgentRuntime(runtime).create_run(
                goal="replace",
                provider=ScriptedPatchProvider(),
                model="test",
                allowed_files=(source,),
            )
        with self.assertRaises(error.HTTPError) as raised:
            self.call(f"/api/runs/{rid}/artifacts/0")
        self.assertEqual(raised.exception.code, 403)

    # 回归断言：步数越界在持久 Run 准入前拒绝，避免残留半成品。
    def test_invalid_step_limit_is_rejected_before_creating_run(self):
        source = self.root / "data.txt"
        source.write_text("foo")
        with self.assertRaises(error.HTTPError) as raised:
            self.call(
                "/api/runs",
                {
                    "goal": "replace",
                    "provider": "scripted",
                    "model": "test",
                    "files": [str(source)],
                    "max_steps": 0,
                },
            )
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(self.service.list_runs(), [])

    # 真实本机 HTTP 合同、入口去重及跨站拒绝的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def workspace_json(self, path, payload=None):
        with self.call("/api/workspace" + path, payload) as response:
            return json.load(response)

    # 真实本机 HTTP 合同、入口去重及跨站拒绝的局部夹具协作；只服务本测试调用链，真实行为仍由外层断言核对。
    def wait_conversation(self, sid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            session = self.workspace_json(f"/sessions/{sid}")
            if session["turns"] and not session["turns"][-1]["driver_active"]:
                return session
            threading.Event().wait(0.01)
        self.fail("conversation did not finish")

    # 回归断言：本机 HTTP 对话持久保存，重复提交仍复用固定入口身份。
    def test_workspace_http_chat_persistence_and_duplicate_submit(self):
        self.workspace_json("/settings", {"provider": "ollama", "model": "test"})
        sid = self.workspace_json("/sessions", {})["id"]
        provider = ChatProvider()
        with (
            patch.object(self.service.workspace, "provider", return_value=provider),
            patch.object(
                self.service.workspace,
                "connection",
                return_value={"ready": True, "details": {"models": ["test"]}},
            ),
        ):
            body = {"text": "普通问题", "request_id": "chat-http"}
            first = self.workspace_json(f"/sessions/{sid}/messages", body)
            session = self.wait_conversation(sid)
            self.assertEqual(
                self.workspace_json(f"/sessions/{sid}/messages", body), first
            )
        self.assertEqual(session["turns"][-1]["status"], "COMPLETED")
        self.assertEqual(len(session["messages"]), 2)
        self.assertEqual(len(provider.calls), 1)
        contexts = [
            e["payload"]
            for e in session["turns"][-1]["events"]
            if e["kind"] == "ConversationContextCompiled"
        ]
        self.assertEqual(len(contexts), 1)
        self.assertEqual(
            contexts[0]["bytes_used"], provider.calls[0].context_report["bytes_used"]
        )
        self.assertIn("message:0", contexts[0]["selected"])
        with self.call(
            f"/api/workspace/messages/{session['messages'][-1]['id']}/download"
        ) as response:
            self.assertEqual(response.read(), "这是回答。".encode())
        with self.call(f"/api/workspace/sessions/{sid}/download") as response:
            self.assertIn("普通问题".encode(), response.read())
        self.workspace_json(f"/sessions/{sid}", {"title": "重要会话", "pinned": True})
        self.assertEqual(self.workspace_json("")["sessions"][0]["title"], "重要会话")

    # 回归断言：经项目/知识/工具路径下载不可变对象，而非后续可变受管文件。
    def test_workspace_http_project_knowledge_and_fixed_artifact_download(self):
        self.workspace_json("/settings", {"provider": "ollama", "model": "test"})
        project = self.workspace_json(
            "/projects", {"name": "工作", "root": str(self.root)}
        )
        doc = self.workspace_json(
            "/documents",
            {
                "title": "指南",
                "content": "学习安排 ALPHA-59",
                "project_id": project["id"],
            },
        )
        sources = self.workspace_json(f"/search?q=ALPHA-59&project_id={project['id']}")[
            "sources"
        ]
        self.assertEqual(sources[0]["document_id"], doc["id"])
        sid = self.workspace_json("/sessions", {"project_id": project["id"]})["id"]
        provider = ChatProvider(
            [
                decision(
                    "tool_call",
                    "artifact.write",
                    {"path": "报告.md", "content": "# ALPHA-59\n"},
                ),
                decision(),
            ]
        )
        with (
            patch.object(self.service.workspace, "provider", return_value=provider),
            patch.object(
                self.service.workspace,
                "connection",
                return_value={"ready": True, "details": {"models": ["test"]}},
            ),
        ):
            self.workspace_json(
                f"/sessions/{sid}/messages",
                {"text": "生成报告", "request_id": "artifact-http"},
            )
            session = self.wait_conversation(sid)
        artifact = session["artifacts"][0]
        path = f"/api/workspace/artifacts/{artifact['decision_id']}"
        with self.call(path) as response:
            self.assertEqual(response.read(), "# ALPHA-59\n".encode())
        (self.root / ".runtime" / "session-outputs" / sid / "报告.md").write_text(
            "changed"
        )
        with self.call(path) as response:
            self.assertEqual(response.read(), "# ALPHA-59\n".encode())
        self.workspace_json(f"/documents/{doc['id']}/archive", {})
        self.assertEqual(
            self.workspace_json(f"/documents/{doc['id']}")["content"],
            "学习安排 ALPHA-59",
        )

    # 回归断言：跨站写请求在 Session 创建前拒绝，不能留业务状态。
    def test_workspace_rejects_cross_origin_before_creating_session(self):
        with self.assertRaises(error.HTTPError) as raised:
            self.call("/api/workspace/sessions", {}, {"Origin": "https://evil.invalid"})
        self.assertIn(raised.exception.code, (400, 403))
        self.assertEqual(self.workspace_json("")["sessions"], [])

    # 回归断言：资料正文限额与 JSON 编码开销分开，合法正文不因外框误拒绝。
    def test_document_size_limit_allows_json_envelope_overhead(self):
        document = self.workspace_json(
            "/documents", {"title": "one-megabyte", "content": "x" * 1_000_000}
        )
        self.assertEqual(
            self.workspace_json(f"/documents/{document['id']}")["bytes"], 1_000_000
        )
        with self.assertRaises(error.HTTPError) as raised:
            self.workspace_json(
                "/documents", {"title": "too-large", "content": "x" * 1_000_001}
            )
        self.assertEqual(raised.exception.code, 400)
