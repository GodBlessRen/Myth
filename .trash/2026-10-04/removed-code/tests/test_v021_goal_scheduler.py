    # 回归断言：旧计划表升级保留时间/身份/设置，不能用清库代替迁移。
    def test_legacy_schedule_schema_is_upgraded_without_losing_timer(self):
        # The additive migration also accepts timer state created before the
        # request identity columns existed.
        schedule = self.schedule()
        with self.runtime.store.tx() as db:
            db.execute("DROP INDEX goal_schedule_requests")
            db.execute("ALTER TABLE goal_schedules DROP COLUMN request_id")
            db.execute("ALTER TABLE goal_schedules DROP COLUMN entry_digest")
        upgraded = GoalScheduler(self.workspace)
        self.assertEqual(
            upgraded.get(schedule["schedule_id"])["prompt"], schedule["prompt"]
        )
        self.assertIsNotNone(upgraded.admit(schedule["schedule_id"], self.now + 1))
