"""会话统计的计量、持久恢复与本机 HTTP 回归。
固定时钟只证明统计口径；真实工具/SQLite/子进程/HTTP 验证复用与恢复，不访问真实模型或账号。
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import urlopen

from myth.models import ModelResult
from myth.runtime import MythRuntime
from myth.session_statistics import session_statistics
from myth.web import AgentWebService, make_handler
from myth.web_workspace import ConversationWebService
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


# 固定调用的纯投影反例；不依赖展示层平均值或供应商价格/质量。
class StatisticsRuleTests(unittest.TestCase):
    # TTFT 按每次调用平均，TPS 按总输出/对应总用时；失败时间可观察但不能参与成功输出速率。
    def test_call_weighted_ttft_and_paired_token_throughput(self):
        invocations = [{"model_attempt_id": str(i), "outcome": "SUCCEEDED", "usage": usage} for i, usage in enumerate([
            {"provider_wall_ms": 1000, "output_tokens": 200, "time_to_first_token_ms": 100},
            {"provider_wall_ms": 3000, "output_tokens": 100, "time_to_first_token_ms": 200},
            {"provider_wall_ms": 6000, "output_tokens": 700, "time_to_first_token_ms": 900},
        ])]
        invocations.append({"outcome": "FAILED", "usage": {"provider_wall_ms": 5000, "output_tokens": 99999}})
        result = session_statistics(invocations, [])
        self.assertEqual(result["model_wall_ms"], 15000)
        self.assertEqual(result["average_ttft_ms"], 400)
        self.assertEqual(result["output_tps"], 100)
        self.assertEqual(result["tps_wall_ms"], 10000)
        self.assertEqual(result["tps_samples"], 3)

    # 没有输出的调用不能借另一调用的时长做除数，缺测应为未报告。
    def test_unpaired_output_and_time_do_not_make_a_rate(self):
        result = session_statistics([
            {"outcome": "SUCCEEDED", "usage": {"output_tokens": 100}},
            {"outcome": "SUCCEEDED", "usage": {"provider_wall_ms": 2000}},
            {"outcome": "UNKNOWN", "usage": {"provider_wall_ms": 1000, "output_tokens": 50}},
        ], [])
        self.assertIsNone(result["output_tps"])
        self.assertEqual(result["model_timing_samples"], 2)
        self.assertEqual(result["model_attempts"], 3)

    # bool/文本/负数及首 token 晚于完成耗时均不是可用计量；不把未决工具的字段当完成收据。
    def test_malformed_and_missing_metrics_remain_unreported(self):
        result = session_statistics([
            {"usage": {"provider_wall_ms": True, "time_to_first_token_ms": -1}},
            {"usage": {"provider_wall_ms": "1000", "time_to_first_token_ms": False}},
            {"usage": {"provider_wall_ms": 500, "time_to_first_token_ms": 600}},
        ], [{"state": "RESOLVED", "tool_wall_ms": "100"}, {"state": "UNKNOWN", "tool_wall_ms": 100}])
        self.assertEqual(result["model_wall_ms"], 500)
        self.assertIsNone(result["average_ttft_ms"])
        self.assertIsNone(result["tool_wall_ms"])
        self.assertIsNone(result["output_tps"])

    # 实测零耗时与缺测不同；零毫秒不能作为速度除数，空会话累计可以明确为零。
    def test_measured_zero_and_empty_session(self):
        result = session_statistics([{"outcome": "SUCCEEDED", "usage": {"provider_wall_ms": 0,
            "output_tokens": 100, "time_to_first_token_ms": 0}}], [{"state": "RESOLVED", "tool_wall_ms": 0}])
        self.assertEqual(result["model_wall_ms"], 0)
        self.assertEqual(result["tool_wall_ms"], 0)
        self.assertEqual(result["average_ttft_ms"], 0)
        self.assertIsNone(result["output_tps"])
        empty = session_statistics([], [])
        self.assertEqual(empty["model_wall_ms"], 0)
        self.assertEqual(empty["tool_wall_ms"], 0)
        self.assertIsNone(empty["average_ttft_ms"])

    # 重复身份只能记一次，避免恢复/投影合并把同一个模型或工具收据重复计量。
    def test_stable_call_identities_are_deduplicated(self):
        model = {"model_attempt_id": "m", "outcome": "SUCCEEDED", "usage": {"provider_wall_ms": 1000, "output_tokens": 20}}
        tool = {"decision_id": "t", "state": "RESOLVED", "tool_wall_ms": 1500}
        result = session_statistics([model, model], [tool, tool])
        self.assertEqual(result["model_attempts"], 1)
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(result["tool_wall_ms"], 1500)
        self.assertEqual(result["output_tps"], 20)


# 每个用例独立 Runtime；指标来自持久调用记录，页面读取不能签发模型/工具机会。
class SessionStatisticsTests(unittest.TestCase):
    # 新会话使用固定供应商设置，避免读取本机真实配置或认证。
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "test"})
        self.sid = self.repo.create_session()["id"]

    # 关闭本测试的 SQLite 再清理目录，子进程和 HTTP 由各自用例 finally 收束。
    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    # 独立真实数学工具，避免模型调用干扰工具时钟；固定决定通过正常 Ticket/收据路径执行。
    def tool(self):
        rid = self.repo.create_turn(self.sid, "Tool timing fixture", "tool-fixture")["run_id"]
        self.repo.begin_step(rid)
        did, value = self.workspace.execution.decide(self.repo.turn(rid), 1,
            ChatProvider([decision("tool_call", "math.calculate", {"expression": "2+3"})]))
        self.repo.bind(rid, 1, did, value)
        with patch("time.monotonic", side_effect=[10, 11.25]):
            result = self.workspace.execution.execute(self.repo.turn(rid), did, value)
        return rid, did, value, result

    # 同一会话两轮三次调用，不平均每轮均值；另一个会话、页面读取和服务重建不能混入/重复计算。
    def test_session_totals_survive_service_restart_and_isolate_other_sessions(self):
        clock = [100.0]
        outputs = [decision("tool_call", "math.calculate", {"expression": "2+3"}), decision(), decision()]
        walls = [2, 4, 1]
        ttfts = [500, 1500, 100]
        tokens = [20, 80, 20]
        provider = ChatProvider(outputs)
        # 供应商夹具推进单调时钟；Runtime 自己记录调用 wall，不能用供应商宣称的 wall 替代。
        def invoke(request):
            index = len(provider.calls)
            provider.calls.append(request)
            clock[0] += walls[index]
            return ModelResult(outputs[index], {"model_calls": 1, "input_tokens": 10,
                "output_tokens": tokens[index], "time_to_first_token_ms": ttfts[index]}, {})
        provider.invoke = invoke
        with patch("time.monotonic", side_effect=lambda: clock[0]):
            rid = self.repo.create_turn(self.sid, "First statistics turn", "first")["run_id"]
            self.workspace.run(rid, provider)
            rid2 = self.repo.create_turn(self.sid, "Second statistics turn", "second")["run_id"]
            self.workspace.run(rid2, provider)
        other = self.repo.create_session()["id"]
        other_rid = self.repo.create_turn(other, "Separate session", "other")["run_id"]
        self.workspace.run(other_rid, ChatProvider())
        expected = ConversationWebService(self.root).session(self.sid)["statistics"]
        self.assertEqual(expected["model_attempts"], 3)
        self.assertEqual(expected["model_wall_ms"], 7000)
        self.assertEqual(expected["average_ttft_ms"], 700)
        self.assertAlmostEqual(expected["output_tps"], 120 / 7)
        self.assertEqual(expected["tool_calls"], 1)
        self.assertEqual(expected["tool_timing_samples"], 1)
        self.assertEqual(ConversationWebService(self.root).session(self.sid)["statistics"], expected)

    # 稳定工具决定复用原计时；恢复不重新执行，也不把计量塞进模型下一步的工具结果正文。
    def test_tool_receipt_persists_time_and_reuse_keeps_budget(self):
        rid, did, value, result = self.tool()
        operation = self.repo.operation(did)
        self.assertEqual(operation["tool_wall_ms"], 1250)
        self.assertNotIn("tool_wall_ms", result)
        receipt = json.loads((self.workspace.execution.receipts / f"{did}.json").read_text())
        self.assertEqual(receipt["tool_wall_ms"], 1250)
        with patch("time.monotonic", side_effect=AssertionError("reused tool must not restart timing")):
            self.assertEqual(self.workspace.execution.execute(self.repo.turn(rid), did, value), result)
        self.assertEqual(self.repo.operation(did)["tool_wall_ms"], 1250)
        account = self.runtime.store.db.execute("SELECT settled FROM accounts WHERE run_id=? AND meter='tool_calls'", (rid,)).fetchone()
        self.assertEqual(account[0], 1)


    # 缺测或损坏的观测字段不能阻止真实结果核对，不能变成伪造零耗时。
    def test_missing_or_invalid_timing_does_not_change_recovery(self):
        rid = self.repo.create_turn(self.sid, "Missing timing", "missing-timing")["run_id"]
        for index, timing in enumerate([None, True, -1, "250"]):
            step = self.repo.begin_step(rid)["step"]
            did, proposal = self.workspace.execution.decide(self.repo.turn(rid), step,
                ChatProvider([decision("tool_call", "math.calculate", {"expression": "2+3"})]))
            self.repo.bind(rid, step, did, proposal)
            result = {"capability_id": "math.calculate", "value": 5}
            op = self.repo.start_operation(rid, did, "math.calculate", {"result": result, "write_bytes": 0})
            receipt = {"decision_id": did, "ticket_id": op["ticket_id"], "result": result}
            if timing is not None:
                receipt["tool_wall_ms"] = timing
            (self.workspace.execution.receipts / f"{did}.json").write_text(json.dumps(receipt), encoding="utf-8")
            self.assertTrue(self.workspace.execution.recover(rid))
            self.assertIsNone(self.repo.operation(did)["tool_wall_ms"])
            self.assertEqual(self.repo.operation(did)["state"], "RESOLVED")
            self.repo.finish_tool(rid, step, result)

    # 真正 os._exit 发生在收据发布后、数据库结算前；下一进程按原收据恢复时间/预算，不重做工具。
    def test_process_exit_after_tool_receipt_restores_same_measurement(self):
        script = '''import json,os,sys
from pathlib import Path
from unittest.mock import patch
from myth.runtime import MythRuntime
from myth.workspace import Workspace
sys.path.insert(0,sys.argv[2])
from test_workspace import ChatProvider,decision
with MythRuntime(Path(sys.argv[1])) as runtime:
 w=Workspace(runtime);r=w.repository;r.save_settings({"provider":"ollama","model":"test"})
 sid=r.create_session()["id"];rid=r.create_turn(sid,"Crash timing","crash")["run_id"]
 r.begin_step(rid);did,d=w.execution.decide(r.turn(rid),1,ChatProvider([decision("tool_call","math.calculate",{"expression":"2+3"})]))
 r.bind(rid,1,did,d)
 (Path(sys.argv[1])/"identities.json").write_text(json.dumps({"sid":sid,"rid":rid,"did":did}))
 r.settle_operation=lambda *args,**kwargs: os._exit(83)
 with patch("time.monotonic",side_effect=[10,11.25]):w.execution.execute(r.turn(rid),did,d)
'''
        with tempfile.TemporaryDirectory() as root:
            child = subprocess.run([sys.executable, "-c", script, root, str(Path(__file__).parent)], capture_output=True, text=True, timeout=15)
            self.assertEqual(child.returncode, 83, child.stderr)
            ids = json.loads((Path(root) / "identities.json").read_text())
            with MythRuntime(root) as runtime:
                workspace = Workspace(runtime)
                workspace.repository.interrupt(ids["rid"], "crash before settlement")
                self.assertTrue(workspace.execution.recover(ids["rid"]))
                op = workspace.repository.operation(ids["did"])
                self.assertEqual(op["state"], "RESOLVED")
                self.assertEqual(op["tool_wall_ms"], 1250)
                self.assertTrue(workspace.execution.recover(ids["rid"]))
                self.assertEqual(ConversationWebService(root).session(ids["sid"])["statistics"]["tool_wall_ms"], 1250)

    # 真正本机 HTTP 返回同一统计对象且交付脚本；GET 不签发工具/模型机会。
    def test_http_session_statistics_and_asset_contract(self):
        self.tool()
        service = AgentWebService(self.root)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(url + f"/api/workspace/sessions/{self.sid}", timeout=3) as response:
                value = json.load(response)
            self.assertEqual(value["statistics"]["tool_wall_ms"], 1250)
            self.assertEqual(value["statistics"]["tool_calls"], 1)
            with urlopen(url + "/statistics.js", timeout=3) as response:
                self.assertIn(b"sessionStatisticsRows", response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__ == "__main__":
    unittest.main()
