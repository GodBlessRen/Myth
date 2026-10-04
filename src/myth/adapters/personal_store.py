"""长期 Goal、进度、关联、Trigger 与个人设置的 SQLite 状态所有者。
Goal 与初始进度一起创建；准入协作加入同一连接事务，迟到旧 Run 不覆盖新进度；Trigger 记录本身不执行工作。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..core import GoalState
from ..domain import canonical_json
from ..domains.personal import TriggerKind


# SCHEMA：本仓储拥有的当前表、索引与约束；由 Store 原子初始化，不叠加旧格式迁移。
# goals 是长期意图，不是 Memory；state 控制未来准入，不能撤销已发出效果。
# goal_work_state 的 revision 单调递增，last_run_id 决定谁能更新当前进度，waiting_for 保留人工/外部等待。
# goal_runs 是意图到 Core Run 的关联，不复制会话；triggers 只描述事件，实际机会归 GoalScheduler。
# personal_state 的 JSON 是显式非秘钥设置；不得放入 OAuth 凭据或由模型自动授予能力。
SCHEMA = r"""
CREATE TABLE IF NOT EXISTS goals(
    goal_id TEXT PRIMARY KEY NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goal_runs(
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    relation TEXT NOT NULL DEFAULT 'work',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(goal_id, run_id)
);

CREATE TABLE IF NOT EXISTS goal_triggers(
    trigger_id TEXT PRIMARY KEY NOT NULL,
    goal_id TEXT NOT NULL REFERENCES goals(goal_id),
    kind TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS personal_state(
    state_key TEXT PRIMARY KEY NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goal_work_state(
    goal_id TEXT PRIMARY KEY NOT NULL REFERENCES goals(goal_id),
    current_state TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT '',
    waiting_for TEXT NOT NULL DEFAULT '',
    progress_note TEXT NOT NULL DEFAULT '',
    last_run_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class SqlitePersonalState:
    """拥有长期个人聚合的适配器；创建、进度与关联写入在这里维护，不自行运行调度线程。"""

    # 复用 Runtime 连接建立个人状态表；负责 Goal/进度/关联写入，不拥有 Driver 或调度线程。
    def __init__(self, runtime) -> None:
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = runtime.store
        self.store.ensure_schema(SCHEMA)

    # 生成带类型前缀的新身份；重试去重使用已固定的 request/decision 身份，不靠新 UUID 判断已执行。
    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    # 校验显式长期意图并同时创建 Goal 和初始工作状态；任一写入失败全项回滚。
    def create_goal(self, title: str, description: str = "") -> dict[str, Any]:
        name = str(title or "").strip()
        detail = str(description or "").strip()
        if not name or len(name) > 200:
            raise ValueError("goal title must contain 1-200 characters")
        if len(detail.encode("utf-8")) > 16_000:
            raise ValueError("goal description exceeds 16000 UTF-8 bytes")
        goal_id = self._id("goal")
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO goals(goal_id,title,description,state) VALUES (?,?,?,?)",
                (goal_id, name, detail, GoalState.ACTIVE.value),
            )
            # Goal 身份与初始工作状态是一个创建决定；第二条写入失败时整项回滚。
            db.execute(
                "INSERT INTO goal_work_state(goal_id,current_state,next_action,progress_note) VALUES (?,?,?,?)",
                (
                    goal_id,
                    "READY",
                    "Start or continue the next admitted work item.",
                    "Goal created.",
                ),
            )
        return self.goal_view(goal_id)

    def _require_transaction(self, db) -> None:
        """校验外部协调器提供的是本实例同一连接的活动事务；不允许跨连接部分提交。"""
        if db is not self.store.db or not db.in_transaction:
            raise RuntimeError(
                "personal admission requires this store's active transaction"
            )

    def admission_snapshot(self, db, goal_id: str) -> dict[str, Any]:
        """在 Turn 准入事务内确认 ACTIVE Goal 并固定当前进度；个人表写入归此仓储所有。"""
        self._require_transaction(db)
        goal = self.goal(goal_id)
        if goal["state"] != GoalState.ACTIVE.value:
            raise ValueError("only an active Goal admits new work")
        return {**goal, "work": self.work_state(goal_id)}

    def bind_admitted_run(self, db, goal_id: str, run_id: str) -> None:
        """在调用方准入事务加入 Goal/Run 关联和 IN_PROGRESS checkpoint；本方法不另开或提交事务。"""
        self._require_transaction(db)
        db.execute(
            "INSERT INTO goal_runs(goal_id,run_id) VALUES(?,?)", (goal_id, run_id)
        )
        db.execute(
            "UPDATE goal_work_state SET current_state='IN_PROGRESS',last_run_id=?,revision=revision+1,"
            "progress_note='A new admitted Turn has started for this Goal.',"
            "next_action='Let the current Turn reach a durable checkpoint.',waiting_for='',"
            "updated_at=CURRENT_TIMESTAMP WHERE goal_id=?",
            (run_id, goal_id),
        )

    # 按身份读取长期 Goal；工作状态由单独的进度合同表示。
    def goal(self, goal_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM goals WHERE goal_id=?", (goal_id,)
        ).fetchone()
        if not row:
            raise KeyError(goal_id)
        return dict(row)

    # 列出当前可见长期 Goal；归档过滤只影响未来产品导航。
    def goals(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM goals"
        args: tuple[Any, ...] = ()
        if not include_archived:
            sql += " WHERE state<>?"
            args = (GoalState.ARCHIVED.value,)
        sql += " ORDER BY updated_at DESC,rowid DESC"
        return [dict(row) for row in self.store.db.execute(sql, args).fetchall()]

    # 显式改变 Goal 生命周期；只影响未来准入，不撤销已签发调用。
    def set_goal_state(self, goal_id: str, state: str | GoalState) -> dict[str, Any]:
        target = state if isinstance(state, GoalState) else GoalState(str(state))
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            updated = db.execute(
                "UPDATE goals SET state=?,updated_at=CURRENT_TIMESTAMP WHERE goal_id=?",
                (target.value, goal_id),
            ).rowcount
            if not updated:
                raise KeyError(goal_id)
        return self.goal(goal_id)

    # 将已存在 Core Run 关联到 Goal；独立 Exact 用例使用此入口，对话准入使用事务协作入口。
    def bind_run(
        self, goal_id: str, run_id: str, relation: str = "work"
    ) -> dict[str, Any]:
        self.goal(goal_id)
        run = self.store.get_run(run_id)
        value = str(relation or "work").strip()
        if not value or len(value) > 80:
            raise ValueError("goal/run relation must contain 1-80 characters")
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT OR IGNORE INTO goal_runs(goal_id,run_id,relation) VALUES (?,?,?)",
                (goal_id, run_id, value),
            )
        return {"goal_id": goal_id, "run_id": run["run_id"], "relation": value}

    # 投影已关联 Core Runs；会话状态由 Web 产品门面补充，个人仓储不依赖工作区会话表。
    def runs(self, goal_id: str) -> list[dict[str, Any]]:
        self.goal(goal_id)
        return [
            dict(row)
            for row in self.store.db.execute(
                "SELECT r.*,gr.relation,gr.created_at AS linked_at "
                "FROM goal_runs gr JOIN runs r ON r.run_id=gr.run_id "
                "WHERE gr.goal_id=? ORDER BY gr.created_at,r.rowid",
                (goal_id,),
            ).fetchall()
        ]

    # 当前格式的 Goal 与进度原子创建；缺行属于损坏，读取不得编造 READY 进度。
    def work_state(self, goal_id: str) -> dict[str, Any]:
        self.goal(goal_id)
        row = self.store.db.execute(
            "SELECT * FROM goal_work_state WHERE goal_id=?", (goal_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"goal work state missing: {goal_id}")
        return dict(row)

    # 合并 Goal 身份与当前 work state 为产品投影；历史 Turn 仍读取自己的冻结副本。
    def goal_view(self, goal_id: str) -> dict[str, Any]:
        goal = self.goal(goal_id)
        return {**goal, "work": self.work_state(goal_id)}

    # 为当前可见 Goal 生成工作状态列表；不是调度队列。
    def goal_views(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        return [
            self.goal_view(item["goal_id"])
            for item in self.goals(include_archived=include_archived)
        ]

    # 在写事务内读取并局部更新进度、递增 revision；expected_run_id 拒绝迟到旧 Run 覆盖新状态。
    def update_work_state(
        self,
        goal_id: str,
        *,
        current_state: str | None = None,
        next_action: str | None = None,
        waiting_for: str | None = None,
        progress_note: str | None = None,
        last_run_id: str | None = None,
        expected_run_id: str | None = None,
        _db=None,
    ) -> dict[str, Any]:
        # _db 由 Control 等协调入口显式传入；所有者仍是本仓储，提交点归调用者。
        with self.store.transaction_scope(_db) as db:
            current = self.work_state(goal_id)
            # 旧 Run 回答后可能迟到写进度；只允许仍为 last_run_id 的轮次更新，避免覆盖新准入 Turn。
            if expected_run_id is not None and current["last_run_id"] not in {
                None,
                expected_run_id,
            }:
                return self.goal_view(goal_id)
            values = {
                "current_state": (
                    current["current_state"]
                    if current_state is None
                    else str(current_state).strip()
                ),
                "next_action": (
                    current["next_action"]
                    if next_action is None
                    else str(next_action).strip()
                ),
                "waiting_for": (
                    current["waiting_for"]
                    if waiting_for is None
                    else str(waiting_for).strip()
                ),
                "progress_note": (
                    current["progress_note"]
                    if progress_note is None
                    else str(progress_note).strip()
                ),
                "last_run_id": (
                    current["last_run_id"] if last_run_id is None else last_run_id
                ),
            }
            for key in ("current_state", "next_action", "waiting_for", "progress_note"):
                if len(values[key].encode("utf-8")) > 4000:
                    raise ValueError(f"{key} exceeds 4000 UTF-8 bytes")
            db.execute(
                "UPDATE goal_work_state SET current_state=?,next_action=?,waiting_for=?,progress_note=?,"
                "last_run_id=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE goal_id=?",
                (
                    values["current_state"],
                    values["next_action"],
                    values["waiting_for"],
                    values["progress_note"],
                    values["last_run_id"],
                    goal_id,
                ),
            )
            db.execute(
                "UPDATE goals SET updated_at=CURRENT_TIMESTAMP WHERE goal_id=?",
                (goal_id,),
            )
        return self.goal_view(goal_id)

    # 把 Run 状态映射为 Goal 进度；校验 last_run_id 防止迟到旧轮次覆盖新准入状态。
    def checkpoint_run(
        self,
        goal_id: str,
        run_id: str,
        *,
        status: str,
        summary: str = "",
        next_action: str = "",
        waiting_for: str = "",
        _db=None,
    ) -> dict[str, Any]:
        mapping = {
            "COMPLETED": "READY",
            "WAITING_USER": "WAITING",
            "PAUSED": "PAUSED",
            "INTERRUPTED": "INTERRUPTED",
            "UNKNOWN": "RECONCILE",
            "FAILED": "BLOCKED",
            "BUDGET_EXHAUSTED": "BLOCKED",
            "CANCELLED": "PAUSED",
            "RUNNING": "IN_PROGRESS",
        }
        return self.update_work_state(
            goal_id,
            current_state=mapping.get(status, status),
            next_action=next_action
            or (
                "Continue from the latest durable checkpoint."
                if status in {"COMPLETED", "PAUSED", "CANCELLED", "INTERRUPTED"}
                else (
                    "Reconcile the latest run before continuing."
                    if status == "UNKNOWN"
                    else ""
                )
            ),
            waiting_for=waiting_for,
            progress_note=summary,
            last_run_id=run_id,
            expected_run_id=run_id,
            _db=_db,
        )

    # 保存有界显式 Trigger 参数；该记录不自动变成 executable schedule。
    def add_trigger(
        self,
        goal_id: str,
        kind: str | TriggerKind,
        spec: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.goal(goal_id)
        trigger_kind = kind if isinstance(kind, TriggerKind) else TriggerKind(str(kind))
        value = dict(spec or {})
        raw = canonical_json(value)
        if len(raw.encode("utf-8")) > 8_000:
            raise ValueError("trigger spec exceeds 8000 UTF-8 bytes")
        trigger_id = self._id("trigger")
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO goal_triggers(trigger_id,goal_id,kind,spec_json) VALUES (?,?,?,?)",
                (trigger_id, goal_id, trigger_kind.value, raw),
            )
        return self.trigger(trigger_id)

    # 读取并解析 Trigger JSON/布尔投影；不存在身份拒绝。
    def trigger(self, trigger_id: str) -> dict[str, Any]:
        row = self.store.db.execute(
            "SELECT * FROM goal_triggers WHERE trigger_id=?", (trigger_id,)
        ).fetchone()
        if not row:
            raise KeyError(trigger_id)
        value = dict(row)
        value["spec"] = json.loads(value.pop("spec_json"))
        value["enabled"] = bool(value["enabled"])
        return value

    # 读取某 Goal 的描述性 Trigger 列表；实际可运行计划属于 GoalScheduler。
    def triggers(self, goal_id: str) -> list[dict[str, Any]]:
        self.goal(goal_id)
        rows = self.store.db.execute(
            "SELECT trigger_id FROM goal_triggers WHERE goal_id=? ORDER BY rowid",
            (goal_id,),
        ).fetchall()
        return [self.trigger(row["trigger_id"]) for row in rows]

    # 保存有界明确个人设置；Preference 不从 Memory 猜测，秘钥不写入此表。
    def set_state(self, key: str, value: Any) -> None:
        state_key = str(key or "").strip()
        if not state_key or len(state_key) > 120:
            raise ValueError("personal state key must contain 1-120 characters")
        raw = canonical_json(value)
        if len(raw.encode("utf-8")) > 16_000:
            raise ValueError("personal state value exceeds 16000 UTF-8 bytes")
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO personal_state(state_key,value_json) VALUES (?,?) "
                "ON CONFLICT(state_key) DO UPDATE SET value_json=excluded.value_json,"
                "updated_at=CURRENT_TIMESTAMP",
                (state_key, raw),
            )

    # 读取个人设置投影；不返回认证秘钥或动态执行权限。
    def state(self) -> dict[str, Any]:
        return {
            row["state_key"]: json.loads(row["value_json"])
            for row in self.store.db.execute(
                "SELECT state_key,value_json FROM personal_state ORDER BY state_key"
            ).fetchall()
        }
