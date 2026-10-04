    # 首次升级只回填一次旧 PASSED 记录；中断可幂等重试，成功后不在每次 Workspace 装配重复扫描。
    def backfill_once(self, limit: int = 200) -> int:
        marker = self.store.db.execute(
            "SELECT value FROM sota_route_meta WHERE key='backfill-v1'"
        ).fetchone()
        if marker is not None and marker["value"] == "done":
            return 0
        synced = self.sync_existing(limit=limit)
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO sota_route_meta(key,value) VALUES('backfill-v1','done') "
                "ON CONFLICT(key) DO UPDATE SET value='done',updated_at=CURRENT_TIMESTAMP"
            )
        return synced


    # 补齐历史 PASSED 记录；只读取已有事实，不重跑模型、工具或验收。
    def sync_existing(self, limit: int = 200) -> int:
        rows = self.store.db.execute(
            "SELECT run_id,subject_digest FROM delivery_acceptance "
            "WHERE state='PASSED' ORDER BY rowid DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        synced = 0
        for row in rows:
            try:
                self.observe(row["run_id"], subject_digest=row["subject_digest"])
                synced += 1
            except (KeyError, ValueError):
                continue
        return synced
