"""对话 HTTP 产品门面与后台 Driver 生命周期。
每个操作打开独立 Runtime 连接；线程 active 集只管理本进程，持久 Lease/游标控制恢复。HTTP 生命周期不等于 Run 生命周期。"""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
import uuid

from .runtime import MythRuntime
from .workspace import Workspace
from .providers import create_provider
from .providers.ollama import OllamaProvider
from .platform.control import ControlCommand
from .strategies import RuleIntentPicker
from .goal_scheduler import GoalScheduler
from .durable_executor import executor_snapshot, run_liveness


# HTTP 产品与后台线程门面；线程内独立连接，active 为本机缓存，Lease 与游标为持久恢复事实。
class ConversationWebService:
    # 保存本机 active/线程锁、六秒 Lease 和两秒心跳/调度配置；请求和后台线程分别打开自己的 Runtime 连接。
    def __init__(self, root):
        # root：已明确选择的根目录；具体读写仍由对应受限适配器校验。
        self.root = root
        # active：本进程正在管理的 Run 身份集合；只防重复线程，跨进程资格由 Lease/物理锁决定。
        self.active = set()
        # lock：当前互斥资源句柄；按上下文/finally 释放，不能表示业务成功。
        self.lock = threading.Lock()
        # driver_id：当前本机 Driver 的 owner 身份；释放/续期须匹配所有者。
        self.driver_id = f"web-{uuid.uuid4().hex}"
        # driver_ttl：持久 Driver 租约存活时长，单位秒；不代替物理互斥锁。
        self.driver_ttl = 6.0
        # heartbeat_interval：后台续租间隔，单位秒；应小于租约 TTL。
        self.heartbeat_interval = 2.0
        # scheduler_stop：本进程调度线程停止事件；停止检查不会撤销已签发效果。
        self.scheduler_stop = threading.Event()
        # scheduler_thread：本进程到期检查线程句柄；不是持久计划或工作机会。
        self.scheduler_thread = None
        # scheduler_state：本进程调度状态投影；真实机会和拒绝原因另存数据库。
        self.scheduler_state = {"running": False, "last_tick": None, "last_error": None}

    # 逐次读取待恢复/到期机会，在事务外检查供应商，再准入并交正常 Driver；本机调度并发有上限。
    def scheduler_tick(self):
        with MythRuntime(self.root) as runtime:
            scheduler = GoalScheduler(Workspace(runtime))
            pending = scheduler.dispatchable_runs()
            due = scheduler.due()
        for rid in pending:
            with self.lock:
                if len(self.active) >= 4:
                    break
            self._spawn(rid)
        for schedule in due:
            with self.lock:
                if len(self.active) >= 4:
                    break
            try:
                check = self.connection(schedule["settings"])
                if not check["ready"]:
                    raise ValueError("scheduled provider is not connected")
                if schedule["settings"]["provider"] == "ollama" and schedule[
                    "settings"
                ]["model"] not in check["details"].get("models", []):
                    raise ValueError("scheduled model is not installed")
                with MythRuntime(self.root) as runtime:
                    rid = GoalScheduler(Workspace(runtime)).admit(
                        schedule["schedule_id"]
                    )
                if rid:
                    self._spawn(rid)
            except (ValueError, KeyError, PermissionError) as exc:
                with MythRuntime(self.root) as runtime:
                    GoalScheduler(Workspace(runtime)).defer(
                        schedule["schedule_id"], str(exc)
                    )
        self.scheduler_state = {
            "running": bool(self.scheduler_thread and self.scheduler_thread.is_alive()),
            "last_tick": time.time(),
            "last_error": None,
        }

    # 启动每两秒检查的 daemon 线程；异常保存可见原因，工作用独立 Runtime 连接。
    def start_scheduler(self):
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            return
        self.scheduler_stop.clear()

        # 后台生命周期函数；独立连接按固定 Turn 设置运行，同步可见错误并在 finally 释放自己的租约/active。
        def work():
            while not self.scheduler_stop.is_set():
                try:
                    self.scheduler_tick()
                except Exception as exc:
                    self.scheduler_state = {
                        "running": True,
                        "last_tick": time.time(),
                        "last_error": str(exc)[:1000],
                    }
                self.scheduler_stop.wait(2.0)
            self.scheduler_state = {**self.scheduler_state, "running": False}

        self.scheduler_thread = threading.Thread(
            target=work, name="myth-goal-wakeup", daemon=True
        )
        self.scheduler_thread.start()

    # 通知线程停止检查并有限等待；不撤销已签发模型/工具调用。
    def stop_scheduler(self):
        self.scheduler_stop.set()
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=6)

    # 为一次仓储操作打开并关闭独立 Runtime 连接；业务事务规则仍由仓储所有。
    def _use(self, method, *args):
        with MythRuntime(self.root) as runtime:
            return getattr(Workspace(runtime).repository, method)(*args)

    # 组合组件地图与明确活动策略/历史投影；不自动修改活动策略。
    def platform(self):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            value = workspace.components.snapshot()
            value["active_policy"] = workspace.evolution.active(
                "information_resolution"
            )
            value["policy_history"] = workspace.evolution.history(
                "information_resolution", 10
            )
            return value

    # 按显式 query/kind 返回可见记忆；文本仅作为上下文，不授予能力。
    def memories(self, query="", kind=None, limit=50):
        with MythRuntime(self.root) as runtime:
            memory = Workspace(runtime).memory
            if query:
                kinds = [kind] if kind else None
                return memory.search(query, kinds=kinds, limit=min(int(limit), 20))
            values = memory.list(active_only=True, limit=min(int(limit), 100))
            return [item for item in values if not kind or item["kind"] == kind]

    # 读取独立执行器心跳/租约投影；只反映 worker 生命，不把它冒充业务进度。
    def executor(self):
        with MythRuntime(self.root) as runtime:
            return executor_snapshot(runtime)

    # 装配页面初始项目/会话/设置/Goal/恢复和调度投影；刷新不驱动未授权效果。
    def bootstrap(self):
        return {
            "projects": self._use("projects"),
            "sessions": self._use("sessions"),
            "settings": self._use("settings"),
            "documents": self._use("documents"),
            "platform": self.platform(),
            "memory_count": len(self.memories(limit=100)),
            "goals": self.goals(),
            "goal_count": len(self.goals()),
            "recoverable_runs": self.recoverable_runs(),
            "executor": self.executor(),
            "scheduler": dict(self.scheduler_state),
        }

    # 按该 Turn/计划固定设置装配供应商；认证秘钥由独立适配器提供。
    def provider(self, settings):
        return create_provider(
            settings["provider"],
            ollama_base_url=settings.get("ollama_url"),
            runtime_root=str(self.root),
        )

    # 在数据库事务外检查固定供应商/model 可用性；ready 不代替真实调用结果。
    def connection(self, payload=None):
        settings = payload or self._use("settings")
        provider = (
            OllamaProvider(
                settings.get("ollama_url", "http://127.0.0.1:11434"), timeout=5
            )
            if settings.get("provider", "ollama") == "ollama"
            else self.provider(settings)
        )
        status = provider.check()
        return {
            "ready": status.ready,
            "provider": status.provider_id,
            "details": status.details or {},
        }

    # 从持久模型收据聚合输入/输出/缓存及调用量；无缓存报告保留 N/A，不伪造命中率。
    @staticmethod
    def _model_usage_summary(invocations):
        input_tokens = 0
        output_tokens = 0
        cached_input_tokens = 0
        provider_wall_ms = 0
        provider_wall_reported = False
        cache_reported = False
        for item in invocations:
            usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
            input_tokens += max(0, int(usage.get("input_tokens") or 0))
            output_tokens += max(0, int(usage.get("output_tokens") or 0))
            if "cached_input_tokens" in usage:
                cache_reported = True
                cached_input_tokens += max(
                    0, int(usage.get("cached_input_tokens") or 0)
                )
            if "provider_wall_ms" in usage:
                provider_wall_reported = True
                provider_wall_ms += max(0, int(usage.get("provider_wall_ms") or 0))
        hit_rate = (
            cached_input_tokens / input_tokens
            if cache_reported and input_tokens > 0
            else None
        )
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens if cache_reported else None,
            "cache_hit_rate": hit_rate,
            "cache_metrics_available": cache_reported,
            "provider_wall_ms": provider_wall_ms if provider_wall_reported else None,
            "provider_wall_available": provider_wall_reported,
            "model_calls": len(invocations),
        }

    # 读取并核对过期 Driver 的未终结 Run，返回游标与租约；UNKNOWN 仍需人工/收据核对。
    def recoverable_runs(self):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            rows = runtime.store.db.execute(
                "SELECT run_id,session_id,status,current_step,max_steps,error,created_at "
                "FROM workspace_turns WHERE status IN ('RUNNING','INTERRUPTED','UNKNOWN','PAUSED','WAITING_USER') "
                "ORDER BY rowid DESC LIMIT 50"
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                if item["status"] == "RUNNING":
                    lease = workspace.repository.driver_lease(item["run_id"])
                    if lease is None or lease["expired"]:
                        workspace.repository.sweep_expired_driver(item["run_id"])
                        item = dict(
                            runtime.store.db.execute(
                                "SELECT run_id,session_id,status,current_step,max_steps,error,created_at "
                                "FROM workspace_turns WHERE run_id=?",
                                (item["run_id"],),
                            ).fetchone()
                        )
                cursor = workspace.repository.execution_cursor(item["run_id"])
                item["execution_cursor"] = cursor
                item["driver_lease"] = workspace.repository.driver_lease(item["run_id"])
                result.append(item)
            return result

    # 每次用独立连接续当前 owner 租约；失败停止续期，不抢占其他 owner。
    def _heartbeat_loop(self, rid, owner_id, stop_event):
        while not stop_event.wait(self.heartbeat_interval):
            try:
                with MythRuntime(self.root) as runtime:
                    workspace = Workspace(runtime)
                    if not workspace.repository.heartbeat_driver(
                        rid, owner_id, self.driver_ttl
                    ):
                        return
            except Exception:
                return

    # 将 SQLite UTC 时间转成 epoch 秒；失败返回空值，展示层不得据无效时间伪造耗时。
    @staticmethod
    def _timestamp_epoch(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace(" ", "T"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    # 为每条 Assistant 回复投影从最近一条同 Run 用户消息到回复落库的 wall-clock 用时；不伪装成纯模型推理时间。
    def _reply_timings(self, messages):
        pending_user = {}
        now = time.time()
        for message in messages:
            stamp = self._timestamp_epoch(message.get("created_at"))
            rid = message.get("run_id")
            if message.get("role") == "user" and rid and stamp is not None:
                pending_user[rid] = stamp
                continue
            if message.get("role") != "assistant" or not rid or stamp is None:
                continue
            started = pending_user.pop(rid, None)
            if started is None:
                continue
            metadata = dict(message.get("metadata") or {})
            metadata["reply_elapsed_seconds"] = max(0, int(stamp - started))
            metadata["reply_started_at"] = started
            metadata["reply_finished_at"] = stamp
            message["metadata"] = metadata
        return {
            rid: {
                "started_at": started,
                "elapsed_seconds": max(0, int(now - started)),
            }
            for rid, started in pending_user.items()
        }

    # 读取会话及其消息/轮次投影；持久状态仍由仓储操作修改。
    def session(self, sid):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            value = workspace.repository.session(sid)
            reply_timings = self._reply_timings(value["messages"])
            with self.lock:
                active = set(self.active)
            for turn in value["turns"]:
                lease = workspace.repository.driver_lease(turn["run_id"])
                if turn["status"] == "RUNNING" and (lease is None or lease["expired"]):
                    swept = workspace.repository.sweep_expired_driver(turn["run_id"])
                    turn.clear()
                    turn.update(swept)
                    lease = workspace.repository.driver_lease(turn["run_id"])
                # driver_active 来自持久 Lease，而不是当前 Web 进程的线程缓存；独立 Durable Executor 也应显示为 active。
                turn["driver_active"] = bool(lease and not lease["expired"])
                turn["driver_local"] = bool(turn["run_id"] in active)
                turn["driver_lease"] = lease
                turn["reply_timing"] = reply_timings.get(turn["run_id"])
                turn["execution_cursor"] = workspace.repository.execution_cursor(
                    turn["run_id"]
                )
                turn["liveness"] = run_liveness(
                    workspace.repository, turn["run_id"]
                )
                turn["control"] = workspace.control.view(turn["run_id"])
                turn["operations"] = workspace.repository.operations(turn["run_id"])
                turn["events"] = workspace.repository.events(turn["run_id"])
                model_state = workspace.repository.decisions.status(turn["run_id"])
                turn["model_usage"] = self._model_usage_summary(
                    model_state["model_invocations"]
                )
                goal_id = (turn.get("snapshot") or {}).get("goal", {}).get("goal_id")
                turn["goal_current"] = (
                    workspace.personal.goal_view(goal_id) if goal_id else None
                )
            value["artifacts"] = workspace.repository.artifacts(sid)
            return value

    # 先在本机 active 集占位，再竞争持久 Driver Lease 并启动线程；失败释放占位，线程退出清理自己的 owner。
    def _spawn(self, rid):
        owner_id = f"{self.driver_id}:{rid}"
        with self.lock:
            if rid in self.active:
                return
            self.active.add(rid)
        try:
            with MythRuntime(self.root) as runtime:
                claimed = Workspace(runtime).repository.claim_driver(
                    rid, owner_id, self.driver_ttl
                )
            if not claimed:
                with self.lock:
                    self.active.discard(rid)
                return
        except BaseException:
            with self.lock:
                self.active.discard(rid)
            raise

        stop_heartbeat = threading.Event()

        # 后台生命周期函数；独立连接按固定 Turn 设置运行，同步可见错误并在 finally 释放自己的租约/active。
        def work():
            heartbeat = threading.Thread(
                target=self._heartbeat_loop,
                args=(rid, owner_id, stop_heartbeat),
                name=f"heartbeat-{rid[:12]}",
                daemon=True,
            )
            heartbeat.start()
            try:
                with MythRuntime(self.root) as runtime:
                    workspace = Workspace(runtime)
                    turn = workspace.repository.turn(rid)
                    settings = turn["settings"]
                    workspace.run(rid, self.provider(settings))
            except Exception as exc:
                with MythRuntime(self.root) as runtime:
                    workspace = Workspace(runtime)
                    interrupted = workspace.repository.interrupt(
                        rid,
                        f"{type(exc).__name__}: {exc}",
                    )
                    goal_id = (
                        (interrupted.get("snapshot") or {})
                        .get("goal", {})
                        .get("goal_id")
                    )
                    if goal_id:
                        workspace.personal.checkpoint_run(
                            goal_id,
                            rid,
                            status=interrupted["status"],
                            summary=f"{type(exc).__name__}: {exc}",
                            next_action=(
                                "Reconcile the uncertain attempt before continuing."
                                if interrupted["status"] == "UNKNOWN"
                                else "Resume from the last durable checkpoint."
                            ),
                        )
            finally:
                stop_heartbeat.set()
                heartbeat.join(timeout=1)
                try:
                    with MythRuntime(self.root) as runtime:
                        Workspace(runtime).repository.release_driver(rid, owner_id)
                except Exception:
                    pass
                with self.lock:
                    self.active.discard(rid)

        threading.Thread(target=work, name=f"chat-{rid[:12]}", daemon=True).start()

    # 校验明确用户消息与固定设置，读取作用域 Memory 后调用原子 Turn admission；提交后才启动 Driver。
    def send(self, sid, value):
        settings = self._use("settings")
        text = value.get("text")
        goal_id = value.get("goal_id") or None
        pick = RuleIntentPicker().pick(str(text or ""), {})
        if pick.route.value != "deterministic":
            check = self.connection(settings)
            if not check["ready"]:
                raise ValueError("模型服务未连接，请在设置中检查模型连接。")
            if settings["provider"] == "ollama" and settings["model"] not in check[
                "details"
            ].get("models", []):
                raise ValueError("所选模型未安装，请选择已有 Ollama 模型。")

        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            # 在 Run/Turn 创建前核对长期 Goal；入口身份绑定 goal_id，同请求不能悄悄换到另一个意图。
            goal_context = None
            if goal_id:
                goal_context = workspace.personal.goal_view(goal_id)
            session = workspace.repository.session(sid)
            memory = workspace.memory.search(
                str(text or ""),
                limit=6,
                project_id=session.get("project_id"),
                session_id=sid,
            )
            turn = workspace.repository.create_turn(
                sid,
                text,
                value.get("request_id"),
                value.get("document_ids"),
                memory_records=memory,
                goal_id=goal_id,
                goal_context=goal_context,
            )
            workspace.control.ensure(turn["run_id"], turn["settings"])
        if turn["status"] == "RUNNING":
            self._spawn(turn["run_id"])
        return {"run_id": turn["run_id"], "session_id": sid}

    # 提交明确控制命令并按安全点选择后续 Driver；不物理撤销在途调用。
    def control(self, rid, action, value):
        if action == "answer":
            self._use("answer", rid, value.get("text"), value.get("question_id"))
            self._spawn(rid)
            return {"run_id": rid, "status": "RUNNING"}

        if action == "continue":
            turn = self._use("turn", rid)
            if turn["status"] not in {"RUNNING", "INTERRUPTED", "UNKNOWN"}:
                raise ValueError("turn cannot continue")
            self._spawn(rid)
            return {"run_id": rid, "status": turn["status"]}

        mapping = {
            "pause": ControlCommand.PAUSE,
            "resume": ControlCommand.RESUME,
            "stop": ControlCommand.STOP,
            "abort": ControlCommand.STOP,
            "cancel": ControlCommand.STOP,
            "steer": ControlCommand.STEER,
            "switch_model": ControlCommand.SWITCH_MODEL,
            "switch_thinking": ControlCommand.SWITCH_THINKING,
            "compact": ControlCommand.COMPACT,
        }
        if action not in mapping:
            raise ValueError("unsupported control")

        if action == "steer":
            payload = value.get("text")
        elif action == "switch_model":
            payload = value.get("model")
        elif action == "switch_thinking":
            payload = value.get("thinking")
        else:
            payload = None

        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            projection = workspace.control.command(rid, mapping[action], payload)
            turn = workspace.repository.turn(rid)

        goal_id = (turn.get("snapshot") or {}).get("goal", {}).get("goal_id")
        if goal_id and action in {"pause", "stop", "resume"}:
            with MythRuntime(self.root) as runtime:
                personal = Workspace(runtime).personal
                status = {"pause": "PAUSED", "stop": "CANCELLED", "resume": "RUNNING"}[
                    action
                ]
                personal.checkpoint_run(
                    goal_id,
                    rid,
                    status=status,
                    summary=f"Control action applied: {action}.",
                    next_action=(
                        "Resume this Goal when ready."
                        if action == "pause"
                        else (
                            "Continue the Goal in a new admitted Turn."
                            if action == "stop"
                            else "Let the resumed Turn reach a durable checkpoint."
                        )
                    ),
                )

        if action == "resume":
            self._spawn(rid)
        elif (
            action in {"steer", "switch_model", "switch_thinking", "compact"}
            and turn["status"] == "RUNNING"
        ):
            self._spawn(rid)

        return {"run_id": rid, "status": turn["status"], "control": projection}

    # 保存用户明确要求的有来源记忆；不从文本推断权限或秘钥。
    def remember(self, value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).memory.remember(
                kind=value.get("kind", "semantic"),
                text=value.get("text", ""),
                source_ref=value.get("source_ref") or "user",
            )

    # 列出当前可见长期 Goal；归档过滤只影响未来产品导航。
    def goals(self, include_archived=False):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.goal_views(
                include_archived=include_archived
            )

    # 调用个人状态所有者原子创建长期意图和初始进度；门面不复制写表逻辑。
    def create_goal(self, value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.create_goal(
                value.get("title", ""),
                value.get("description", ""),
            )

    # 返回描述性 Trigger；不会把旧 cron/webhook 记录当成当前可执行计划。
    def goal_triggers(self, goal_id):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.triggers(goal_id)

    # 在产品门面补充已关联 Core Run 的会话/Turn 状态；个人仓储保持独立于会话表。
    def goal_runs(self, goal_id):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            runs = workspace.personal.runs(goal_id)
            for run in runs:
                row = runtime.store.db.execute(
                    "SELECT session_id,status FROM workspace_turns WHERE run_id=?",
                    (run["run_id"],),
                ).fetchone()
                if row:
                    run.update(
                        {"session_id": row["session_id"], "turn_status": row["status"]}
                    )
            return runs

    # 读取合并 Goal/进度的产品投影；不是新的准入决定。
    def goal(self, goal_id):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.goal_view(goal_id)

    # 经持久调度适配器返回计划列表；历史 occurrence 不重新执行。
    def schedules(self, goal_id=None):
        with MythRuntime(self.root) as runtime:
            return GoalScheduler(Workspace(runtime)).list(goal_id)

    # 把明确用户时间/Prompt/会话/请求身份保存为固定计划；未来机会仍经正常 admission。
    def schedule_goal(self, goal_id, value):
        with MythRuntime(self.root) as runtime:
            return GoalScheduler(Workspace(runtime)).create(goal_id, value)

    # 修改未来计划开关；当前已运行工作由 Control 管理。
    def enable_schedule(self, schedule_id, value):
        with MythRuntime(self.root) as runtime:
            return GoalScheduler(Workspace(runtime)).set_enabled(
                schedule_id, value.get("enabled")
            )

    # 显式改变长期意图状态；暂停阻止未来准入，已开始的 Run 不被撤销。
    def set_goal_state(self, goal_id, value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.set_goal_state(
                goal_id, value.get("state")
            )

    # 只把允许进度字段交个人仓储校验并保存；不修改历史 Turn 快照。
    def update_goal_work(self, goal_id, value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.update_work_state(
                goal_id,
                current_state=value.get("current_state"),
                next_action=value.get("next_action"),
                waiting_for=value.get("waiting_for"),
                progress_note=value.get("progress_note"),
            )

    # 保存描述性触发参数；具体执行能力仍由对应调度适配器决定。
    def add_goal_trigger(self, goal_id, value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.add_trigger(
                goal_id,
                value.get("kind", "user"),
                value.get("spec") or {},
            )

    # 读取非秘钥个人设置；认证凭据不属于这个聚合。
    def personal_state(self):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.state()

    # 保存明确个人配置，限制字段/大小；模型文本不能凭此扩权。
    def set_personal_state(self, value):
        key = value.get("key", "")
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            workspace.personal.set_state(key, value.get("value"))
            return {"key": key, "value": workspace.personal.state().get(key)}

    # 显式撤下未来检索记忆；保留历史快照和来源证据。
    def revoke_memory(self, memory_id):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).memory.revoke(memory_id)

    # 使用实际受限项目执行器列目录；不把 UI 路径参数直接交给任意文件读取。
    def project_files(self, pid, path="."):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            return workspace.execution.list_project(
                {"snapshot": {"project": workspace.repository.project(pid)}},
                path,
            )

    # 验证已结算产物身份并读取固定摘要对象；不用可变受管文件制造历史下载。
    def artifact(self, decision_id):
        with MythRuntime(self.root) as runtime:
            repository = Workspace(runtime).repository
            op = repository.operation(decision_id)
            if not op or op["state"] != "RESOLVED" or not op["result"].get("artifact"):
                raise KeyError(decision_id)
            artifact = op["result"]["artifact"]
            return artifact["name"], runtime.objects.get(artifact["digest"])

    # 将明确会话消息生成 Markdown 数据；导出不改变业务事实。
    def export(self, kind, identity):
        with MythRuntime(self.root) as runtime:
            repository = Workspace(runtime).repository
            if kind == "messages":
                row = runtime.store.db.execute(
                    "SELECT role,content FROM workspace_messages WHERE id=?",
                    (identity,),
                ).fetchone()
                if not row or row["role"] != "assistant":
                    raise KeyError(identity)
                return "myth-answer.md", row["content"].encode("utf-8")
            session = repository.session(identity)
            text = (
                "# "
                + session["title"]
                + "\n\n"
                + "\n\n---\n\n".join(
                    "## "
                    + ("你" if m["role"] == "user" else "Myth")
                    + "\n\n"
                    + m["content"]
                    for m in session["messages"]
                )
            )
            return "myth-conversation.md", text.encode("utf-8")

    # 分派只读产品 API 到对应状态所有者；允许的恢复投影修正仍由仓储维护。
    def get(self, parts, query):
        if not parts:
            return self.bootstrap()
        if parts == ["platform"]:
            return self.platform()
        if parts == ["connection"]:
            return self.connection()
        if parts == ["memories"]:
            return {
                "memories": self.memories(
                    query.get("q", [""])[0],
                    query.get("kind", [None])[0],
                    int(query.get("limit", ["50"])[0]),
                )
            }
        if parts == ["goals"]:
            return {"goals": self.goals(query.get("archived", ["0"])[0] == "1")}
        if parts == ["schedules"]:
            return {
                "schedules": self.schedules(),
                "scheduler": dict(self.scheduler_state),
            }
        if len(parts) == 2 and parts[0] == "goals":
            return self.goal(parts[1])
        if len(parts) == 3 and parts[0] == "goals" and parts[2] == "triggers":
            return {"triggers": self.goal_triggers(parts[1])}
        if len(parts) == 3 and parts[0] == "goals" and parts[2] == "schedules":
            return {"schedules": self.schedules(parts[1])}
        if len(parts) == 3 and parts[0] == "goals" and parts[2] == "runs":
            return {"runs": self.goal_runs(parts[1])}
        if parts == ["personal-state"]:
            return {"state": self.personal_state()}
        if parts == ["sessions"]:
            return {
                "sessions": self._use(
                    "sessions", query.get("archived", ["0"])[0] == "1"
                )
            }
        if len(parts) == 2 and parts[0] == "sessions":
            return self.session(parts[1])
        if len(parts) == 2 and parts[0] == "documents":
            return self._use("document", parts[1])
        if parts == ["search"]:
            return self._use(
                "search_report",
                query.get("q", [""])[0],
                query.get("project_id", [None])[0],
            )
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "files":
            return self.project_files(parts[1], query.get("path", ["."])[0])
        raise KeyError("endpoint")

    # 分派明确产品写入操作；参数、身份与权限规则由对应用例/仓储校验。
    def post(self, parts, value):
        if parts == ["settings"]:
            return self._use("save_settings", value)
        if parts == ["connection"]:
            return self.connection(value)
        if parts == ["memories"]:
            return self.remember(value)
        if parts == ["goals"]:
            return self.create_goal(value)
        if len(parts) == 3 and parts[0] == "schedules" and parts[2] == "enabled":
            return self.enable_schedule(parts[1], value)
        if len(parts) == 3 and parts[0] == "goals" and parts[2] == "state":
            return self.set_goal_state(parts[1], value)
        if len(parts) == 3 and parts[0] == "goals" and parts[2] == "schedules":
            return self.schedule_goal(parts[1], value)
        if len(parts) == 3 and parts[0] == "goals" and parts[2] == "triggers":
            return self.add_goal_trigger(parts[1], value)
        if len(parts) == 3 and parts[0] == "goals" and parts[2] == "work":
            return self.update_goal_work(parts[1], value)
        if parts == ["personal-state"]:
            return self.set_personal_state(value)
        if len(parts) == 3 and parts[0] == "memories" and parts[2] == "revoke":
            return self.revoke_memory(parts[1])
        if parts == ["projects"]:
            return self._use("create_project", value)
        if len(parts) == 2 and parts[0] == "projects":
            return self._use("update_project", parts[1], value)
        if parts == ["sessions"]:
            return self._use(
                "create_session", value.get("title", "新对话"), value.get("project_id")
            )
        if len(parts) == 2 and parts[0] == "sessions":
            return self._use("update_session", parts[1], value)
        if len(parts) == 3 and parts[0] == "sessions" and parts[2] == "messages":
            return self.send(parts[1], value)
        if parts == ["documents"]:
            return self._use("import_document", value)
        if len(parts) == 3 and parts[0] == "documents" and parts[2] == "archive":
            return self._use("archive_document", parts[1])
        if len(parts) == 3 and parts[0] == "turns":
            return self.control(parts[1], parts[2], value)
        raise KeyError("endpoint")
