    # 旧工具表升级保留身份、结果与预算；无法补测旧耗时，因此新列必须为 NULL。
    def test_legacy_tool_schema_migration_does_not_fabricate_time(self):
        rid, did, _, result = self.tool()
        with self.runtime.store.tx() as db:
            db.execute("ALTER TABLE workspace_operations DROP COLUMN tool_wall_ms")
        repo = Workspace(self.runtime).repository
        self.assertIsNone(repo.operation(did)["tool_wall_ms"])
        self.assertEqual(repo.operation(did)["result"], result)
        report = ConversationWebService(self.root).session(self.sid)["statistics"]
        self.assertIsNone(report["tool_wall_ms"])
        self.assertEqual(report["tool_timing_samples"], 0)
        self.assertEqual(report["tool_calls"], 1)
