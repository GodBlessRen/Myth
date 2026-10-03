"""独立常驻 Durable Executor。
把长任务的 Driver 生命周期从浏览器/Web 进程中解耦：轮询持久 Run 与 Goal schedule，
竞争 Driver Lease，按原 Run 的 Execution Cursor 恢复；UNKNOWN 只观察不盲目重放。"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from .goal_scheduler import GoalScheduler
from .providers import create_provider
from .runtime import MythRuntime
from .workspace import Workspace


# EXECUTOR_SCHEMA：仅保存执行器自身租约/心跳/诊断；业务 Run 真相仍归 Runtime/Workspace。
EXECUTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_executor_state(
 executor_key TEXT PRIMARY KEY,
 owner_id TEXT NOT NULL,
 pid INTEGER,
 state TEXT NOT NULL,
 started_at REAL NOT NULL,
 heartbeat_at REAL NOT NULL,
 lease_until REAL NOT NULL,
 last_tick REAL,
 last_error TEXT,
 dispatched INTEGER NOT NULL DEFAULT 0);
"""

# EXECUTOR_KEY：单机 Runtime 的常驻执行器身份；Driver 仍按每个 Run 单独竞争 Lease。
EXECUTOR_KEY = "local"
# EXECUTOR_TTL_SECONDS：执行器全局租约秒数；只证明 worker 存活，不证明业务有进展。
EXECUTOR_TTL_SECONDS = 10.0
# EXECUTOR_POLL_SECONDS：默认扫描间隔秒数；真正进度来自 durable checkpoint/event。
EXECUTOR_POLL_SECONDS = 2.0
# NO_PROGRESS_SECONDS：UI 标记“疑似无进展”的观察阈值；不会据此自动重放外部效果。
NO_PROGRESS_SECONDS = 600.0


# 确保执行器状态表存在；该表不拥有 Goal/Run/Receipt 等业务事实。
def ensure_executor_schema(runtime) -> None:
    runtime.store.db.executescript(EXECUTOR_SCHEMA)


# 把 SQLite CURRENT_TIMESTAMP 解析成 UTC epoch；解析失败返回 None，不能伪造进度时间。
def _sqlite_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


# 读取常驻执行器租约快照；expired/stale 是派生状态，不代表任何业务 Run 成败。
def executor_snapshot(runtime) -> dict:
    ensure_executor_schema(runtime)
    row = runtime.store.db.execute(
        "SELECT * FROM runtime_executor_state WHERE executor_key=?",
        (EXECUTOR_KEY,),
    ).fetchone()
    if row is None:
        return {
            "state": "NOT_STARTED",
            "active": False,
            "owner_id": None,
            "pid": None,
            "heartbeat_age_seconds": None,
            "lease_remaining_seconds": 0,
            "last_tick": None,
            "last_error": None,
            "dispatched": 0,
        }
    value = dict(row)
    now = time.time()
    active = value["state"] == "RUNNING" and float(value["lease_until"]) > now
    return {
        **value,
        "state": value["state"] if active or value["state"] != "RUNNING" else "STALE",
        "active": active,
        "heartbeat_age_seconds": max(0.0, now - float(value["heartbeat_at"])),
        "lease_remaining_seconds": max(0.0, float(value["lease_until"]) - now),
    }


# 从真实 Execution Cursor 与 Driver Lease 派生无进展观察；心跳活着不等于任务进度。
def run_liveness(repository, run_id: str, threshold_seconds=NO_PROGRESS_SECONDS) -> dict:
    turn = repository.turn(run_id)
    cursor = repository.execution_cursor(run_id)
    lease = repository.driver_lease(run_id)
    updated = _sqlite_timestamp(cursor.get("updated_at"))
    now = time.time()
    age = None if updated is None else max(0.0, now - updated)
    live_driver = bool(lease and not lease.get("expired"))
    suspected = bool(
        turn["status"] == "RUNNING"
        and live_driver
        and age is not None
        and age >= float(threshold_seconds)
    )
    return {
        "last_progress_at": cursor.get("updated_at"),
        "seconds_since_progress": age,
        "threshold_seconds": float(threshold_seconds),
        "suspected_no_progress": suspected,
        "driver_heartbeat_live": live_driver,
        "phase": cursor.get("phase"),
        "checkpoint_step": cursor.get("checkpoint_step"),
    }


