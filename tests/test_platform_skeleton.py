"""Breadth-first skeleton tests: every future layer has a real minimum contract."""

import unittest

from myth.platform.capabilities import CapabilityState
from myth.platform.context import ContextItem
from myth.platform.control import ControlCommand, ControlSnapshot
from myth.platform.evaluation import EvalReport, release_gate
from myth.platform.evolution import PolicyCandidate, PromotionDecision, decide_promotion
from myth.platform.kernel import MythKernel
from myth.platform.memory import MemoryCatalog, MemoryKind, MemoryRecord
from myth.platform.workflow import WorkflowSpec, WorkflowStep, ready_steps, validate_workflow
from myth.conversation import TOOL_CATALOG


class PlatformSkeletonTests(unittest.TestCase):
    def test_kernel_exposes_broad_platform_without_advertising_planned_tools(self):
        kernel = MythKernel.default()
        snapshot = kernel.snapshot()
        ids = {layer["id"] for layer in snapshot["layers"]}
        self.assertTrue({
            "runtime","conversation","control","capabilities","context","memory",
            "retrieval","workflow","subagents","skills","mcp","observability",
            "evaluation","evolution","distributed",
        } <= ids)
        self.assertIn("project.read", snapshot["executable_capabilities"])
        self.assertNotIn("shell.exec", snapshot["executable_capabilities"])
        self.assertEqual(kernel.capabilities.get("shell.exec").state, CapabilityState.PLANNED)

    def test_existing_conversation_tools_are_registered_executable_capabilities(self):
        kernel = MythKernel.default()
        executable = set(kernel.capabilities.executable_ids())
        self.assertTrue(set(TOOL_CATALOG) <= executable)

    def test_control_plane_has_explicit_transitions(self):
        kernel = MythKernel.default()
        state = ControlSnapshot()
        state = kernel.control.apply(state, ControlCommand.STEER, "focus on runtime")
        state = kernel.control.apply(state, ControlCommand.SWITCH_MODEL, "model-b")
        state = kernel.control.apply(state, ControlCommand.PAUSE)
        self.assertTrue(state.paused)
        self.assertEqual(state.model, "model-b")
        state = kernel.control.apply(state, ControlCommand.RESUME)
        state = kernel.control.apply(state, ControlCommand.ABORT)
        self.assertTrue(state.aborted)
        with self.assertRaises(ValueError):
            kernel.control.apply(state, ControlCommand.RESUME)

    def test_context_preserves_required_items_before_optional_depth(self):
        frame = MythKernel.default().context.compile(
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

    def test_workflow_rejects_cycles_and_finds_ready_steps(self):
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
