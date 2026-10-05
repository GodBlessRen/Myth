"""并行委派的真实账本、并发与恢复回归。

用屏障证明三个 Provider 确实同时在途，故障注入覆盖原子 Ticket、兄弟恢复隔离、
乱序汇合及 Pause/Stop；延迟替身只测调度等待，不推断真实厂商延迟或质量。
"""

import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from myth.domain import BudgetExceeded, ExecutionDeferred, RecoveryRequired, SimulatedCrash
from myth.models import ModelResult, ProviderKnownFailure, ProviderUnavailable
from myth.platform.control import ControlCommand
from myth.platform.handoff import project_handoffs
from myth.platform.model_pool import pending_reviews, pending_resolutions
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


class ConcurrentProvider:
    """每次工厂创建独立实例；只共享测试同步器，绝不共享父 SQLite 或可变供应商客户端。"""

    provider_id = "ollama"

    def __init__(self, name, probe):
        """保存固定模型名和故障/屏障状态；生产 Runtime 仍负责真实计量。"""
        self.name, self.probe = name, probe
        self.started = False

    def invoke(self, request):
        """记录线程身份，屏障强制重叠，再返回模型名正文或注入已知/未知故障。"""
        probe = self.probe
        with probe["lock"]:
            probe["calls"].append((self.name, threading.get_ident()))
            count = sum(name == self.name for name, _ in probe["calls"])
        if probe.get("barrier") and not self.started:
            probe["barrier"].wait(timeout=5)
        self.started = True
        if probe.get("callback"):
            probe["callback"](self.name, count)
        failure = probe.get("failures", {}).get((self.name, count))
        if failure:
            raise failure
        time.sleep(probe.get("delays", {}).get(self.name, 0))
        with probe["lock"]:
            probe["arrivals"].append(self.name)
        text = json.loads(decision(claim=f"完整结果 {self.name}"))
        text["summary"] = f"摘要 {self.name}"
        if probe.get("plans", {}).get(self.name):
            text = json.loads(probe["plans"][self.name][min(count - 1, len(probe["plans"][self.name]) - 1)])
        return ModelResult(json.dumps(text, ensure_ascii=False), {"model_calls": 1, "input_tokens": 20, "output_tokens": 30},
            {"usage": {"input_tokens": 20, "output_tokens": 30}, "model": self.name}, f"response-{self.name}-{count}")


