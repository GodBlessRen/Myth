"""日常对话的可用性回归：短提示、稳定前缀、澄清连续性与已知截断恢复。

固定 Provider 仅验证真实 Runtime 的派发、预算与消息事实，不替代真实模型质量测试。
"""

import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from myth.adapters.model_catalog import PublicModelCatalog
from myth.conversation import conversation_request
from myth.models import ModelMessage, ModelRequest, OutputTruncated, ProviderStatus
from myth.providers.messages import MessagesProvider
from myth.providers.openai import OpenAIResponsesProvider
from myth.providers.ollama import OllamaProvider
from myth.runtime import MythRuntime
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


class ConversationUsabilityTests(unittest.TestCase):
    """用正常准入创建独立工作区，避免直接造表绕过产品路径。"""

    def setUp(self):
        """每个用例拥有数据库、Provider 和文件目录。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = MythRuntime(Path(self.tmp.name))
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "test"})
        self.sid = self.repo.create_session()["id"]

    def tearDown(self):
        """关闭连接后释放夹具，不能让后台状态跨用例复用。"""
        self.runtime.close()
        self.tmp.cleanup()

    def test_plain_question_uses_small_prompt_without_special_wording(self):
        """普通中文问题无需匹配介绍/解释正则才享有轻量提示。"""
        turn = self.repo.create_turn(self.sid, "Python 的列表和元组有啥区别？", "plain")
        provider = ChatProvider()
        self.workspace.run(turn["run_id"], provider)
        request = provider.calls[0]
        self.assertLess(request.context_report["bytes_used"], 7000)
        self.assertLessEqual(len(request.context_report["visible_tools"]), 14)
        self.assertEqual(len(provider.calls), 1)

    def test_volatile_state_does_not_rewrite_instruction_prefix(self):
        """工具进度、控制和 Goal 内容放在稳定指令之后，保留缓存公共前缀。"""
        settings = self.repo.settings()
        snapshot = {"messages": [{"role": "user", "content": "处理资料"}],
                    "knowledge": [], "memory": [], "turn_message_start": 0}
        first = conversation_request(settings, snapshot, snapshot["messages"], [])
        activity = {"step": 1, "state": "DONE", "capability": "math.calculate",
                    "result": {"value": 2}, "decision_id": "dec_fixture"}
        second = conversation_request(settings, {**snapshot, "goal": {
            "goal_id": "goal_fixture", "title": "新的工作状态", "work": {"progress_note": "已读取"}}},
            snapshot["messages"], [activity], {"steering_note": "继续", "revision": 2})
        self.assertEqual(first.messages[0], second.messages[0])
        self.assertNotIn("新的工作状态", second.messages[0].content)
        self.assertIn("新的工作状态", "\n".join(m.content for m in second.messages))

    def test_answered_question_is_not_replayed_as_latest_tool_observation(self):
        """提问与回答已有消息事实，不在回答后再把旧问题当最新工具结果提示模型。"""
        turn = self.repo.create_turn(self.sid, "帮我写一封请假信", "clarify")
        provider = ChatProvider([decision(kind="ask_user", question="请假日期？"), decision(claim="请假信正文")])
        self.workspace.run(turn["run_id"], provider)
        waiting = self.repo.turn(turn["run_id"])
        self.repo.answer(turn["run_id"], "10 月 20 日", waiting["question_id"])
        self.workspace.run(turn["run_id"], provider)
        prompt = "\n".join(m.content for m in provider.calls[-1].messages)
        self.assertEqual(prompt.count("请假日期？"), 1)
        self.assertNotIn('"question":"请假日期？"', prompt)
        self.assertIn("10 月 20 日", prompt)
        self.assertEqual(self.repo.turn(turn["run_id"])["status"], "COMPLETED")

    def test_known_output_limit_gets_one_larger_attempt_in_same_run(self):
        """终态 length 有收据才扩大一次生成预算，全文落库且不转等待用户。"""
        turn = self.repo.create_turn(self.sid, "详细写一份 Python 学习计划", "truncated")
        full_text = "完整段落。" * 1200 + "结束标记"
        provider = ChatProvider()
        original = provider.invoke

        def invoke(request):
            """首个请求达到长度上限；第二个请求返回完整决定。"""
            if not provider.calls:
                provider.calls.append(request)
                raise OutputTruncated("length", usage={"model_calls": 1, "input_tokens": 100,
                    "output_tokens": 2048}, raw={"done_reason": "length"})
            provider.outputs = [decision(claim=full_text)]
            return original(request)

        provider.invoke = invoke
        self.workspace.run(turn["run_id"], provider)
        self.assertEqual(self.repo.turn(turn["run_id"])["status"], "COMPLETED")
        self.assertEqual([r.max_output_tokens for r in provider.calls], [2048, 4096])
        self.assertEqual(self.repo.session(self.sid)["messages"][-1]["content"], full_text)
        facts = self.repo.decisions.status(turn["run_id"])["model_invocations"]
        self.assertEqual(len(facts), 2)
        self.assertTrue(all(row["state"] == "RESOLVED" for row in facts))

    def test_recent_history_is_not_injected_again_as_episodic_memory(self):
        """同源经历去重只改变模型投影，不删除 Memory 或跨会话的独立事实。"""
        first = self.repo.create_turn(self.sid, "解释 Python 列表", "history-first")
        self.workspace.run(first["run_id"], ChatProvider([decision(claim="Python 列表支持修改元素。")]))
        second = self.repo.create_turn(self.sid, "Python 列表还支持什么？", "history-next", _recall_memory=True)
        snapshot = second["snapshot"]
        self.assertFalse(any(m["provenance_ref"] == "run:" + first["run_id"] for m in snapshot["memory"]))
        self.assertGreater(snapshot["memory_retrieval_report"]["already_in_recent_history"], 0)
        self.assertIn("支持修改元素", "\n".join(m["content"] for m in snapshot["messages"]))
        self.assertTrue(self.workspace.memory.list())

    def test_admission_does_not_reload_historical_execution_details(self):
        """连续对话的上下文准备读取同一 CAS 事实，但不为旧轮次执行 N 次观测查询。"""
        first = self.repo.create_turn(self.sid, "之前的问题", "details-first")
        self.workspace.run(first["run_id"], ChatProvider())
        queries = []
        self.runtime.store.db.set_trace_callback(queries.append)
        try:
            prepared = self.repo.prepare_turn(self.sid, "继续回答", "details-next")
        finally:
            self.runtime.store.db.set_trace_callback(None)
        self.assertFalse(any("FROM workspace_steps WHERE run_id=" in q for q in queries))
        self.assertIn("之前的问题", str(prepared["snapshot"]["messages"]))
        # 不能用性能改动削弱快照核对：旧快照在准备后变化，仍须拒绝这份准备。
        with self.runtime.store.tx() as db:
            db.execute("UPDATE workspace_turns SET snapshot_json=json_set(snapshot_json,'$.fixture_changed',1) WHERE run_id=?",
                       (first["run_id"],))
        from myth.domain import IdentityConflict
        with self.assertRaises(IdentityConflict):
            self.repo.create_turn(self.sid, "继续回答", "details-next", _prepared=prepared)

    def test_repeated_truncation_stops_without_retry_loop(self):
        """第二次已知截断保留 FAILED，不用用户回答重启一条无界生成循环。"""
        turn = self.repo.create_turn(self.sid, "写长文", "twice")
        provider = ChatProvider()

        def invoke(request):
            """按实际上限报告完整已知失败计量。"""
            provider.calls.append(request)
            raise OutputTruncated("length", usage={"model_calls": 1, "input_tokens": 20,
                "output_tokens": request.max_output_tokens}, raw={"done_reason": "length"})

        provider.invoke = invoke
        self.workspace.run(turn["run_id"], provider)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(self.repo.turn(turn["run_id"])["status"], "FAILED")

    def test_crash_after_truncation_receipt_resumes_without_replaying_attempt(self):
        """收据已写而修复 Observation 未提交时崩溃；恢复只准入第二次机会。"""
        turn = self.repo.create_turn(self.sid, "写一份计划", "crash-truncated")
        provider = ChatProvider()
        original = provider.invoke

        def invoke(request):
            """首个机会有完整 length 收据；之后返回有效回答。"""
            if not provider.calls:
                provider.calls.append(request)
                raise OutputTruncated("length", usage={"model_calls": 1, "input_tokens": 100, "output_tokens": 2048})
            return original(request)

        provider.invoke = invoke
        with patch.object(self.repo, "finish_observation", side_effect=SystemExit("crash")):
            with self.assertRaises(SystemExit):
                self.workspace.run(turn["run_id"], provider)
        self.workspace.run(turn["run_id"], provider)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(self.repo.turn(turn["run_id"])["status"], "COMPLETED")
        reservations = self.runtime.store.db.execute(
            "SELECT reserved_amount FROM model_reservations WHERE run_id=? AND meter='output_tokens' ORDER BY rowid",
            (turn["run_id"],)).fetchall()
        self.assertEqual([row[0] for row in reservations], [2048, 4096])

    def test_oauth_length_failure_does_not_retry_an_unchanged_wire(self):
        """订阅端点不支持本地输出参数，不靠重发同一请求假装提高生成上限。"""
        self.repo.save_settings({"provider": "chatgpt", "model": "fixture"})
        turn = self.repo.create_turn(self.sid, "写长文", "oauth-length")
        provider = ChatProvider()
        provider.provider_id = "chatgpt"

        def invoke(request):
            """返回有计量的远端长度终态，区别于效果不明。"""
            provider.calls.append(request)
            raise OutputTruncated("max_output_tokens", usage={"model_calls": 1,
                "input_tokens": 20, "output_tokens": 2048})

        provider.invoke = invoke
        self.workspace.run(turn["run_id"], provider)
        self.assertEqual(len(provider.calls), 1)
        failed = self.repo.turn(turn["run_id"])
        self.assertEqual(failed["status"], "FAILED")
        self.assertIn("GPT OAuth 不支持本地调整", failed["error"])


class AdmissionLatencyTests(unittest.TestCase):
    """目录延迟用调用计数验证，避免依赖机器速度阈值。"""

    def test_remote_connection_cache_is_detached_and_force_refreshes(self):
        """热请求复用公开目录，调用方修改与手动刷新均不能污染缓存。"""
        with tempfile.TemporaryDirectory() as root:
            service = ConversationWebService(Path(root))
            provider = Mock()
            provider.check.return_value = ProviderStatus("openai", True, details={
                "models": ["fixture"], "model_capabilities": {"fixture": {"context_window": 32768}}})
            settings = {"provider": "openai", "model": "fixture"}
            with patch.object(service, "provider", return_value=provider):
                first = service.connection(settings)
                first["details"]["model_capabilities"]["fixture"]["context_window"] = 1
                second = service.connection(settings)
                self.assertEqual(provider.check.call_count, 1)
                self.assertEqual(second["details"]["model_capabilities"]["fixture"]["context_window"], 32768)
                service.connection(settings, force=True)
                self.assertEqual(provider.check.call_count, 2)

    def test_quote_can_use_cached_data_without_network(self):
        """发送热路径只读现有公开价格；冷目录不能阻塞第一条模型消息。"""
        loader = Mock(return_value={})
        catalog = PublicModelCatalog(loader)
        value = catalog.quote_settings({"provider": "openai", "model": "fixture"}, refresh=False)
        loader.assert_not_called()
        self.assertIsNone(value["model_pool"]["main_pricing"])


class CacheWireTests(unittest.TestCase):
    """请求标记与计量是两条独立事实；HTTP 替身不证明远端实际命中。"""

    def test_chinese_discovery_can_find_deferred_tools(self):
        """减少常驻目录后，中文工具发现仍能找到技能、记忆时间线与外部服务。"""
        from myth.conversation import TOOL_CATALOG
        from myth.platform.capabilities import default_capabilities
        from myth.platform.tool_discovery import search_tools
        descriptions = {spec.capability_id: spec.description for spec in default_capabilities().list()}
        for query, expected in (("技能", "skill.list"), ("记忆时间线", "memory.timeline"), ("外部服务", "mcp.servers")):
            with self.subTest(query=query):
                matches = search_tools(TOOL_CATALOG, descriptions, query)
                self.assertIn(expected, [row["capability_id"] for row in matches])

    def test_claude_explicitly_enables_automatic_prompt_caching(self):
        """缓存跟随增长的消息尾部，保留原始系统角色与结构化决定合同。"""
        request = ModelRequest("fixture", (ModelMessage("system", "固定说明"), ModelMessage("user", "问题")), {})
        value = {"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "myth_decision",
                 "input": json.loads(decision())}], "usage": {"input_tokens": 10, "output_tokens": 30}}
        with patch("myth.providers.messages.open_credential_request",
                   return_value=io.BytesIO(json.dumps(value).encode())) as send:
            MessagesProvider("anthropic", lambda: "fixture-secret").invoke(request)
        self.assertEqual(json.loads(send.call_args.args[0].data)["cache_control"], {"type": "ephemeral"})

    def test_responses_terminal_length_is_classified_for_known_retry(self):
        """DeepSeek/OpenAI/OAuth 的 Responses incomplete 只在长度原因明确时分类。"""
        value = {"type": "response.incomplete", "response": {"status": "incomplete",
                 "incomplete_details": {"reason": "max_output_tokens"}, "usage": {"output_tokens": 2048}}}
        body = io.BytesIO(("data: " + json.dumps(value) + "\n\n").encode())
        with self.assertRaises(OutputTruncated) as failed:
            OpenAIResponsesProvider._read_stream(body)
        self.assertEqual(failed.exception.usage["output_tokens"], 2048)

    def test_messages_terminal_length_is_classified_for_known_retry(self):
        """Claude/Kimi 已知长度停止保留费用，不被当成完整结构化决定。"""
        request = ModelRequest("fixture", (ModelMessage("user", "问题"),), {})
        for provider, value in (("anthropic", {"stop_reason": "max_tokens", "usage": {"output_tokens": 2048}}),
                                ("kimi", {"choices": [{"finish_reason": "length"}], "usage": {"completion_tokens": 2048}})):
            with self.subTest(provider=provider), patch("myth.providers.messages.open_credential_request",
                    return_value=io.BytesIO(json.dumps(value).encode())):
                with self.assertRaises(OutputTruncated) as failed:
                    MessagesProvider(provider, lambda: "fixture-secret").invoke(request)
                self.assertEqual(failed.exception.usage["output_tokens"], 2048)


class StreamingReplyTests(unittest.TestCase):
    """真实传输解析与 Web Driver 的预览边界；模型替身不提供真实质量或速度结论。"""

    def test_responses_preview_is_redacted_and_waits_for_completed(self):
        """API 与 OAuth 共用的流消费在完成前回调；认证材料不能经预览绕过脱敏。"""
        partial = '{"decision_type":"request_completion","reason":"answer","claim":"hello fixture-secret'
        full = partial + ' world","goal_coverage":"answer"}'
        terminal = {"status": "completed", "output_text": full, "usage": {"input_tokens": 12, "output_tokens": 30}}
        events = [{"type": "response.output_text.delta", "delta": partial},
                  {"type": "response.output_text.delta", "delta": full[len(partial):]},
                  {"type": "response.completed", "response": terminal}]
        body = "".join("data: " + json.dumps(e) + "\n\n" for e in events).encode()
        for provider_id in ("openai", "deepseek", "chatgpt"):
            observed = []
            response = io.BytesIO(body)
            response.headers = {"Content-Type": "text/event-stream"}
            request = ModelRequest("fixture", (ModelMessage("user", "问题"),), {}, on_text_delta=observed.append)
            with self.subTest(provider=provider_id), patch("myth.providers.openai.open_credential_request", return_value=response):
                provider = OpenAIResponsesProvider(provider_id=provider_id, token_supplier=lambda: "fixture-secret",
                    chatgpt_plan=provider_id == "chatgpt")
                result = provider.invoke(request)
            self.assertGreaterEqual(len(observed), 2)
            self.assertNotIn("fixture-secret", "\n".join(observed))
            self.assertEqual(result.usage["output_tokens"], 30)
            self.assertNotIn("on_text_delta", request.serializable())

    def test_ollama_stream_reassembles_complete_json_and_reports_ttft(self):
        """Ollama NDJSON 的终态计量和整份决定一起返回，局部片段只供展示。"""
        full = decision(claim="完整的中文回答")
        chunks = [full[:100], full[100:]]
        values = [{"message": {"content": text}, "done": False} for text in chunks]
        values.append({"message": {"content": ""}, "done": True, "done_reason": "stop",
                       "prompt_eval_count": 60, "eval_count": 40, "prompt_eval_cached_count": 45})
        observed = []
        request = ModelRequest("fixture", (ModelMessage("user", "问题"),), {}, on_text_delta=observed.append)
        with patch("myth.providers.ollama.open_credential_request", return_value=io.BytesIO(
                  "\n".join(json.dumps(row) for row in values).encode())) as send:
            result = OllamaProvider().invoke(request)
        self.assertIs(json.loads(send.call_args.args[0].data)["stream"], True)
        self.assertEqual(result.text, full)
        self.assertEqual(observed[-1], full)
        self.assertEqual(result.usage["cached_input_tokens"], 45)
        self.assertGreaterEqual(result.usage["time_to_first_token_ms"], 0)

    def test_ollama_missing_terminal_is_not_a_complete_decision(self):
        """合法 JSON 正文也不能代替流的 done 终态；断流不可执行。"""
        request = ModelRequest("fixture", (ModelMessage("user", "问题"),), {}, on_text_delta=lambda text: None)
        body = json.dumps({"message": {"content": decision()}, "done": False}).encode()
        with patch("myth.providers.ollama.open_credential_request", return_value=io.BytesIO(body)):
            with self.assertRaises(RuntimeError):
                OllamaProvider().invoke(request)

    def test_preview_parser_ignores_tools_and_handles_partial_unicode(self):
        """只展示顶层回答，工具参数里的 claim 和半个 unicode escape 都不会被误解释。"""
        with tempfile.TemporaryDirectory() as root:
            web = ConversationWebService(Path(root))
            web._preview_reply("run", '{"action":"tool","arguments":{"claim":"不要显示"}}')
            self.assertNotIn("run", web.reply_previews)
            web._preview_reply("run", '{"action":"reply","claim":"文字\\u4e')
            self.assertEqual(web.reply_previews["run"]["text"], "文字")
            web._preview_reply("run", '{"action":"reply","claim":"文字\\u4e2d"}')
            self.assertEqual(web.reply_previews["run"]["text"], "文字中")

    def test_driver_exposes_preview_before_answer_without_committing_it(self):
        """在真实后台 Driver 等待模型终态时读取会话：有草稿、无回答、无完成事实。"""
        ready = threading.Event()
        finish = threading.Event()

        class StreamingProvider(ChatProvider):
            """在终态前显式停住，允许检查真实数据库与 HTTP 门面投影。"""

            def invoke(self, request):
                """观察器收到局部正文，独立信号才允许返回完成结果。"""
                request.preview_text('{"action":"reply","claim":"正在出现的正文')
                ready.set()
                finish.wait(5)
                return super().invoke(request)

        with tempfile.TemporaryDirectory() as root:
            with MythRuntime(Path(root)) as runtime:
                repo = Workspace(runtime).repository
                repo.save_settings({"provider": "ollama", "model": "test"})
                sid = repo.create_session()["id"]
                rid = repo.create_turn(sid, "问题", "preview")["run_id"]
            web = ConversationWebService(Path(root))
            with patch.object(web, "provider", return_value=StreamingProvider()):
                web._spawn(rid)
                try:
                    self.assertTrue(ready.wait(3))
                    view = web.session(sid)
                    self.assertEqual(view["turns"][0]["reply_preview"]["text"], "正在出现的正文")
                    self.assertEqual(view["turns"][0]["status"], "RUNNING")
                    self.assertEqual([m["role"] for m in view["messages"]], ["user"])
                finally:
                    finish.set()
                    deadline = time.monotonic() + 5
                    while rid in web.active and time.monotonic() < deadline:
                        time.sleep(0.02)
                view = web.session(sid)
                self.assertEqual(view["turns"][0]["status"], "COMPLETED")
                self.assertIsNone(view["turns"][0]["reply_preview"])
                self.assertEqual(len(view["messages"]), 2)
