    # 回归断言：记忆类型、revision 和未来可见性明确；撤下不倒写历史。
    def test_memory_is_typed_revisioned_and_revocable(self):
        memory = MemoryCatalog()
        memory.put(
            MemoryRecord(
                "m1",
                MemoryKind.SEMANTIC,
                "user prefers concise Chinese",
                "conversation:1",
            )
        )
        self.assertEqual(memory.search("concise Chinese")[0].memory_id, "m1")
        memory.revoke("m1", revision=2)
        self.assertEqual(memory.search("concise Chinese"), [])


    # 回归断言：工作流验证节点依赖/无环，只提供策略原语而非自动执行。
    def test_workflow_is_a_strategy_primitive_not_a_mandatory_layer(self):
        spec = WorkflowSpec(
            "w1",
            (
                WorkflowStep("read", "project.read"),
                WorkflowStep("patch", "project.patch_exact", ("read",)),
            ),
        )
        validate_workflow(spec)
        self.assertEqual([step.step_id for step in ready_steps(spec, set())], ["read"])
        self.assertEqual(
            [step.step_id for step in ready_steps(spec, {"read"})], ["patch"]
        )
        with self.assertRaises(ValueError):
            validate_workflow(
                WorkflowSpec(
                    "bad",
                    (
                        WorkflowStep("a", "x", ("b",)),
                        WorkflowStep("b", "x", ("a",)),
                    ),
                )
            )