# 启动脱离 Web 生命周期的本机 worker；已有活租约时不重复启动。
def ensure_executor_process(root: str | Path) -> dict:
    root = Path(root).resolve()
    with MythRuntime(root) as runtime:
        current = executor_snapshot(runtime)
    if current["active"]:
        return {**current, "spawned": False}

    command = [
        sys.executable,
        "-m",
        "myth.cli",
        "--root",
        str(root),
        "worker",
    ]
    kwargs = {
        # 从可信安装目录启动模块，不能让用户 Runtime 目录的同名 myth 包抢先执行。
        "cwd": str(Path(__file__).resolve().parents[1]),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)

    deadline = time.monotonic() + 1.0
    latest = current
    while time.monotonic() < deadline:
        time.sleep(0.05)
        try:
            with MythRuntime(root) as runtime:
                latest = executor_snapshot(runtime)
            if latest["active"]:
                break
        except Exception:
            break
    return {**latest, "spawned": True}


# 常驻执行器：只负责发现/驱动已准入工作，权限、预算、UNKNOWN 与收据语义继续由原 Runtime 决定。
class DurableExecutor:
    # 保存 worker 身份、扫描节奏和本机线程集合；active 只是进程缓存，不能替代持久 Lease。
    def __init__(
        self,
        root: str | Path,
        *,
        poll_seconds: float = EXECUTOR_POLL_SECONDS,
        max_active: int = 4,
        provider_factory=None,
    ) -> None:
        # root：当前 Myth 根目录；持久状态位于其私有 .runtime。
        self.root = Path(root).resolve()
        # owner_id：本 worker 的全局租约身份；每个 Run 再追加 run_id 形成 Driver owner。
        self.owner_id = f"executor-{uuid.uuid4().hex}"
        # poll_seconds：扫描间隔秒数；限制后台数据库/连接检查频率。
        self.poll_seconds = max(0.2, float(poll_seconds))
        # max_active：本机同时驱动的 Run 上限；不改变每个 Run 自身预算。
        self.max_active = max(1, min(int(max_active), 32))
        # provider_factory：测试可注入供应商工厂；生产默认使用正式 adapter registry。
        self.provider_factory = provider_factory
        # active：本 worker 已启动的 Run 集；跨进程重复仍由 Driver Lease 阻止。
        self.active: set[str] = set()
        # lock：仅保护 active 线程集合；重连次数/截止时间归持久 Run 仓储。
        self.lock = threading.Lock()
        # wake_event：线程交还工作时唤醒扫描，避免默认两秒轮询拉长首次一秒重连。
        self.wake_event = threading.Event()
        # stop_event：显式停止 worker 主循环；不撤销已经签发的模型/工具效果。
        self.stop_event = threading.Event()

    # 原子竞争全局 worker 租约；过期 owner 可被新进程接管，旧进程后续心跳会失败。
    def claim(self) -> bool:
        now = time.time()
        with MythRuntime(self.root) as runtime:
            ensure_executor_schema(runtime)
            with runtime.store.tx() as db:
                row = db.execute(
                    "SELECT * FROM runtime_executor_state WHERE executor_key=?",
                    (EXECUTOR_KEY,),
                ).fetchone()
                if (
                    row
                    and row["owner_id"] != self.owner_id
                    and row["state"] == "RUNNING"
                    and float(row["lease_until"]) > now
                ):
                    return False
                db.execute(
                    "INSERT INTO runtime_executor_state("
                    "executor_key,owner_id,pid,state,started_at,heartbeat_at,lease_until,last_tick,last_error,dispatched"
                    ") VALUES(?,?,?,?,?,?,?,?,?,0) "
                    "ON CONFLICT(executor_key) DO UPDATE SET "
                    "owner_id=excluded.owner_id,pid=excluded.pid,state='RUNNING',"
                    "started_at=excluded.started_at,heartbeat_at=excluded.heartbeat_at,"
                    "lease_until=excluded.lease_until,last_tick=NULL,last_error=NULL,dispatched=0",
                    (
                        EXECUTOR_KEY,
                        self.owner_id,
                        os.getpid(),
                        "RUNNING",
                        now,
                        now,
                        now + EXECUTOR_TTL_SECONDS,
                        None,
                        None,
                    ),
                )
        return True

    # 仅当前 owner 续全局租约；失败意味着 worker 已失去继续派发资格。
    def heartbeat(self) -> bool:
        now = time.time()
        with MythRuntime(self.root) as runtime:
            ensure_executor_schema(runtime)
            with runtime.store.tx() as db:
                changed = db.execute(
                    "UPDATE runtime_executor_state SET heartbeat_at=?,lease_until=?,state='RUNNING' "
                    "WHERE executor_key=? AND owner_id=?",
                    (
                        now,
                        now + EXECUTOR_TTL_SECONDS,
                        EXECUTOR_KEY,
                        self.owner_id,
                    ),
                )
                return bool(changed.rowcount)

    # 保存本次扫描事实；错误只描述 worker 自身，不把 provider 暂不可用写成 Run 失败。
    def _record_tick(self, *, dispatched=0, error=None) -> None:
        now = time.time()
        with MythRuntime(self.root) as runtime:
            ensure_executor_schema(runtime)
            with runtime.store.tx() as db:
                db.execute(
                    "UPDATE runtime_executor_state SET last_tick=?,last_error=?,"
                    "dispatched=dispatched+? WHERE executor_key=? AND owner_id=?",
                    (
                        now,
                        None if error is None else str(error)[:1000],
                        int(dispatched),
                        EXECUTOR_KEY,
                        self.owner_id,
                    ),
                )

    # 释放全局 worker 租约；Run 级 Driver Lease 由各执行线程 finally 独立释放或自然过期。
    def release(self) -> None:
        now = time.time()
        try:
            with MythRuntime(self.root) as runtime:
                ensure_executor_schema(runtime)
                with runtime.store.tx() as db:
                    db.execute(
                        "UPDATE runtime_executor_state SET state='STOPPED',heartbeat_at=?,lease_until=? "
                        "WHERE executor_key=? AND owner_id=?",
                        (now, now, EXECUTOR_KEY, self.owner_id),
                    )
        except Exception:
            pass

    # 按固定 Turn 设置创建供应商；模型身份不能由 worker 临时替换。
    def _provider(self, settings):
        if self.provider_factory is not None:
            return self.provider_factory(settings)
        return create_provider(
            settings["provider"],
            ollama_base_url=settings.get("ollama_url"),
            runtime_root=str(self.root),
        )

    # 在持有 Driver 心跳的工作线程检查供应商；检查失败提交退避，不消费模型 Ticket。
    def _provider_ready(self, run_id: str, settings) -> bool:
        provider = self._provider(settings)
        # 生产探测有界；调用使用另一个 provider 的原始推理超时，工厂替身不被修改。
        if self.provider_factory is None and hasattr(provider, "timeout"):
            provider.timeout = min(provider.timeout, 5.0)
        try:
            status = provider.check()
            ready = bool(status.ready)
            if (ready and settings.get("provider") == "ollama" and settings.get("model")
                    and settings["model"] not in (status.details or {}).get("models", [])):
                ready = False
        except Exception:
            ready = False
        if not ready:
            with MythRuntime(self.root) as runtime:
                Workspace(runtime).repository.defer_network(run_id)
        return ready

    # 读取所有普通/计划 Turn 的可恢复候选；UNKNOWN/PAUSED/WAITING_USER 永远不自动派发。
    def dispatchable_runs(self, limit=32) -> list[str]:
        now = time.time()
        result = []
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            rows = runtime.store.db.execute(
                "SELECT t.run_id,t.status FROM workspace_turns t "
                "LEFT JOIN workspace_driver_leases d ON d.run_id=t.run_id "
                "LEFT JOIN workspace_network_retries n ON n.run_id=t.run_id "
                "WHERE t.status IN ('RUNNING','INTERRUPTED') "
                "AND (d.run_id IS NULL OR d.lease_until<=?) "
                "AND (n.run_id IS NULL OR n.retry_at<=?) "
                "ORDER BY t.rowid LIMIT ?",
                (now, now, int(limit)),
            ).fetchall()
            for row in rows:
                rid = row["run_id"]
                turn = workspace.repository.turn(rid)
                if turn["status"] == "RUNNING":
                    turn = workspace.repository.sweep_expired_driver(rid)
                if turn["status"] == "INTERRUPTED":
                    result.append(rid)
        return result

    # Run 级心跳线程只续当前 owner；无法续租时退出，业务线程仍须依真实 Ticket/Receipt 收束。
    def _run_heartbeat(self, run_id: str, owner_id: str, stop_event) -> None:
        while not stop_event.wait(2.0):
            try:
                with MythRuntime(self.root) as runtime:
                    if not Workspace(runtime).repository.heartbeat_driver(
                        run_id, owner_id, 8.0
                    ):
                        return
            except Exception:
                return

    # 竞争 Run Driver Lease 后在独立线程驱动原 Run；进程/线程异常只转 INTERRUPTED/UNKNOWN，不建替代 Run。
    def _spawn(self, run_id: str) -> bool:
        with self.lock:
            if run_id in self.active or len(self.active) >= self.max_active:
                return False
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            turn = workspace.repository.turn(run_id)
            if turn["status"] not in {"RUNNING", "INTERRUPTED"}:
                return False
            retry = workspace.repository.network_retry(run_id)
            if retry and retry["retry_at"] > time.time():
                return False
            if workspace.control.gate(run_id) is not None:
                return False
            owner_id = f"{self.owner_id}:{run_id}"
            if not workspace.repository.claim_driver(run_id, owner_id, 8.0):
                return False
        with self.lock:
            self.active.add(run_id)

        stop_heartbeat = threading.Event()

        # Run 工作线程按持久快照重建 provider/Workspace；finally 只释放自己的 owner，不触碰新一代 Driver。
        def work() -> None:
            heartbeat = threading.Thread(
                target=self._run_heartbeat,
                args=(run_id, owner_id, stop_heartbeat),
                name=f"executor-heartbeat-{run_id[:12]}",
                daemon=True,
            )
            heartbeat.start()
            try:
                with MythRuntime(self.root) as runtime:
                    workspace = Workspace(runtime)
                    turn = workspace.repository.turn(run_id)
                    # 探测与真实调用都在有心跳的 Run 线程中；慢网络不阻塞全局 worker 心跳/其他 Run。
                    pending_local = any(item.get("decision") and item["state"] != "DONE" for item in turn["activities"])
                    local_intent = (turn["current_step"] == 0
                        and (turn["snapshot"].get("intent_pick") or {}).get("route") == "deterministic")
                    if not pending_local and not local_intent and not self._provider_ready(run_id, turn["settings"]):
                        return
                    workspace.run(run_id, self._provider(turn["settings"]))
                    after = workspace.repository.turn(run_id)
                    if after["status"] == "RUNNING":
                        workspace.repository.interrupt(
                            run_id,
                            "Durable executor returned without a durable yield; checkpoint preserved.",
                        )
            except Exception as exc:
                try:
                    with MythRuntime(self.root) as runtime:
                        workspace = Workspace(runtime)
                        interrupted = workspace.repository.interrupt(
                            run_id, f"{type(exc).__name__}: {exc}"
                        )
                        goal_id = (
                            (interrupted.get("snapshot") or {})
                            .get("goal", {})
                            .get("goal_id")
                        )
                        if goal_id:
                            workspace.personal.checkpoint_run(
                                goal_id,
                                run_id,
                                status=interrupted["status"],
                                summary=f"{type(exc).__name__}: {exc}",
                                next_action=(
                                    "Reconcile the uncertain attempt before continuing."
                                    if interrupted["status"] == "UNKNOWN"
                                    else "Resume from the last durable checkpoint."
                                ),
                            )
                except Exception:
                    pass
            finally:
                stop_heartbeat.set()
                heartbeat.join(timeout=1.0)
                try:
                    with MythRuntime(self.root) as runtime:
                        Workspace(runtime).repository.release_driver(run_id, owner_id)
                except Exception:
                    pass
                with self.lock:
                    self.active.discard(run_id)
                self.wake_event.set()

        threading.Thread(
            target=work,
            name=f"executor-run-{run_id[:12]}",
            daemon=True,
        ).start()
        return True

    # 执行一次恢复/计划扫描；普通 Turn 与 Goal wakeup 共用同一 Driver/Lease/UNKNOWN 语义。
    def tick(self) -> int:
        if not self.heartbeat():
            raise RuntimeError("durable executor lease was lost")
        dispatched = 0
        errors = []
        try:
            for run_id in self.dispatchable_runs(self.max_active * 4):
                with self.lock:
                    if len(self.active) >= self.max_active:
                        break
                try:
                    if self._spawn(run_id):
                        dispatched += 1
                except Exception as exc:
                    errors.append(f"{run_id}: {type(exc).__name__}: {exc}")

            with MythRuntime(self.root) as runtime:
                due = GoalScheduler(Workspace(runtime)).due(limit=self.max_active * 4)
            for schedule in due:
                with self.lock:
                    if len(self.active) >= self.max_active:
                        break
                try:
                    provider = self._provider(schedule["settings"])
                    status = provider.check()
                    ready = bool(status.ready)
                    if (
                        ready
                        and schedule["settings"].get("provider") == "ollama"
                        and schedule["settings"].get("model")
                        not in (status.details or {}).get("models", [])
                    ):
                        ready = False
                    if not ready:
                        with MythRuntime(self.root) as runtime:
                            GoalScheduler(Workspace(runtime)).defer(
                                schedule["schedule_id"],
                                "scheduled provider is not connected",
                            )
                        continue
                    with MythRuntime(self.root) as runtime:
                        run_id = GoalScheduler(Workspace(runtime)).admit(
                            schedule["schedule_id"]
                        )
                    if run_id and self._spawn(run_id):
                        dispatched += 1
                except (ValueError, KeyError, PermissionError) as exc:
                    try:
                        with MythRuntime(self.root) as runtime:
                            GoalScheduler(Workspace(runtime)).defer(
                                schedule["schedule_id"], str(exc)
                            )
                    except Exception:
                        pass
                except Exception as exc:
                    errors.append(
                        f"{schedule.get('schedule_id')}: {type(exc).__name__}: {exc}"
                    )
        finally:
            self._record_tick(
                dispatched=dispatched,
                error="; ".join(errors[:3]) if errors else None,
            )
        return dispatched

    # 找最近可恢复连接截止时间；仅调整扫描节奏，不在轮询线程睡眠一整分钟或伪造任务进度。
    def _next_poll_delay(self):
        with MythRuntime(self.root) as runtime:
            GoalScheduler(Workspace(runtime))
            row = runtime.store.db.execute(
                "SELECT MIN(n.retry_at) FROM workspace_network_retries n "
                "JOIN workspace_turns t USING(run_id) LEFT JOIN workspace_driver_leases d USING(run_id) "
                "WHERE t.status='INTERRUPTED' AND (d.run_id IS NULL OR d.lease_until<=?)",
                (time.time(),)).fetchone()
            scheduled = runtime.store.db.execute(
                "SELECT MIN(retry_at) FROM goal_schedules WHERE enabled=1 AND due_at<=? AND retry_at>0",
                (time.time(),)).fetchone()
        deadlines = [value for value in (row[0], scheduled[0]) if value is not None]
        return min(self.poll_seconds, max(0.05, min(deadlines) - time.time())) if deadlines else self.poll_seconds

    # 常驻运行直到显式停止/进程结束；按持久重连时间唤醒，崩溃后原 Run/截止时间可由下一进程接管。
    def serve_forever(self) -> int:
        if not self.claim():
            return 0
        # 到期 Goal 的外部探测也可能慢于全局 TTL；独立续租不冒充业务进度，失去 owner 后停止未来扫描。
        def keep_alive():
            while not self.stop_event.wait(2.0):
                try:
                    if not self.heartbeat():
                        self.stop()
                        return
                except Exception:
                    self.stop()
                    return
        heartbeat = threading.Thread(target=keep_alive, name="executor-heartbeat", daemon=True)
        heartbeat.start()
        try:
            while not self.stop_event.is_set():
                self.wake_event.clear()
                try:
                    self.tick()
                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    self._record_tick(error=f"{type(exc).__name__}: {exc}")
                self.wake_event.wait(self._next_poll_delay())
        finally:
            self.stop()
            heartbeat.join(timeout=3.0)
            self.release()
        return 0

    # 有界等待当前本机 Run 线程退出；用于优雅关闭/测试清理，不改变任何 Run 的业务状态。
    def wait_for_idle(self, timeout=5.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            with self.lock:
                if not self.active:
                    return True
            time.sleep(0.02)
        with self.lock:
            return not self.active

    # 请求 worker 停止未来扫描；在途线程不被强杀，外部效果继续按真实收据处理。
    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
