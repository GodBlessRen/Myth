"""Replay World 回归：历史只覆盖已发生分支，候选策略不能从离线重放获得线上发布权限。"""

from __future__ import annotations

import unittest

from myth.platform.replay import ReplayLab, ReplayStatus, ReplayWorld


# 固定构造同一比较组的历史路径；数据只代表已验收路线快照，不模拟真实模型或工具。
def _group():
    common = {
        "comparison_key": "same-frozen-world",
        "eligible": 1,
        "environment_scope": "frozen-context-v1",
    }
    return [
        {
            **common,
            "run_id": "run-a",
            "status": "CHAMPION",
            "metrics": {"tool_calls": 2, "steps": 3, "total_tokens": 100},
            "path": [
                {"step": 1, "kind": "tool", "capability": "project.search", "arguments": {"path": "src"}},
                {"step": 2, "kind": "tool", "capability": "project.read", "arguments": {"path": "src/app.py"}},
                {"step": 3, "kind": "reply"},
            ],
        },
        {
            **common,
            "run_id": "run-b",
            "status": "CHAMPION",
            "metrics": {"tool_calls": 1, "steps": 2, "total_tokens": 80},
            "path": [
                {"step": 1, "kind": "tool", "capability": "project.search", "arguments": {"path": "src"}},
                {"step": 2, "kind": "reply"},
            ],
        },
    ]


# Replay World 的纯历史边界测试；不触及 Runtime SQLite、外部 Provider 或生产策略指针。
class ReplayWorldTests(unittest.TestCase):
    # 两条共享前缀的真实路线应合并成一棵树，分叉只来自历史中真实出现的下一动作。
    def test_merges_observed_routes_into_prefix_tree(self):
        world = ReplayWorld.from_sota_group(_group())
        root = world.observe()
        self.assertEqual(world.covered_runs, 2)
        self.assertEqual(len(root.available_actions), 1)
        self.assertEqual(root.available_actions[0].label, "project.search")
        self.assertEqual(root.available_actions[0].visits, 2)

        after_search = world.step(root.node_id, root.available_actions[0].key)
        self.assertEqual(
            {action.label for action in after_search.available_actions},
            {"project.read", "reply"},
        )

    # 选择历史从未出现的动作必须返回 UNOBSERVED，不能生成虚假的 terminal metrics 或成功结论。
    def test_unobserved_action_remains_explicit(self):
        world = ReplayWorld.from_sota_group(_group())

        result = world.evaluate(lambda observation: "tool:never-seen")

        self.assertEqual(result.status, ReplayStatus.UNOBSERVED)
        self.assertEqual(result.terminal_run_ids, ())
        self.assertEqual(result.terminal_metrics, ())
        self.assertIn("outside the realized historical search space", result.reason)

    # 候选策略可在已实现分叉中选择较短历史路线；返回的是原 Run 指标，不重新执行工具或模型。
    def test_policy_can_select_an_observed_terminal_route(self):
        world = ReplayWorld.from_sota_group(_group())

        def decide(observation):
            preferred = "project.search" if observation.depth == 0 else "reply"
            return next(
                action.key
                for action in observation.available_actions
                if action.label == preferred
            )

        result = world.evaluate(decide)
        self.assertEqual(result.status, ReplayStatus.TERMINAL)
        self.assertEqual(result.terminal_run_ids, ("run-b",))
        self.assertEqual(result.terminal_metrics[0]["total_tokens"], 80)
        self.assertEqual(result.steps, 2)

    # 同一前缀本身若历史上曾终止，策略可显式停止并落到该真实终点，而不是被迫继续另一条分支。
    def test_policy_stop_uses_only_observed_terminal_prefix(self):
        group = _group()
        group.append(
            {
                "comparison_key": "same-frozen-world",
                "eligible": 1,
                "run_id": "run-root",
                "metrics": {"tool_calls": 0, "steps": 0, "total_tokens": 10},
                "path": [],
            }
        )
        world = ReplayWorld.from_sota_group(group)
        result = world.evaluate(lambda observation: None)
        self.assertEqual(result.status, ReplayStatus.TERMINAL)
        self.assertEqual(result.terminal_run_ids, ("run-root",))

    # Replay Lab 只统计覆盖与离线结果，没有 score/promote 字段，发布仍必须回到固定 Eval/Evolution 链。
    def test_lab_reports_replay_evidence_without_promotion_semantics(self):
        world = ReplayWorld.from_sota_group(_group())
        report = ReplayLab([world]).evaluate(
            "candidate-short-route",
            lambda observation: observation.available_actions[0].key,
        )
        self.assertEqual(report.policy_id, "candidate-short-route")
        self.assertEqual(report.worlds, 1)
        self.assertEqual(report.terminal_worlds, 1)
        self.assertFalse(hasattr(report, "score"))
        self.assertFalse(hasattr(report, "eligible"))
        self.assertFalse(hasattr(report, "promote"))

    # 不同冻结环境的 comparison_key 不能混成一个 World，避免跨条件重放制造虚假分叉。
    def test_mixed_comparison_keys_are_rejected(self):
        group = _group()
        group[1] = {**group[1], "comparison_key": "different-world"}
        with self.assertRaisesRegex(ValueError, "comparison_key"):
            ReplayWorld.from_sota_group(group)


if __name__ == "__main__":
    unittest.main()
