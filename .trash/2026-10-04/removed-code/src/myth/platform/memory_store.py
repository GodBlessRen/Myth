    # _backfill_revision_snapshots：旧库第一次升级只为当前 revision 建快照；历史未知 revision 不伪造。
    def _backfill_revision_snapshots(self) -> None:
        rows = self.store.db.execute(
            "SELECT * FROM workspace_memories ORDER BY rowid"
        ).fetchall()
        with self.store.tx() as db:
            for row in rows:
                memory_id = str(row["memory_id"])
                exists = db.execute(
                    "SELECT 1 FROM workspace_memory_revisions WHERE memory_id=? AND revision=?",
                    (memory_id, int(row["revision"])),
                ).fetchone()
                if exists is not None:
                    continue
                if not self._evidence_rows(db, memory_id):
                    prepared = self._prepare_evidence(
                        db, None, default_ref=str(row["source_ref"])
                    )
                    self._replace_evidence(db, memory_id, prepared)
                self._snapshot_revision(db, memory_id)
