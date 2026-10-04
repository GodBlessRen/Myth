    # 回归断言：旧快照兼容推断当前边界，不倒写历史记录。
    def test_legacy_snapshot_infers_current_turn_boundary_without_rewriting(self):
        turn = self.repo.turn(self.rid)
        snapshot = turn["snapshot"]
        snapshot.pop("turn_message_start")
        snapshot.pop("attached_document_ids")
        snapshot["messages"] = [
            {"role": "user", "content": f"old-{i}"} for i in range(12)
        ] + snapshot["messages"]
        stored = canonical_json(snapshot)
        with self.runtime.store.tx() as db:
            db.execute(
                "UPDATE workspace_turns SET snapshot_json=? WHERE run_id=?",
                (stored, self.rid),
            )
        turn = self.repo.turn(self.rid)
        self.assertEqual(turn["snapshot"]["turn_message_start"], 12)
        self.workspace.control.command(self.rid, "compact")
        provider = ChatProvider()
        self.workspace.run(self.rid, provider)
        self.assertIn("read then answer", str(provider.calls[0].serializable()))
        self.assertEqual(
            self.runtime.store.db.execute(
                "SELECT snapshot_json FROM workspace_turns WHERE run_id=?",
                (self.rid,),
            ).fetchone()[0],
            stored,
        )
