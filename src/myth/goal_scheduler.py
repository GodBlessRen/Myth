"""显式一次性/固定间隔 Goal 计划的本地调度适配器。
计划、工作机会、Turn、Goal 关联和 checkpoint 在同一数据库事务提交；供应商检查与 Driver 派发在事务外，UNKNOWN 不自动继续。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import time
import uuid

from .domain import canonical_json, digest_json, IdentityConflict


# SCHEMA：本仓储拥有的表、索引与约束；升级补齐旧字段，删除列须有迁移证据。
# due_at/retry_at/admitted_at 为 UTC epoch 秒，interval_seconds 为秒；禁用不删除已准入历史。
# sequence 标识同一计划的机会；(schedule_id,sequence) 唯一，不能用重新启用重发一次性机会。
# request_id/entry_digest 绑定明确计划意图；settings_json 在创建时固定，未来全局设置不倒写。
# wakeups.run_id 唯一关联已准入 Turn；数据库提交后才派发 Driver，UNKNOWN 仍由原 Run 核对。
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


# 严格解析带显式时区的 ISO 时间为 UTC epoch 秒，拒绝无时区/非有限/超范围值。
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


# 把 UTC epoch 秒转为带时区 ISO 投影；UI 可按浏览器时区显示。
def utc_iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


# 计划和工作机会的持久协调器；不持有模型执行权限，准入后交给正常 Driver。
class GoalScheduler:
    # 复用明确 Workspace 的三个状态所有者并建立计划表；构造不启动线程，admit 才提交工作机会。
    def __init__(self, workspace):
        # workspace：Conversation 产品装配对象；连接仓储、执行、Control 和长期状态。
        self.workspace = workspace
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = workspace.repository.store
        self.store.db.executescript(SCHEMA)
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(goal_schedules)")
            }
            for column in ("request_id", "entry_digest"):
                if column not in columns:
                    db.execute(f"ALTER TABLE goal_schedules ADD COLUMN {column} TEXT")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS goal_schedule_requests ON goal_schedules(request_id)"
            )

    # 固定用户计划、会话、模型设置与 request_id 摘要；同意图重试返回原计划，不同内容冲突。
    def create(self, goal_id, value):
        prompt = value.get("prompt")
        if (
            not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt.encode("utf-8")) > 16000
        ):
            raise ValueError("schedule prompt must contain 1-16000 UTF-8 bytes")
        due = utc_timestamp(value.get("due_at"))
        interval = value.get("interval_seconds")
        if interval is not None and (
            type(interval) is not int or not 60 <= interval <= 31536000
        ):
            raise ValueError("interval_seconds must be 60-31536000 or null")
        sid = value.get("session_id")
        self.workspace.personal.work_state(goal_id)
        request_id = value.get("request_id", uuid.uuid4().hex)
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 200:
            raise ValueError("request_id must contain 1-200 characters")
        settings = self.workspace.repository.settings()
        if not settings["model"]:
            raise ValueError("select a model before scheduling")
        schedule_id = f"schedule_{uuid.uuid4().hex}"
        identity = digest_json(
            {
                "goal_id": goal_id,
                "session_id": sid,
                "prompt": prompt.strip(),
                "due_at": due,
                "interval_seconds": interval,
                "settings": settings,
            }
        )
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            existing = db.execute(
                "SELECT schedule_id,entry_digest FROM goal_schedules WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if existing:
                if existing["entry_digest"] != identity:
                    raise IdentityConflict(
                        "schedule request_id reused with different intent or settings"
                    )
                return self.get(existing["schedule_id"])
            goal = self.workspace.personal.goal(goal_id)
            if goal["state"] != "ACTIVE":
                raise ValueError("only an active Goal can be scheduled")
            session = self.workspace.repository.session(sid)
            if session["archived"]:
                raise ValueError("restore the archived session before scheduling")
            db.execute(
                "INSERT INTO goal_schedules(schedule_id,goal_id,session_id,prompt,settings_json,due_at,interval_seconds,request_id,entry_digest) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    schedule_id,
                    goal_id,
                    sid,
                    prompt.strip(),
                    canonical_json(settings),
                    due,
                    interval,
                    request_id,
                    identity,
                ),
            )
        return self.get(schedule_id)

    # 读取计划固定设置及最近二十个 occurrence/Run 状态；wakeups 是历史事实，不重新执行。
    def get(self, schedule_id):
        row = self.store.db.execute(
            "SELECT * FROM goal_schedules WHERE schedule_id=?", (schedule_id,)
        ).fetchone()
        if row is None:
            raise KeyError(schedule_id)
        value = dict(row)
        value["settings"] = json.loads(value.pop("settings_json"))
        value["enabled"] = bool(value["enabled"])
        value["due_at"] = utc_iso(value["due_at"])
        value["wakeups"] = [
            dict(r)
            for r in self.store.db.execute(
                "SELECT w.*,t.status FROM goal_wakeups w JOIN workspace_turns t ON t.run_id=w.run_id "
                "WHERE w.schedule_id=? ORDER BY w.sequence DESC LIMIT 20",
                (schedule_id,),
            )
        ]
        return value

    # 读取全部或某 Goal 的计划投影；enabled 不代表供应商必然可用。
    def list(self, goal_id=None):
        if goal_id:
            self.workspace.personal.goal(goal_id)
        rows = self.store.db.execute(
            "SELECT schedule_id FROM goal_schedules "
            + ("WHERE goal_id=? " if goal_id else "")
            + "ORDER BY rowid DESC",
            (goal_id,) if goal_id else (),
        )
        return [self.get(r[0]) for r in rows]

    # 改变未来准入开关并清重试原因；已 fired 的一次性计划不可重置成另一次机会。
    def set_enabled(self, schedule_id, enabled):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            current = self.get(schedule_id)
            if enabled and current["interval_seconds"] is None and current["wakeups"]:
                raise ValueError(
                    "a fired one-shot timer cannot be rearmed; create another timer"
                )
            db.execute(
                "UPDATE goal_schedules SET enabled=?,retry_at=0,last_error=NULL WHERE schedule_id=?",
                (int(enabled), schedule_id),
            )
        return self.get(schedule_id)

    # 选取 enabled 且 due_at/retry_at 已到的有界计划；结果须在 admission 事务重新校验。
    def due(self, now=None, limit=10):
        now = time.time() if now is None else float(now)
        return [
            self.get(r[0])
            for r in self.store.db.execute(
                "SELECT schedule_id FROM goal_schedules WHERE enabled=1 AND due_at<=? AND retry_at<=? ORDER BY due_at,rowid LIMIT ?",
                (now, now, limit),
            )
        ]

    # 保留 due/sequence，记录原因并将检查延后三十秒；拒绝不消费工作机会。
    def defer(self, schedule_id, reason, now=None):
        now = time.time() if now is None else float(now)
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "UPDATE goal_schedules SET retry_at=?,last_error=? WHERE schedule_id=? AND enabled=1",
                (now + 30, str(reason)[:1000], schedule_id),
            )

    # 同事务提交 occurrence、Turn/预算、Goal 关联/进度并返回 Run 身份；未到期返回 None，忙/等待明确拒绝且不消费机会。
    def admit(self, schedule_id, now=None):
        now = time.time() if now is None else float(now)
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            row = db.execute(
                "SELECT * FROM goal_schedules WHERE schedule_id=?", (schedule_id,)
            ).fetchone()
            if row is None:
                raise KeyError(schedule_id)
            if not row["enabled"] or row["due_at"] > now or row["retry_at"] > now:
                return None
            # 读取/补齐旧 Goal 必须加入当前准入事务；不能在调度事务内再开一个初始化事务。
            goal = self.workspace.personal.admission_snapshot(db, row["goal_id"])
            work = goal["work"]
            if (
                goal["state"] != "ACTIVE"
                or work["current_state"] not in {"READY", "IN_PROGRESS"}
                or work["waiting_for"]
            ):
                raise ValueError(
                    "Goal is paused, blocked, or waiting; resolve its existing work first"
                )
            session = self.workspace.repository.session(row["session_id"])
            memory = self.workspace.memory.search(
                row["prompt"],
                limit=6,
                project_id=session.get("project_id"),
                session_id=row["session_id"],
            )
            turn = self.workspace.repository.create_turn(
                row["session_id"],
                row["prompt"],
                f"wake:{schedule_id}:{row['sequence']}",
                memory_records=memory,
                goal_id=row["goal_id"],
                _db=db,
                _settings=json.loads(row["settings_json"]),
            )
            rid = turn["run_id"]
            db.execute(
                "INSERT INTO goal_wakeups VALUES(?,?,?,?,?)",
                (schedule_id, row["sequence"], row["due_at"], rid, now),
            )
            interval = row["interval_seconds"]
            # 停机错过的多个间隔合并成一次机会；不积压成补跑风暴。
            next_due = (
                row["due_at"]
                + (math.floor((now - row["due_at"]) / interval) + 1) * interval
                if interval
                else row["due_at"]
            )
            db.execute(
                "UPDATE goal_schedules SET enabled=?,due_at=?,sequence=sequence+1,retry_at=0,last_error=NULL WHERE schedule_id=?",
                (int(interval is not None), next_due, schedule_id),
            )
            self.store._event(
                db,
                rid,
                "GoalWakeupAdmitted",
                {
                    "schedule_id": schedule_id,
                    "sequence": row["sequence"],
                    "due_at": utc_iso(row["due_at"]),
                    "goal_id": row["goal_id"],
                    "session_id": row["session_id"],
                },
            )
        return rid

    # 寻找没有活租约的已准入 RUNNING/INTERRUPTED 机会；UNKNOWN/等待/暂停不由调度器自动继续。
    def dispatchable_runs(self, limit=10):
        # UNKNOWN/暂停机会不由调度器自动继续；恢复须经过原 Run 的核对及 Control 安全点。
        return [
            r[0]
            for r in self.store.db.execute(
                "SELECT w.run_id FROM goal_wakeups w JOIN workspace_turns t ON t.run_id=w.run_id "
                "LEFT JOIN workspace_driver_leases d ON d.run_id=w.run_id "
                "WHERE t.status IN ('RUNNING','INTERRUPTED') AND (d.run_id IS NULL OR d.lease_until<=?) "
                "ORDER BY w.admitted_at LIMIT ?",
                (time.time(), limit),
            )
        ]
