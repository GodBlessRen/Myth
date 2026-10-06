"""对话 HTTP 产品门面与后台 Driver 生命周期。
每个操作打开独立 Runtime 连接；线程 active 集只管理本进程，持久 Lease/游标控制恢复。HTTP 生命周期不等于 Run 生命周期。"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
import time
import uuid

from .runtime import MythRuntime
from .workspace import Workspace
from .providers import create_provider
from .providers.ollama import OllamaProvider
from .model_capabilities import validate_model_selection
from .platform.control import ControlCommand
from .strategies import RuleIntentPicker
from .goal_scheduler import GoalScheduler
from .durable_executor import executor_snapshot, run_liveness
from .session_statistics import session_statistics, measured_integer, unique_records, usage_measurements
from .adapters.model_catalog import PublicModelCatalog


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
        # _connection_cache：最多十六个 Ollama 端点的五秒公开目录缓存；失败不缓存，不保存认证信息。
        self._connection_cache = {}
        # _connection_lock：目录检查串行化避免同时刷新；不与 Runtime 写事务组合。
        self._connection_lock = threading.Lock()
        # model_catalog：固定公共目录缓存，价格网络查询只在业务事务之外进行。
        self.model_catalog = PublicModelCatalog()

    # 逐次读取待恢复/到期机会，在事务外检查供应商，再准入并交正常 Driver；本机调度并发有上限。
    def scheduler_tick(self):
        # 恢复已有 Run 优先于到期准入；Provider 检查在数据库外，抢占资格仍由 Scheduler 原子决定。
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

    def _use_knowledge(self, method, *args):
        """把知识 API 交给知识仓储；请求自带连接生命周期，不让对话仓储代写文档。"""
        with MythRuntime(self.root) as runtime:
            return getattr(Workspace(runtime).repository.knowledge, method)(*args)

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
            value["vector_index"] = (
                workspace.vector_index.status()
                if workspace.vector_index is not None
                else {
                    "backend": "milvus",
                    "configured": False,
                    "healthy": False,
                    "last_error": None,
                }
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

    # mental_models：返回 materialized view 的紧凑状态并附加 auto-refresh policy；读取不会触发模型调用。
    def mental_models(self):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            values = workspace.knowledge_views.list_models()
            for item in values:
                try:
                    item["auto_refresh"] = workspace.mental_model_refresh.policy(
                        str(item["model_id"])
                    )
                except KeyError:
                    item["auto_refresh"] = {
                        "enabled": False,
                        "configured": False,
                    }
            return values

    # mental_model：读取单个模型及其 policy；L2 仍只展开已持久 materialized content，不自动刷新。
    def mental_model(self, model_id):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            value = workspace.knowledge_views.model(str(model_id), resolution="L2")
            try:
                value["auto_refresh"] = workspace.mental_model_refresh.policy(
                    str(model_id)
                )
            except KeyError:
                value["auto_refresh"] = {
                    "enabled": False,
                    "configured": False,
                }
            return value

    # create_mental_model：显式登记持续问题；创建本身不调用模型，后台刷新仍需另行 opt-in。
    def create_mental_model(self, value):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            return workspace.knowledge_views.create_model(
                name=value.get("name", ""),
                source_query=value.get("source_query", ""),
                scope_type=value.get("scope_type", "global"),
                scope_id=value.get("scope_id"),
            )

    # configure_mental_model_refresh：产品入口只配置 policy；真正 Provider I/O 由独立 Durable Executor 驱动。
    def configure_mental_model_refresh(self, model_id, value):
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            return workspace.mental_model_refresh.configure(
                str(model_id),
                enabled=value.get("enabled"),
                min_interval_seconds=value.get("min_interval_seconds", 300),
            )

    # knowledge_pages：只返回导航树；正文继续由 backing Mental Model/Memory 持有。
    def knowledge_pages(self):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).knowledge_views.tree()

    # 读取独立执行器心跳/租约投影；只反映 worker 生命，不把它冒充业务进度。
    def executor(self):
        with MythRuntime(self.root) as runtime:
            return executor_snapshot(runtime)

    # 装配页面初始项目/会话/设置/Goal/恢复和调度投影；刷新不驱动未授权效果。
    def bootstrap(self):
        # 同一 bootstrap 只打开一次数据库连接，避免重复装配/schema 检查及两次 Goal 查询。
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            repository = workspace.repository
            projects = repository.projects()
            sessions = repository.sessions()
            settings = repository.settings()
            documents = repository.knowledge.documents()
            goals = workspace.personal.goal_views()
        return {
            "projects": projects,
            "sessions": sessions,
            "settings": settings,
            "documents": documents,
            "platform": self.platform(),
            "memory_count": len(self.memories(limit=100)),
            "goals": goals,
            "goal_count": len(goals),
            "recoverable_runs": self.recoverable_runs(),
            "executor": self.executor(),
            "scheduler": dict(self.scheduler_state),
        }

    def extensions(self):
        """显式只读扩展目录入口；不在 bootstrap 轮询扫描技能，不启动 MCP 连接。"""
        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            result = {}
            for name, read in (("skills", workspace.skills.list_skills), ("mcp", workspace.mcp.servers),
                               ("hooks", workspace.tool_hooks.descriptors)):
                try:
                    result[name] = read()
                except (ValueError, PermissionError, OSError):
                    # 配置错误不会泄露本机命令/路径或拖垮另一种扩展目录。
                    result[name] = {"status": "unavailable", "error": "本机扩展配置或资源不可用"}
            return result

    # 按该 Turn/计划固定设置装配供应商；认证秘钥由独立适配器提供。
    def provider(self, settings):
        return create_provider(
            settings["provider"],
            ollama_base_url=settings.get("ollama_url"),
            runtime_root=str(self.root),
        )

    # 在数据库事务外检查固定供应商/model 可用性；ready 不代替真实调用结果。
    def connection(self, payload=None, *, force=False):
        settings = payload or self._use("settings")
        if settings.get("provider", "ollama") == "ollama":
            key = settings.get("ollama_url", "http://127.0.0.1:11434")
            with self._connection_lock:
                cached = self._connection_cache.get(key)
                if not force and cached and time.monotonic() - cached[0] < 5:
                    return {**cached[1], "details": {**cached[1]["details"], "models": list(cached[1]["details"].get("models", []))}}
                status = OllamaProvider(key, timeout=5).check()
                value = {"ready": status.ready, "provider": status.provider_id, "details": status.details or {}}
                if status.ready:
                    if len(self._connection_cache) >= 16:
                        self._connection_cache.clear()
                    self._connection_cache[key] = (time.monotonic(), value)
                else:
                    self._connection_cache.pop(key, None)
                return {**value, "details": {**value["details"], "models": list(value["details"].get("models", []))}}
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
        records = list(unique_records(invocations, "model_attempt_id"))
        measured = usage_measurements(records, ("input_tokens", "output_tokens", "cached_input_tokens", "provider_wall_ms"))
        totals = measured["totals"]
        input_tokens, output_tokens = totals["input_tokens"], totals["output_tokens"]
        cached_input_tokens = totals["cached_input_tokens"] if records else None
        provider_wall_ms = totals["provider_wall_ms"] if records else None
        # first_tokens：每个已报告调用的传输首个非空输出 delta 延迟，单位毫秒；无报告保留 N/A。
        first_tokens = []
        for item in records:
            usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
            first = measured_integer(usage.get("time_to_first_token_ms"))
            wall = measured_integer(usage.get("provider_wall_ms"))
            if first is not None and (wall is None or first <= wall):
                first_tokens.append(first)
        hit_rate = (
            cached_input_tokens / input_tokens
            if cached_input_tokens is not None and input_tokens is not None
            and input_tokens > 0 and cached_input_tokens <= input_tokens
            else None
        )
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "cache_hit_rate": hit_rate,
            "cache_metrics_available": cached_input_tokens is not None,
            "provider_wall_ms": provider_wall_ms,
            "provider_wall_available": provider_wall_ms is not None,
            "measurement_samples": measured["samples"],
            "model_calls": measured["attempts"],
            "first_token_ms": first_tokens[0] if first_tokens else None,
            "latest_first_token_ms": first_tokens[-1] if first_tokens else None,
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
            # 复用下方已读取的模型/工具事实，整段会话线性汇总；不为统计再增加逐轮 SQL 查询。
            model_invocations = []
            tool_operations = []
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
                model_invocations.extend(model_state["model_invocations"])
                tool_operations.extend(turn["operations"])
                # Execution Graph 只是现有 durable facts 的观测投影，不新增执行状态或授权。
                turn["execution_graph"] = workspace.components.observability.execution_graph(
                    run_id=turn["run_id"],
                    status=turn["status"],
                    model_state=model_state,
                    operations=turn["operations"],
                    main_pricing=(turn["settings"].get("model_pool") or {}).get("main_pricing"),
                    main_model=turn["settings"]["model"],
                )
                # Live Information Control 从已持久 activity 重建只读摘要；页面读取不新增策略状态。
                turn["information_control"] = (
                    workspace.execution.information_controller.summary(turn)
                )
                turn["model_usage"] = self._model_usage_summary(
                    model_state["model_invocations"]
                )
                latest_invocation = (
                    model_state["model_invocations"][-1]
                    if model_state["model_invocations"]
                    else None
                )
                turn["provider_evidence"] = (
                    latest_invocation.get("provider_evidence")
                    if latest_invocation
                    else None
                )
                goal_id = (turn.get("snapshot") or {}).get("goal", {}).get("goal_id")
                turn["goal_current"] = (
                    workspace.personal.goal_view(goal_id) if goal_id else None
                )
                turn["delivery"] = workspace.delivery.run_view(turn["run_id"])
                turn["sota_route"] = workspace.sota_route.view(turn["run_id"])
            value["artifacts"] = workspace.repository.artifacts(sid)
            value["statistics"] = session_statistics(model_invocations, tool_operations)
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
                workspace = Workspace(runtime)
                retry = workspace.repository.network_retry(rid)
                if retry and retry["retry_at"] > time.time():
                    with self.lock:
                        self.active.discard(rid)
                    return
                claimed = workspace.repository.claim_driver(
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

        # 只在成功取得租约后使用；未启动与正常退出共用一个 owner 清理规则。
        def release_claim():
            try:
                with MythRuntime(self.root) as runtime:
                    Workspace(runtime).repository.release_driver(rid, owner_id)
            except Exception:
                # 不伪报持久释放；租约仍由 TTL 与恢复核对约束，日志不附可能含秘密的异常正文。
                logging.getLogger(__name__).warning("Driver lease cleanup failed; durable lease remains until expiry.")
            finally:
                with self.lock:
                    self.active.discard(rid)

        # 启动心跳后才调用 Provider；心跳构造或 start 失败也进入同一恢复和清理路径。
        def work():
            heartbeat = None
            heartbeat_started = False
            try:
                heartbeat = threading.Thread(
                    target=self._heartbeat_loop,
                    args=(rid, owner_id, stop_heartbeat),
                    name=f"heartbeat-{rid[:12]}",
                    daemon=True,
                )
                heartbeat.start()
                heartbeat_started = True
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
                try:
                    if heartbeat_started:
                        heartbeat.join(timeout=1)
                finally:
                    release_claim()

        try:
            stop_heartbeat = threading.Event()
            threading.Thread(target=work, name=f"chat-{rid[:12]}", daemon=True).start()
        except Exception:
            # 只处理普通启动失败；BaseException 中断不能证明线程一定未启动。
            release_claim()
            raise

    # 校验明确用户消息与固定设置，由仓储在写事务外准备带版本的召回；提交后才启动 Driver。
    def send(self, sid, value):
        settings = self.model_catalog.quote_settings(self._use("settings"))
        text = value.get("text")
        goal_id = value.get("goal_id") or None
        pick = RuleIntentPicker().pick(str(text or ""), {})
        if pick.route.value != "deterministic":
            check = self.connection(settings)
            if not check["ready"]:
                raise ValueError("模型服务未连接，请在设置中检查模型连接。")
            validate_model_selection(settings, check.get("details"))

        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            # 仓储在召回前后核对 Goal/会话/Memory 版本，失败时不留下半准入 Run。
            turn = workspace.repository.create_turn(
                sid,
                text,
                value.get("request_id"),
                value.get("document_ids"),
                goal_id=goal_id,
                _settings=settings,
                _recall_memory=True,
            )
            workspace.control.ensure(turn["run_id"])
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
            "steer": ControlCommand.STEER,
            "switch_model": ControlCommand.SWITCH_MODEL,
            "switch_thinking": ControlCommand.SWITCH_THINKING,
            "compact": ControlCommand.COMPACT,
        }
        if action not in mapping:
            raise ValueError("unsupported control")

        expected_revision = None
        if action == "steer":
            payload = value.get("text")
        elif action in {"switch_model", "switch_thinking"}:
            payload = value.get("model") if action == "switch_model" else value.get("thinking")
            # 动态模型/档位必须相对当前 Control 投影验证；连续切换不能退回 Turn 最初设置。
            with MythRuntime(self.root) as runtime:
                workspace = Workspace(runtime)
                turn = workspace.repository.turn(rid)
                current = workspace.control.view(rid)
            expected_revision = current["revision"]
            current_model = current.get("model") or turn["settings"]["model"]
            current_thinking = (
                current["thinking"]
                if "thinking" in current
                else turn["settings"].get("thinking")
            )
            future_settings = {
                **turn["settings"],
                "model": payload if action == "switch_model" else current_model,
                "thinking": payload if action == "switch_thinking" else current_thinking,
            }
            check = self.connection(future_settings)
            if not check["ready"]:
                raise ValueError("模型服务未连接，不能切换未来模型设置。")
            validate_model_selection(future_settings, check.get("details"))
        else:
            payload = None

        with MythRuntime(self.root) as runtime:
            workspace = Workspace(runtime)
            projection = workspace.control.command(
                rid, mapping[action], payload, expected_revision=expected_revision
            )
            turn = workspace.repository.turn(rid)

        if action == "resume":
            self._spawn(rid)
        elif (
            action in {"steer", "switch_model", "switch_thinking", "compact"}
            and turn["status"] == "RUNNING"
        ):
            self._spawn(rid)

        return {"run_id": rid, "status": turn["status"], "control": projection}

    # 单 Run 交付投影；读取不会重跑模型/工具。
    def turn_delivery(self, run_id):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).delivery.run_view(run_id)

    # 读取单 Run 的 SOTA Route 对比；不生成新路径或模型调用。
    def turn_sota_route(self, run_id):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).sota_route.view(run_id)

    # 列出最近已验收路径；用于 Runtime/诊断，不改变活动策略。
    def sota_routes(self, limit=50):
        with MythRuntime(self.root) as runtime:
            return {"paths": Workspace(runtime).sota_route.list(limit)}

    # 汇总全分母验收、错误完成、待收尾与人工关注。
    def delivery_metrics(self):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).delivery.metrics()

    # 验收必须绑定当前 subject digest；模型文字不能直接升级成 PASS。
    def set_delivery_acceptance(self, run_id, value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).delivery.set_acceptance(
                run_id,
                state=value.get("state", "UNVERIFIED"),
                checker_id=value.get("checker_id", "human/manual"),
                evidence=value.get("evidence"),
                note=value.get("note", ""),
                subject_digest=value.get("subject_digest"),
            )

    # 记录连续自用中的人工关注时长。
    def record_delivery_attention(self, run_id, value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).delivery.record_attention(
                run_id,
                kind=value.get("kind", "review"),
                seconds=value.get("seconds"),
                note=value.get("note", ""),
            )

    # 给同一个 Run 增加持久阶段；plan_revision 必须单调增加。
    def plan_work_items(self, run_id, value):
        with MythRuntime(self.root) as runtime:
            return {
                "work_items": Workspace(runtime).delivery.plan_work_items(
                    run_id,
                    value.get("items") or [],
                    plan_revision=value.get("plan_revision"),
                )
            }

    # test.run 只能使用项目已显式建立的受限 profile。
    def verification_profiles(self, project_id):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).verification.list(project_id)

    # 创建明确受信项目的固定测试 profile；不接受任意命令文本。
    def create_verification_profile(self, project_id, value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).verification.create(project_id, value)

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

    # 按需读取某 Turn 最新或指定 Attempt 的完整脱敏 Provider Evidence；不重新调用模型。
    def provider_evidence(self, rid, attempt_id=None):
        with MythRuntime(self.root) as runtime:
            repository = Workspace(runtime).repository
            turn = repository.turn(rid)
            if turn["run_id"] != rid:
                raise KeyError(rid)
            return repository.decisions.provider_evidence(rid, attempt_id)

    # 分派只读产品 API 到对应状态所有者；允许的恢复投影修正仍由仓储维护。
    def get(self, parts, query):
        # 精确匹配路径段；例如 provider-evidence 仍核对所属 Run，未知 URL 不退化成文件读取。
        if not parts:
            return self.bootstrap()
        if parts == ["platform"]:
            return self.platform()
        if parts == ["extensions"]:
            return self.extensions()
        if parts == ["connection"]:
            return self.connection(force=True)
        if parts == ["memories"]:
            return {
                "memories": self.memories(
                    query.get("q", [""])[0],
                    query.get("kind", [None])[0],
                    int(query.get("limit", ["50"])[0]),
                )
            }
        if parts == ["mental-models"]:
            return {"mental_models": self.mental_models()}
        if len(parts) == 2 and parts[0] == "mental-models":
            return self.mental_model(parts[1])
        if parts == ["knowledge-pages"]:
            return {"knowledge_pages": self.knowledge_pages()}
        if parts == ["goals"]:
            return {"goals": self.goals(query.get("archived", ["0"])[0] == "1")}
        if parts == ["schedules"]:
            return {
                "schedules": self.schedules(),
                "scheduler": dict(self.scheduler_state),
            }
        if parts == ["delivery", "metrics"]:
            return self.delivery_metrics()
        if parts == ["sota-routes"]:
            return self.sota_routes(int(query.get("limit", ["50"])[0]))
        if len(parts) == 3 and parts[0] == "turns" and parts[2] == "delivery":
            return self.turn_delivery(parts[1])
        if len(parts) == 3 and parts[0] == "turns" and parts[2] == "sota-route":
            return self.turn_sota_route(parts[1])
        if len(parts) == 3 and parts[0] == "turns" and parts[2] == "provider-evidence":
            return self.provider_evidence(
                parts[1], query.get("attempt_id", [None])[0]
            )
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
            return self._use_knowledge("document", parts[1])
        if parts == ["search"]:
            return self._use_knowledge(
                "search_report",
                query.get("q", [""])[0],
                query.get("project_id", [None])[0],
            )
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "files":
            return self.project_files(parts[1], query.get("path", ["."])[0])
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "verification-profiles":
            return {"profiles": self.verification_profiles(parts[1])}
        raise KeyError("endpoint")

    # 分派明确产品写入操作；参数、身份与权限规则由对应用例/仓储校验。
    def post(self, parts, value):
        if parts == ["settings"]:
            # 先验证公开输入，再在事务外查询；最后一次短事务保存已解析配置。
            with MythRuntime(self.root) as runtime:
                clean = Workspace(runtime).repository.save_settings(value, validate_only=True)
            return self._use("save_settings", self.model_catalog.quote_settings(clean))
        if parts == ["model-info"]:
            if not isinstance(value, dict) or set(value) - {"provider", "model", "force"}:
                raise ValueError("invalid model info fields")
            return self.model_catalog.info(value.get("provider"), value.get("model", ""), force=value.get("force", False))
        if parts == ["connection"]:
            return self.connection(value, force=True)
        if parts == ["memories"]:
            return self.remember(value)
        if parts == ["mental-models"]:
            return self.create_mental_model(value)
        if (
            len(parts) == 3
            and parts[0] == "mental-models"
            and parts[2] == "auto-refresh"
        ):
            return self.configure_mental_model_refresh(parts[1], value)
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
            return self._use_knowledge("import_document", value)
        if len(parts) == 3 and parts[0] == "projects" and parts[2] == "verification-profiles":
            return self.create_verification_profile(parts[1], value)
        if len(parts) == 3 and parts[0] == "turns" and parts[2] == "acceptance":
            return self.set_delivery_acceptance(parts[1], value)
        if len(parts) == 3 and parts[0] == "turns" and parts[2] == "attention":
            return self.record_delivery_attention(parts[1], value)
        if len(parts) == 3 and parts[0] == "turns" and parts[2] == "work-items":
            return self.plan_work_items(parts[1], value)
        if len(parts) == 3 and parts[0] == "documents" and parts[2] == "archive":
            return self._use_knowledge("archive_document", parts[1])
        if len(parts) == 3 and parts[0] == "turns":
            return self.control(parts[1], parts[2], value)
        raise KeyError("endpoint")
