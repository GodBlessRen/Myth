"""Local, explicit timer/interval wake-ups. One occurrence is one admitted Turn.

The schedule, occurrence, Run, Goal link and checkpoint commit together. A
crash before dispatch leaves an admitted Run for the normal driver to recover.
No scheduler callback performs model or tool effects inside a DB transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import time
import uuid

from .domain import canonical_json, digest_json, IdentityConflict


SCHEMA = """
CREATE TABLE IF NOT EXISTS goal_schedules(
 schedule_id TEXT PRIMARY KEY,
 goal_id TEXT NOT NULL REFERENCES goals(goal_id),
 session_id TEXT NOT NULL REFERENCES workspace_sessions(id),
 prompt TEXT NOT NULL,settings_json TEXT NOT NULL,
 due_at REAL NOT NULL,interval_seconds INTEGER,
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
 sequence INTEGER NOT NULL DEFAULT 1,
 retry_at REAL NOT NULL DEFAULT 0,last_error TEXT,
 request_id TEXT,entry_digest TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS goal_schedules_due ON goal_schedules(enabled,due_at,retry_at);
CREATE TABLE IF NOT EXISTS goal_wakeups(
 schedule_id TEXT NOT NULL REFERENCES goal_schedules(schedule_id),
 sequence INTEGER NOT NULL,due_at REAL NOT NULL,
 run_id TEXT NOT NULL UNIQUE REFERENCES workspace_turns(run_id),
 admitted_at REAL NOT NULL,
 PRIMARY KEY(schedule_id,sequence));
"""


def utc_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("due_at must be an ISO timestamp with an explicit timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid due_at timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("due_at requires an explicit timezone")
    result = parsed.timestamp()
    if not math.isfinite(result) or not 0 <= result <= 253402300799:
        raise ValueError("due_at is outside supported range")
    return result


def utc_iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


class GoalScheduler:
    def __init__(self, workspace):
        self.workspace = workspace
        self.store = workspace.repository.store
        self.store.db.executescript(SCHEMA)
        with self.store.tx() as db:
            columns={row[1] for row in db.execute("PRAGMA table_info(goal_schedules)")}
            for column in ("request_id", "entry_digest"):
                if column not in columns:db.execute(f"ALTER TABLE goal_schedules ADD COLUMN {column} TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS goal_schedule_requests ON goal_schedules(request_id)")

    def create(self, goal_id, value):
        prompt = value.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > 16000:
            raise ValueError("schedule prompt must contain 1-16000 UTF-8 bytes")
        due = utc_timestamp(value.get("due_at"))
        interval = value.get("interval_seconds")
        if interval is not None and (type(interval) is not int or not 60 <= interval <= 31536000):
            raise ValueError("interval_seconds must be 60-31536000 or null")
        sid = value.get("session_id")
        self.workspace.personal.work_state(goal_id)
        request_id=value.get("request_id",uuid.uuid4().hex)
        if not isinstance(request_id,str) or not 1<=len(request_id)<=200:
            raise ValueError("request_id must contain 1-200 characters")
        settings = self.workspace.repository.settings()
        if not settings["model"]:
            raise ValueError("select a model before scheduling")
        schedule_id = f"schedule_{uuid.uuid4().hex}"
        identity=digest_json({"goal_id":goal_id,"session_id":sid,"prompt":prompt.strip(),
                              "due_at":due,"interval_seconds":interval,"settings":settings})
        with self.store.tx() as db:
            existing=db.execute("SELECT schedule_id,entry_digest FROM goal_schedules WHERE request_id=?",(request_id,)).fetchone()
            if existing:
                if existing["entry_digest"]!=identity:raise IdentityConflict("schedule request_id reused with different intent or settings")
                return self.get(existing["schedule_id"])
            goal = self.workspace.personal.goal(goal_id)
            if goal["state"] != "ACTIVE":
                raise ValueError("only an active Goal can be scheduled")
            session = self.workspace.repository.session(sid)
            if session["archived"]:
                raise ValueError("restore the archived session before scheduling")
            db.execute(
                "INSERT INTO goal_schedules(schedule_id,goal_id,session_id,prompt,settings_json,due_at,interval_seconds,request_id,entry_digest) VALUES(?,?,?,?,?,?,?,?,?)",
                (schedule_id, goal_id, sid, prompt.strip(), canonical_json(settings), due, interval,request_id,identity),
            )
        return self.get(schedule_id)

    def get(self, schedule_id):
        row = self.store.db.execute("SELECT * FROM goal_schedules WHERE schedule_id=?", (schedule_id,)).fetchone()
        if row is None:
            raise KeyError(schedule_id)
        value = dict(row)
        value["settings"] = json.loads(value.pop("settings_json"))
        value["enabled"] = bool(value["enabled"])
        value["due_at"] = utc_iso(value["due_at"])
        value["wakeups"] = [dict(r) for r in self.store.db.execute(
            "SELECT w.*,t.status FROM goal_wakeups w JOIN workspace_turns t ON t.run_id=w.run_id "
            "WHERE w.schedule_id=? ORDER BY w.sequence DESC LIMIT 20", (schedule_id,))]
        return value

    def list(self, goal_id=None):
        if goal_id:
            self.workspace.personal.goal(goal_id)
        rows = self.store.db.execute(
            "SELECT schedule_id FROM goal_schedules " + ("WHERE goal_id=? " if goal_id else "") + "ORDER BY rowid DESC",
            (goal_id,) if goal_id else (),
        )
        return [self.get(r[0]) for r in rows]

    def set_enabled(self, schedule_id, enabled):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        with self.store.tx() as db:
            current = self.get(schedule_id)
            if enabled and current["interval_seconds"] is None and current["wakeups"]:
                raise ValueError("a fired one-shot timer cannot be rearmed; create another timer")
            db.execute("UPDATE goal_schedules SET enabled=?,retry_at=0,last_error=NULL WHERE schedule_id=?",
                       (int(enabled), schedule_id))
        return self.get(schedule_id)

    def due(self, now=None, limit=10):
        now = time.time() if now is None else float(now)
        return [self.get(r[0]) for r in self.store.db.execute(
            "SELECT schedule_id FROM goal_schedules WHERE enabled=1 AND due_at<=? AND retry_at<=? ORDER BY due_at,rowid LIMIT ?",
            (now, now, limit))]

    def defer(self, schedule_id, reason, now=None):
        now = time.time() if now is None else float(now)
        with self.store.tx() as db:
            db.execute("UPDATE goal_schedules SET retry_at=?,last_error=? WHERE schedule_id=? AND enabled=1",
                       (now + 30, str(reason)[:1000], schedule_id))

    def admit(self, schedule_id, now=None):
        now = time.time() if now is None else float(now)
        with self.store.tx() as db:
            row = db.execute("SELECT * FROM goal_schedules WHERE schedule_id=?", (schedule_id,)).fetchone()
            if row is None:
                raise KeyError(schedule_id)
            if not row["enabled"] or row["due_at"] > now or row["retry_at"] > now:
                return None
            goal = self.workspace.personal.goal(row["goal_id"])
            work = self.workspace.personal.work_state(row["goal_id"])
            if goal["state"] != "ACTIVE" or work["current_state"] not in {"READY", "IN_PROGRESS"} or work["waiting_for"]:
                raise ValueError("Goal is paused, blocked, or waiting; resolve its existing work first")
            session = self.workspace.repository.session(row["session_id"])
            memory = self.workspace.memory.search(row["prompt"], limit=6,
                project_id=session.get("project_id"), session_id=row["session_id"])
            turn = self.workspace.repository.create_turn(
                row["session_id"], row["prompt"], f"wake:{schedule_id}:{row['sequence']}",
                memory_records=memory, goal_id=row["goal_id"],
                _db=db, _settings=json.loads(row["settings_json"]),
            )
            rid = turn["run_id"]
            db.execute("INSERT INTO goal_wakeups VALUES(?,?,?,?,?)",
                       (schedule_id, row["sequence"], row["due_at"], rid, now))
            interval = row["interval_seconds"]
            # Coalesce overdue intervals into one opportunity; no catch-up storm.
            next_due = row["due_at"] + (math.floor((now - row["due_at"]) / interval) + 1) * interval if interval else row["due_at"]
            db.execute("UPDATE goal_schedules SET enabled=?,due_at=?,sequence=sequence+1,retry_at=0,last_error=NULL WHERE schedule_id=?",
                       (int(interval is not None), next_due, schedule_id))
            self.store._event(db, rid, "GoalWakeupAdmitted", {
                "schedule_id": schedule_id, "sequence": row["sequence"], "due_at": utc_iso(row["due_at"]),
                "goal_id": row["goal_id"], "session_id": row["session_id"],
            })
        return rid

    def dispatchable_runs(self, limit=10):
        # An UNKNOWN or paused occurrence is never automatically continued.
        # The Run's ordinary recovery/Control gate owns resumed execution.
        return [r[0] for r in self.store.db.execute(
            "SELECT w.run_id FROM goal_wakeups w JOIN workspace_turns t ON t.run_id=w.run_id "
            "LEFT JOIN workspace_driver_leases d ON d.run_id=w.run_id "
            "WHERE t.status IN ('RUNNING','INTERRUPTED') AND (d.run_id IS NULL OR d.lease_until<=?) "
            "ORDER BY w.admitted_at LIMIT ?", (time.time(), limit))]
