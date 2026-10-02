"""Composable architecture tests: stable core, orthogonal domains and pluggable strategies."""

import unittest

from myth.conversation import TOOL_CATALOG
from myth.domains.coordination import RouteTarget, StrategyState
from myth.platform import Maturity, MythComponents
from myth.platform.capabilities import CapabilityState
from myth.platform.context import ContextItem
from myth.platform.control import ControlCommand, ControlSnapshot
from myth.platform.evaluation import EvalReport, release_gate
from myth.platform.evolution import PolicyCandidate, PromotionDecision, decide_promotion
from myth.platform.memory import MemoryCatalog, MemoryKind, MemoryRecord
from myth.platform.workflow import WorkflowSpec, WorkflowStep, ready_steps, validate_workflow


class PlatformSkeletonTests(unittest.TestCase):
    def test_architecture_has_core_domains_strategies_and_adapters(self):
        components = MythComponents.default()
        snapshot = components.snapshot()

        self.assertEqual(snapshot["shape"], "core-domains-strategies-adapters")
        core_ids = {item["id"] for item in snapshot["core"]}
        domain_ids = {item["id"] for item in snapshot["domains"]}
        strategy_ids = {item["id"] for item in snapshot["strategies"]}
        adapter_ids = {item["id"] for item in snapshot["adapters"]}

        self.assertTrue({"goal","run","action","attempt","ticket","receipt","artifact","verification"} <= core_ids)
        self.assertTrue({"coordination","control","execution","capability","state","context","memory","personal","observability"} <= domain_ids)
        self.assertTrue({"direct","agent_loop","workflow","routing","multi_agent","managed_agent","personal_agent"} <= strategy_ids)
        self.assertTrue({"sqlite","local_files","ollama","openai","mcp","a2a"} <= adapter_ids)

        # There are no product-facing P0/P1000 phase labels anymore.
        for group in ("core","domains","strategies","adapters"):
            for item in snapshot[group]:
                self.assertNotIn("phase", item)

    def test_maturity_is_descriptive_not_execution_authority(self):
        components = MythComponents.default()
        snapshot = components.snapshot()
        allowed = {item.value for item in Maturity}
        for group in ("core","domains","adapters"):
            for item in snapshot[group]:
                self.assertIn(item["maturity"], allowed)

        self.assertIn("project.read", snapshot["executable_capabilities"])
        self.assertNotIn("shell.exec", snapshot["executable_capabilities"])
        self.assertEqual(components.capabilities.get("shell.exec").state, CapabilityState.PLANNED)

    def test_existing_conversation_tools_are_registered_executable_capabilities(self):
        components = MythComponents.default()
        executable = set(components.capabilities.executable_ids())
        self.assertTrue(set(TOOL_CATALOG) <= executable)

    def test_coordination_strategies_are_pluggable_not_layers(self):
        components = MythComponents.default()
        self.assertEqual(components.strategies.get("agent_loop").state, StrategyState.USABLE)
        self.assertEqual(components.strategies.get("multi_agent").state, StrategyState.EXISTS)
        self.assertEqual(RouteTarget.REMOTE_AGENT.value, "remote_agent")

    def test_control_uses_stop_vocabulary_and_legacy_abort_alias(self):
        components = MythComponents.default()
        state = ControlSnapshot()
        state = components.control.apply(state, ControlCommand.STEER, "focus on runtime")
        state = components.control.apply(state, ControlCommand.SWITCH_MODEL, "model-b")
        state = components.control.apply(state, ControlCommand.PAUSE)
        self.assertTrue(state.paused)
        state = components.control.apply(state, ControlCommand.RESUME)
        state = components.control.apply(state, ControlCommand.STOP)
        self.assertTrue(state.stopped)
        self.assertTrue(state.aborted)
        with self.assertRaises(ValueError):
            components.control.apply(state, ControlCommand.RESUME)

    def test_context_preserves_required_items_before_optional_depth(self):
        frame = MythComponents.default().context.compile(
            [
                ContextItem("history:old", "x" * 30, priority=0),
                ContextItem("goal", "GOAL", priority=100, required=True),
                ContextItem("recent", "RECENT", priority=10),
            ],
            max_bytes=12,
        )
        self.assertEqual([item.source_ref for item in frame.items], ["goal", "recent"])
        self.assertIn("history:old", frame.dropped)

    def test_memory_is_typed_revisioned_and_revocable(self):
        memory = MemoryCatalog()
        memory.put(MemoryRecord("m1", MemoryKind.SEMANTIC, "user prefers concise Chinese", "conversation:1"))
        self.assertEqual(memory.search("concise Chinese")[0].memory_id, "m1")
        memory.revoke("m1", revision=2)
        self.assertEqual(memory.search("concise Chinese"), [])

    def test_workflow_is_a_strategy_primitive_not_a_mandatory_layer(self):
        spec = WorkflowSpec("w1", (
            WorkflowStep("read", "project.read"),
            WorkflowStep("patch", "project.patch_exact", ("read",)),
        ))
        validate_workflow(spec)
        self.assertEqual([step.step_id for step in ready_steps(spec, set())], ["read"])
        self.assertEqual([step.step_id for step in ready_steps(spec, {"read"})], ["patch"])
        with self.assertRaises(ValueError):
            validate_workflow(WorkflowSpec("bad", (
                WorkflowStep("a", "x", ("b",)),
                WorkflowStep("b", "x", ("a",)),
            )))

    def test_evolution_never_auto_promotes_without_quality_gate(self):
        bad = EvalReport("suite", 9, 1, 0, 0)
        self.assertFalse(release_gate(bad)[0])
        candidate = PolicyCandidate("c1", "v1", "v2", ("prompt: tighter tool use",))
        self.assertEqual(decide_promotion(candidate, bad)[0], PromotionDecision.HOLD)
        good = EvalReport("suite", 20, 0, 0, 0)
        self.assertEqual(decide_promotion(candidate, good)[0], PromotionDecision.PROMOTE)


if __name__ == "__main__":
    unittest.main()
