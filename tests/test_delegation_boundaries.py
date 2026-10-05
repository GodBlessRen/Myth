"""委派准入与双层收据回归。

父工具额度必须先于子模型费用；模型已完成、父工具收据未写的崩溃窗口只做本地
补收据。工具额度、模型额度、子结果与未知状态分别核对，不借替身推断远端可靠性。
"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from myth.domain import BudgetExceeded, RecoveryRequired, SimulatedCrash
from myth.runtime import MythRuntime
from myth.workspace import Workspace
from test_workspace import ChatProvider, decision


class DelegationBoundaryTests(unittest.TestCase):
    """每例固定一个真实父决定；后续 Provider 仅供子模型使用。"""

    def setUp(self):
        """准入父 Turn/Step/Decision；不能用伪造的决定身份绕过工具所有权检查。"""
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.repo.save_settings({"provider": "ollama", "model": "fixture", "model_pool": {"children": [
            {"id": "fixture", "provider": "ollama", "model": "fixture", "tier": 2}]}})
        sid = self.repo.create_session()["id"]
        self.rid = self.repo.create_turn(sid, "review a bounded task", "delegate-boundary")["run_id"]
        step = self.repo.begin_step(self.rid)["step"]
        parent = ChatProvider([decision("tool_call", "agent.delegate", {"task": "检查 FACT=A"})])
        self.did, self.proposal = self.workspace.execution.decide(self.repo.turn(self.rid), step, parent)
        self.repo.bind(self.rid, step, self.did, self.proposal)
        self.child = ChatProvider([decision(claim="已核对")])

    def tearDown(self):
        """先关闭本例连接，再删除临时持久状态。"""
        self.runtime.close()
        self.temp.cleanup()

    def execute(self):
        """调用生产工具入口；子调用计数、Ticket 和预算都从同一个父 Run 检查。"""
        return self.workspace.execution.execute(self.repo.turn(self.rid), self.did, self.proposal, provider=self.child)

    def test_tool_budget_rejects_before_child_model_call(self):
        """耗尽工具额度后不得先花子模型费用；准入失败不留下工具机会。"""
        self.runtime.store.db.execute(
            "UPDATE accounts SET limit_units=0 WHERE run_id=? AND meter='tool_calls'", (self.rid,)
        )
        with self.assertRaises(BudgetExceeded):
            self.execute()
        self.assertEqual(self.child.calls, [])
        self.assertEqual(self.repo.operations(self.rid), [])

    def test_tool_ticket_is_durable_before_child_invocation(self):
        """在 invoke 的实际边界核对父工具 Ticket，不能用调用后的事件顺序冒充授权。"""
        invoke = self.child.invoke

        def inspect(request):
            """子模型开始时，父工具额度已经预留且 Tool Ticket 可从 SQLite 读取。"""
            op = self.repo.operation(self.did)
            self.assertIsNotNone(op)
            self.assertEqual(op["state"], "TICKETED")
            return invoke(request)

        with patch.object(self.child, "invoke", side_effect=inspect):
            result = self.execute()
        self.assertEqual(result["summary"], "已核对")
        self.assertEqual(self.repo.operation(self.did)["state"], "RESOLVED")

    def test_model_receipt_recovers_missing_tool_receipt_without_provider(self):
        """模型已完成但工具发布前退出；重开只消费固定子决定，模型调用次数保持一次。"""
        with patch.object(self.workspace.execution, "_record_tool_receipt", side_effect=SimulatedCrash()):
            with self.assertRaises(SimulatedCrash):
                self.execute()
        self.assertEqual(len(self.child.calls), 1)
        self.runtime.close()
        self.runtime = MythRuntime(self.root)
        self.workspace = Workspace(self.runtime)
        self.repo = self.workspace.repository
        self.assertTrue(self.workspace.execution.recover(self.rid))
        result = self.execute()
        self.assertEqual(result["summary"], "已核对")
        self.assertEqual(len(self.child.calls), 1)
        self.assertEqual(self.repo.operation(self.did)["state"], "RESOLVED")
        account = self.runtime.store.db.execute(
            "SELECT reserved,settled,unknown_held FROM accounts WHERE run_id=? AND meter='tool_calls'", (self.rid,)
        ).fetchone()
        self.assertEqual(tuple(account), (0, 1, 0))

    def test_crash_before_child_ticket_recovers_as_known_unstarted(self):
        """父 Ticket 后、子模型准入前退出：没有子 Ticket 可证明未派发，不执行补跑。"""
        with patch.object(self.repo.decisions, "request_decision", side_effect=SimulatedCrash()):
            with self.assertRaises(SimulatedCrash):
                self.execute()
        self.assertTrue(self.workspace.execution.recover(self.rid))
        self.assertEqual(self.child.calls, [])
        self.assertIn("not started", self.repo.operation(self.did)["result"]["error"])

    def test_transport_value_error_is_unknown_and_never_replayed(self):
        """供应商在 Ticket 后抛 ValueError 也可能效果未知，不能当作参数拒绝闭合父收据。"""
        with patch.object(self.child, "invoke", side_effect=ValueError("transport decode failed")) as invoke:
            with self.assertRaises(RecoveryRequired):
                self.execute()
            self.assertFalse(self.workspace.execution.recover(self.rid))
            with self.assertRaises(RecoveryRequired):
                self.execute()
        self.assertEqual(invoke.call_count, 1)
        self.assertIsNone(self.repo.operation(self.did)["result"])


if __name__ == "__main__":
    unittest.main()