class ParallelDelegationTests(unittest.TestCase):
    """一个主 Run、三个配置槽位；所有主工具决定都由真实模型账本准入。"""

    def setUp(self):
        """每例使用新数据库与可控 Provider 工厂，不访问用户账号。"""
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.probe = {"lock": threading.Lock(), "calls": [], "arrivals": []}
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime, child_provider_factory=self.factory)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "parent", "max_steps": 24,
            "model_pool": {"children": [{"id": name, "provider": "ollama", "model": name, "tier": 3,
                "pricing": {"currency": "USD", "input": 1, "output": 2}} for name in "ABC"]}})
        self.rid = self.repo.create_turn(self.repo.create_session()["id"], "并行核对三份材料", "parallel")["run_id"]

    def tearDown(self):
        """execute 已汇合全部工作线程；关闭父连接后删除临时文件。"""
        self.runtime.close()
        self.temp.cleanup()

    def factory(self, profile):
        """工厂只接收冻结配置，创建线程私有的 Provider。"""
        return ConcurrentProvider(profile["model"], self.probe)

    def tasks(self):
        """三项显式无互相依赖；每项可以选任意强模型。"""
        return [{"task": f"核对 {name}", "profile_id": name, "context": f"FACT={name}"} for name in "ABC"]

    def prepare(self, capability="agent.parallel", args=None):
        """产生真实父决定并绑定固定步骤，供故障恢复复用原身份。"""
        step = self.repo.begin_step(self.rid)["step"]
        provider = ChatProvider([decision("tool_call", capability, args or {"tasks": self.tasks()})])
        self.did, self.proposal = self.workspace.execution.decide(self.repo.turn(self.rid), step, provider)
        self.repo.bind(self.rid, step, self.did, self.proposal)
        return step

    def execute(self):
        """执行实际并行工具并消费整批观察，主状态只由父线程写入。"""
        result = self.workspace.execution.execute(self.repo.turn(self.rid), self.did, self.proposal)
        self.repo.finish_tool(self.rid, self.repo.turn(self.rid)["current_step"], result)
        return result

    def restart(self):
        """关闭父连接重装配，验证持久子收据而非 Future 缓存负责恢复。"""
        self.runtime.close()
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime, child_provider_factory=self.factory)
        self.repo = self.workspace.repository

    def graph(self):
        """完整调用与费用仅从持久模型/工具账本计算。"""
        return self.workspace.components.observability.execution_graph(run_id=self.rid,
            status=self.repo.turn(self.rid)["status"], model_state=self.repo.decisions.status(self.rid),
            operations=self.repo.operations(self.rid))

    def review(self, child, accepted=True):
        """每个并行子任务独立审核；整批返回不代表整批已采用。"""
        step = self.prepare("agent.evaluate", {"delegation_id": child["delegation_id"],
            "correctness": 90 if accepted else 20, "completeness": 90, "usefulness": 90,
            "accepted": accepted, "failure_kind": "none" if accepted else "quality", "reason": "核对给定材料",
            "capability_tier": 3, "metadata_verdict": "accepted", "metadata_digest": child["telemetry"]["report_digest"]})
        result = self.workspace.execution.execute(self.repo.turn(self.rid), self.did, self.proposal)
        self.repo.finish_tool(self.rid, step, result)

    def test_three_calls_overlap_and_reverse_arrivals_keep_ordinal(self):
        """三线程必须同时越过屏障；最快 C 先返回，父仍收到 A/B/C，图表达 fork/join。"""
        self.probe.update(barrier=threading.Barrier(3), delays={"A": .12, "B": .06, "C": 0})
        self.prepare()
        result = self.execute()
        self.assertEqual(self.probe["arrivals"], ["C", "B", "A"])
        self.assertEqual(len({tid for _, tid in self.probe["calls"]}), 3)
        self.assertNotIn(threading.get_ident(), [tid for _, tid in self.probe["calls"]])
        self.assertEqual([r["summary"] for r in result["results"]], [f"摘要 {name}" for name in "ABC"])
        self.assertEqual(len(pending_reviews(self.repo.turn(self.rid)["activities"])), 3)
        graph = self.graph()
        self.assertEqual(graph["coverage"]["unmapped_model_calls"], 0)
        self.assertEqual(sum(e["kind"] == "fork" for e in graph["edges"]), 3)
        self.assertEqual(sum(e["kind"] == "join" for e in graph["edges"]), 3)
        self.assertEqual(graph["cost_summary"]["pending_by_currency"]["USD"], .00024)
        self.assertTrue(all(x["state"] == "RESOLVED" for x in self.repo.decisions.status(self.rid)["model_invocations"]))

    def test_atomic_tool_budget_rejects_entire_batch_before_calls(self):
        """父批次加三个子 Ticket 共四个工具额度，第三个子准入失败时全部回滚。"""
        self.prepare()
        self.runtime.store.db.execute("UPDATE accounts SET limit_units=3 WHERE run_id=? AND meter='tool_calls'", (self.rid,))
        with self.assertRaises(BudgetExceeded):
            self.execute()
        self.assertEqual(self.probe["calls"], [])
        self.assertEqual(self.repo.operations(self.rid), [])
        self.assertEqual(self.runtime.store.db.execute("SELECT reserved FROM accounts WHERE run_id=? AND meter='tool_calls'", (self.rid,)).fetchone()[0], 0)

    def test_invalid_last_task_leaves_no_partial_admission(self):
        """第三项伪造来源时前两项也未取得 Ticket，更没有已经开始的远端效果。"""
        tasks = self.tasks()
        tasks[-1]["source_refs"] = ["forged"]
        self.prepare(args={"tasks": tasks})
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.repo.operations(self.rid), [])
        self.assertEqual(self.probe["calls"], [])

    def test_four_tasks_are_rejected(self):
        """禁止四项超限，校验拒绝不产生部分派发。"""
        self.prepare(args={"tasks": self.tasks() + self.tasks()[:1]})
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.repo.operations(self.rid), [])

    def test_dependency_on_unreviewed_batch_child_is_rejected(self):
        """依赖其他批次的结果也须主审核，不能凭已返回正文绕过采用边界。"""
        self.prepare()
        first = self.execute()
        tasks = self.tasks()
        tasks[0]["depends_on"] = [first["results"][0]["delegation_id"]]
        self.prepare(args={"tasks": tasks})
        with self.assertRaises(ValueError):
            self.execute()
        self.assertIsNone(self.repo.operation(self.did))
        self.assertEqual(len(self.probe["calls"]), 3)

    def test_three_tasks_can_use_the_same_configured_model(self):
        """并发任务数不是模型槽位数；一个强模型也可以承担三份独立工作。"""
        self.probe["barrier"] = threading.Barrier(3)
        self.prepare(args={"tasks": [{"task": str(i), "profile_id": "A"} for i in range(3)]})
        result = self.execute()
        self.assertEqual(len({tid for _, tid in self.probe["calls"]}), 3)
        self.assertEqual([r["routing"]["profile"]["id"] for r in result["results"]], ["A"] * 3)

    def test_multistep_child_and_siblings_keep_separate_recovery_scope(self):
        """A 展开输入并执行第二步时，仍在途的 B/C 不能被 A 的恢复标成 UNKNOWN。"""
        self.probe.update(barrier=threading.Barrier(3), delays={"B": .1, "C": .15}, plans={"A": [
            decision("tool_call", "input.read", {"offset": 0, "max_chars": 20}), decision(claim="完成 A") ]})
        self.prepare()
        result = self.execute()
        self.assertEqual(result["results"][0]["subagent"]["steps_used"], 2)
        self.assertEqual(len(self.probe["calls"]), 4)
        self.assertTrue(all(x["state"] == "RESOLVED" for x in self.repo.decisions.status(self.rid)["model_invocations"]))
        self.assertEqual(self.graph()["coverage"]["unmapped_model_calls"], 0)

    def test_known_provider_failure_is_local_and_spend_is_retained(self):
        """B 已知终结失败不抹去 A/C 成果；B 已用 Token 仍计入费用并要求主审核。"""
        self.probe["failures"] = {("B", 1): ProviderKnownFailure("known failure",
            usage={"model_calls": 1, "input_tokens": 20, "output_tokens": 30}, raw={})}
        self.prepare()
        result = self.execute()
        self.assertEqual([r["subagent"]["status"] for r in result["results"]], ["COMPLETED", "FAILED", "COMPLETED"])
        self.assertEqual(len(pending_reviews(self.repo.turn(self.rid)["activities"])), 3)
        self.assertEqual(self.graph()["cost_summary"]["pending_by_currency"]["USD"], .00024)

    def test_stop_keeps_late_facts_and_prevents_further_child_steps(self):
        """三个子请求已在途时 Stop；晚到收据仍结算，A 的 input.read 后继模型不开始。"""
        def stop(name, count):
            """通过另一连接发 Stop，模拟与父等待并发的用户控制。"""
            if name == "A" and count == 1:
                with MythRuntime(self.root) as runtime:
                    Workspace(runtime).control.command(self.rid, ControlCommand.STOP)
        self.probe.update(barrier=threading.Barrier(3), callback=stop, plans={"A": [
            decision("tool_call", "input.read", {"offset": 0, "max_chars": 20}), decision(claim="不得调用") ]})
        self.prepare()
        result = self.execute()
        self.assertEqual(self.repo.turn(self.rid)["status"], "CANCELLED")
        self.assertEqual(len(self.probe["calls"]), 3)
        self.assertEqual(len(result["results"]), 3)
        self.assertEqual(self.graph()["cost_summary"]["pending_by_currency"]["USD"], .00024)

    def test_large_batch_context_keeps_recallable_navigation(self):
        """三份长正文不进入父 Prompt；长摘要预览明确裁剪，仍可逐项回读完整对象。"""
        payload = json.loads(decision(claim="正文" * 5000))
        payload["summary"] = "摘要" * 600
        self.probe["plans"] = {name: [json.dumps(payload, ensure_ascii=False)] for name in "ABC"}
        self.prepare()
        result = self.execute()
        projected = project_handoffs(self.repo.turn(self.rid)["activities"])[0]["result"]["results"]
        self.assertTrue(all(r["summary_truncated"] and len(r["summary"]) == 300 for r in projected))
        self.review(result["results"][0])
        for child in result["results"]:
            self.assertEqual(self.runtime.objects.get(child["handoff"]["content_ref"]).decode(), "正文" * 5000)

    def test_full_parent_loop_delegates_reviews_and_completes(self):
        """通过真实主应用循环完成并发、三次独立审核及汇总，无特殊测试驱动捷径。"""
        self.probe["barrier"] = threading.Barrier(3)
        parent = ChatProvider()
        def plan(request):
            """主替身根据持久结果产生下一步；第一份批次观察必须含所有任务身份。"""
            parent.calls.append(request)
            children = [op["result"] for op in self.repo.operations(self.rid)
                        if op["capability"] == "agent.delegate" and op["state"] == "RESOLVED"]
            pending = pending_reviews(self.repo.turn(self.rid)["activities"])
            if not children:
                text = decision("tool_call", "agent.parallel", {"tasks": self.tasks()})
            elif pending:
                if len(pending) == 3:
                    messages = "\n".join(m.content for m in request.messages)
                    self.assertTrue(all(child["delegation_id"] in messages for child in children))
                child = next(c for c in children if c["delegation_id"] == pending[0])
                text = decision("tool_call", "agent.evaluate", {"delegation_id": child["delegation_id"],
                    "correctness": 90, "completeness": 90, "usefulness": 90, "accepted": True,
                    "failure_kind": "none", "reason": "根据固定材料核对", "capability_tier": 3,
                    "metadata_verdict": "accepted", "metadata_digest": child["telemetry"]["report_digest"]})
            else:
                text = decision(claim="主模型完成并汇总三份结果")
            return ModelResult(text, {"model_calls": 1, "input_tokens": 20, "output_tokens": 30}, {})
        with patch.object(parent, "invoke", new=plan):
            self.workspace.run(self.rid, parent)
        self.assertEqual(self.repo.turn(self.rid)["status"], "COMPLETED")
        self.assertEqual(len(self.probe["calls"]), 3)
        self.assertEqual(len(parent.calls), 5)
        self.assertEqual(pending_reviews(self.repo.turn(self.rid)["activities"]), [])

    def test_crash_after_model_receipt_recovers_without_provider(self):
        """B 收据之后绑定前退出；A/C 已结算，重启仅消费 B 事实并补父批次收据。"""
        from myth.adapters.subagent_runtime import SubagentRepository
        original = SubagentRepository.bind
        def crash(repository, run_id, step, did, proposal):
            """只在指定子游标注入崩溃，其他工作线程继续记录真实收据。"""
            if run_id.endswith("_child_2"):
                raise SimulatedCrash()
            return original(repository, run_id, step, did, proposal)
        self.prepare()
        with patch.object(SubagentRepository, "bind", new=crash):
            with self.assertRaises(SimulatedCrash):
                self.execute()
        self.assertEqual(len(self.probe["calls"]), 3)
        self.restart()
        with patch.object(self.workspace.execution, "provider_factory", side_effect=AssertionError("no replay")):
            self.assertTrue(self.workspace.execution.recover(self.rid))
            result = self.execute()
        self.assertEqual(len(result["results"]), 3)
        self.assertIsNone(result["parallel"]["wall_ms"])
        self.assertEqual(len(self.probe["calls"]), 3)
        self.assertEqual(self.graph()["coverage"]["unmapped_model_calls"], 0)

    def test_crash_after_batch_ticket_before_workers_resumes_same_contracts(self):
        """整批 Ticket 已提交但线程未开始：核对不请求 Provider，正常驱动使用原合同继续。"""
        self.prepare()
        with patch.object(self.workspace.execution.parallel, "_work", side_effect=SimulatedCrash()):
            with self.assertRaises(SimulatedCrash):
                self.execute()
        frozen = self.repo.operation(self.did)["intent"]
        self.assertEqual(self.probe["calls"], [])
        self.restart()
        self.assertTrue(self.workspace.execution.recover(self.rid))
        self.assertEqual(self.probe["calls"], [])
        result = self.execute()
        self.assertEqual(self.repo.operation(self.did)["intent"], frozen)
        self.assertEqual(len(result["results"]), 3)

    def test_recorded_decision_dedup_does_not_reconcile_live_sibling(self):
        """A 完成后的去重回读发生在 B.invoke 内，不能把 B 的在途 Ticket 标为 UNKNOWN。"""
        def recall(name, count):
            """从线程私有连接观察 A 结算后回读其决定，并检查仍在当前回调内的 B。"""
            if name != "B":
                return
            from myth.decision_runtime import DecisionRuntime
            with MythRuntime(self.root) as runtime:
                decisions = DecisionRuntime(runtime)
                key = json.loads(runtime.store.db.execute(
                    "SELECT intent_json FROM workspace_operations WHERE decision_id=?", (self.did + "_child_1",)
                ).fetchone()[0])["delegate"]["request_key"]
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    row = runtime.store.db.execute("SELECT m.state FROM model_request_keys k JOIN model_invocations m "
                        "USING(model_attempt_id) WHERE k.request_key=?", (key,)).fetchone()
                    if row and row[0] == "RESOLVED":
                        break
                    time.sleep(.005)
                self.assertIsNotNone(decisions.recorded_decision(self.rid, key))
                live = [m for m in decisions.status(self.rid)["model_invocations"] if m["model_id"] == "B"]
                self.assertEqual(live[0]["state"], "TICKETED")
        self.probe["callback"] = recall
        self.prepare()
        self.execute()

    def test_zero_dispatch_retry_only_restarts_failed_child(self):
        """B 明确零派发断线，A/C 收据保留；重启只再调用 B，共四次而非六次。"""
        self.probe["failures"] = {("B", 1): ProviderUnavailable()}
        self.prepare()
        with self.assertRaises(ProviderUnavailable):
            self.execute()
        self.restart()
        self.assertTrue(self.workspace.execution.recover(self.rid))
        result = self.execute()
        self.assertEqual([sum(n == name for n, _ in self.probe["calls"]) for name in "ABC"], [1, 2, 1])
        self.assertEqual(len(result["results"][1]["telemetry"]["attempt_ids"]), 2)
        self.assertEqual(self.graph()["cost_summary"]["pending_by_currency"]["USD"], .00024)

    def test_unknown_child_never_replays_successful_siblings_or_itself(self):
        """B 在 Ticket 后传输异常进入 UNKNOWN；A/C 已完成仍留账，整批不能盲目重派。"""
        self.probe.update(barrier=threading.Barrier(3), failures={("B", 1): ValueError("decode after dispatch")})
        self.prepare()
        with self.assertRaises(RecoveryRequired):
            self.execute()
        self.restart()
        self.assertFalse(self.workspace.execution.recover(self.rid))
        with self.assertRaises(RecoveryRequired):
            self.execute()
        self.assertEqual(len(self.probe["calls"]), 3)
        children = [x for x in self.repo.operations(self.rid) if x["capability"] == "agent.delegate"]
        self.assertEqual(sum(x["state"] == "RESOLVED" for x in children), 2)

    def test_pause_and_resume_keep_all_late_receipts(self):
        """全部子调用在途时 Pause，Resume 复用已返回模型收据，各模型只调用一次。"""
        def pause(name, count):
            """模拟用户从另一连接发送控制命令，不跨线程使用测试父连接。"""
            if name == "A" and count == 1:
                with MythRuntime(self.root) as runtime:
                    Workspace(runtime).control.command(self.rid, ControlCommand.PAUSE)
        self.probe.update(barrier=threading.Barrier(3), callback=pause)
        self.prepare()
        with self.assertRaises(ExecutionDeferred):
            self.execute()
        self.assertEqual(self.repo.turn(self.rid)["status"], "PAUSED")
        self.workspace.control.command(self.rid, ControlCommand.RESUME)
        result = self.execute()
        self.assertEqual(len(result["results"]), 3)
        self.assertEqual(len(self.probe["calls"]), 3)

    def test_model_budget_competition_cannot_overspend(self):
        """两个子调用额度供三者争抢，只允许两次调用，第三项返回预算缺口给主审核。"""
        self.prepare()
        self.runtime.store.db.execute("UPDATE accounts SET limit_units=3 WHERE run_id=? AND meter='model_calls'", (self.rid,))
        result = self.execute()
        self.assertEqual(len(self.probe["calls"]), 2)
        self.assertEqual(sum(r["subagent"]["status"] == "BUDGET_EXHAUSTED" for r in result["results"]), 1)
        account = self.runtime.store.db.execute("SELECT settled,reserved,unknown_held FROM accounts WHERE run_id=? AND meter='model_calls'", (self.rid,)).fetchone()
        self.assertEqual(tuple(account), (3, 0, 0))

    def test_each_child_review_and_rejection_projection_remain_independent(self):
        """采用 A/C、拒收 B；B 正文从默认上下文移除，其花销及补做义务保留。"""
        self.prepare()
        result = self.execute()
        for child in result["results"]:
            self.review(child, accepted=child["ordinal"] != 2)
        activities = self.repo.turn(self.rid)["activities"]
        self.assertEqual(pending_reviews(activities), [])
        self.assertEqual(pending_resolutions(activities), [result["results"][1]["delegation_id"]])
        projected = project_handoffs(activities)[0]["result"]["results"]
        self.assertEqual([r["adoption"] for r in projected], ["accepted", "rejected", "accepted"])
        self.assertNotIn("摘要 B", projected[1]["summary"])
        self.assertEqual(self.graph()["cost_summary"]["reviewed_by_currency"]["USD"], .00024)

    def test_wait_time_benchmark(self):
        """相同 250/500/750ms 延迟替身比较串行和并行；屏障验证比脆弱墙钟阈值更可靠。"""
        self.probe["delays"] = {"A": .25, "B": .5, "C": .75}
        started = time.monotonic()
        for name in "ABC":
            provider = self.factory({"model": name})
            step = self.prepare("agent.delegate", {"task": f"核对 {name}", "profile_id": name})
            result = self.workspace.execution.execute(self.repo.turn(self.rid), self.did, self.proposal, provider=provider)
            self.repo.finish_tool(self.rid, step, result)
        serial_ms = int((time.monotonic() - started) * 1000)
        self.probe.update(calls=[], arrivals=[], barrier=threading.Barrier(3))
        self.prepare()
        started = time.monotonic()
        result = self.execute()
        parallel_ms = int((time.monotonic() - started) * 1000)
        self.assertEqual(len({tid for _, tid in self.probe["calls"]}), 3)
        print(json.dumps({"benchmark": "controlled-provider-wait", "child_delays_ms": [250, 500, 750],
            "serial_ms": serial_ms, "parallel_ms": parallel_ms, "batch_wall_ms": result["parallel"]["wall_ms"]}))


if __name__ == "__main__":
    unittest.main()
