    # 旧定时表没有失败次数列时升级保留已保存的截止时间，不重新准入或清空旧计划。
    def test_legacy_schedule_retry_migration_preserves_deadline(self):
        scheduler = GoalScheduler(self.workspace)
        goal = self.workspace.personal.create_goal("Migration")
        sid = self.repo.create_session()["id"]
        entry = scheduler.create(goal["goal_id"], {"session_id": sid, "prompt": "Resume", "due_at": "2026-01-01T00:00:00Z"})
        scheduler.defer(entry["schedule_id"], "offline")
        before = scheduler.get(entry["schedule_id"])
        with self.runtime.store.tx() as db:
            db.execute("ALTER TABLE goal_schedules DROP COLUMN retry_failures")
        current = GoalScheduler(self.workspace).get(entry["schedule_id"])
        self.assertEqual(current["retry_at"], before["retry_at"])
        self.assertEqual(current["retry_failures"], 0)
        self.assertEqual(current["wakeups"], [])
