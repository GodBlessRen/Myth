"""Execution Graph 只读投影测试。
图由已有 model/decision/operation durable facts 生成；不会创建新的执行状态或授权。
"""

import unittest

from myth.platform.observability import TraceProjection


# Execution Graph 只读投影回归集合；固定输入验证映射覆盖，不代表真实模型或外部工具执行。
class ExecutionGraphProjectionTests(unittest.TestCase):
    # 回归断言：父模型、Tool 与隔离 Child 只由已有 durable facts 投影，不能新增执行真相。
    def test_projects_parent_tool_and_isolated_subagent_without_new_truth(self):
        graph = TraceProjection().execution_graph(
            run_id="run-1",
            status="COMPLETED",
            model_state={
                "model_invocations": [
                    {
                        "model_attempt_id": "ma-parent-1",
                        "request_key": "conversation:run-1:1",
                        "state": "SETTLED",
                    },
                    {
                        "model_attempt_id": "ma-child-1",
                        "request_key": "subagent:run-1:decision-1:isolated_worker",
                        "state": "SETTLED",
                    },
                    {
                        "model_attempt_id": "ma-parent-2",
                        "request_key": "conversation:run-1:2",
                        "state": "SETTLED",
                    },
                ],
                "decisions": [
                    {
                        "decision_id": "decision-1",
                        "model_attempt_id": "ma-parent-1",
                        "decision_type": "tool_call",
                        "payload": {
                            "decision_type": "tool_call",
                            "capability_id": "agent.delegate",
                        },
                    },
                    {
                        "decision_id": "decision-2",
                        "model_attempt_id": "ma-parent-2",
                        "decision_type": "request_completion",
                        "payload": {"decision_type": "request_completion"},
                    },
                ],
            },
            operations=[
                {
                    "decision_id": "decision-1",
                    "capability": "agent.delegate",
                    "ticket_id": "ticket-1",
                    "state": "RESOLVED",
                    "result": {
                        "subagent": {
                            "role_id": "isolated_worker",
                            "request_key": "subagent:run-1:decision-1:isolated_worker",
                        }
                    },
                }
            ],
        )

        self.assertEqual(graph["version"], "execution-graph-v1")
        self.assertTrue(graph["experimental"])
        self.assertEqual(graph["coverage"]["model_calls"], 3)
        self.assertEqual(graph["coverage"]["mapped_model_calls"], 3)
        self.assertEqual(graph["coverage"]["unmapped_model_calls"], 0)
        kinds = [node["kind"] for node in graph["nodes"]]
        self.assertEqual(
            kinds,
            ["run", "model", "tool", "subagent", "model", "state"],
        )
        delegate_edges = [
            edge for edge in graph["edges"] if edge["kind"] == "delegate"
        ]
        self.assertEqual(len(delegate_edges), 1)
        child = next(node for node in graph["nodes"] if node["kind"] == "subagent")
        self.assertEqual(child["role_id"], "isolated_worker")
        self.assertEqual(child["parent_decision_id"], "decision-1")

    # 回归断言：无法归类的模型调用保持 unmapped，观测层不得凭猜测补齐 Execution Graph。
    def test_unclassified_model_calls_remain_explicitly_unmapped(self):
        graph = TraceProjection().execution_graph(
            run_id="run-2",
            status="RUNNING",
            model_state={
                "model_invocations": [
                    {
                        "model_attempt_id": "ma-other",
                        "request_key": "other:run-2:1",
                        "state": "SETTLED",
                    }
                ],
                "decisions": [],
            },
            operations=[],
        )
        self.assertEqual(graph["coverage"]["model_calls"], 1)
        self.assertEqual(graph["coverage"]["mapped_model_calls"], 0)
        self.assertEqual(graph["coverage"]["unmapped_model_calls"], 1)


if __name__ == "__main__":
    unittest.main()
