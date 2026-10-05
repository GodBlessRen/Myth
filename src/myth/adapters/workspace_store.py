"""项目、会话与对话步骤的 SQLite 状态所有者。
协调 Turn 的事务准入和恢复游标；Goal 写入通过个人仓储加入同一事务，检索/快照是数据投影而非权限。"""

from __future__ import annotations
import json
import time
import uuid
from contextlib import nullcontext
from ..domain import canonical_json, digest_json, IdentityConflict, BudgetExceeded, InvalidTransition
from ..domains.conversation_state import (
    ACTIVE_TURN_STATUSES,
    is_active,
    is_drivable,
    is_executor_candidate,
    is_pausable,
    require_transition,
)
from ..decision_runtime import DecisionRuntime
from ..strategies import RuleIntentPicker, RuleResolutionController
from ..platform.context_anchor import build_context_anchor
from ..platform.continuity import message_digest, plan_conversation_continuity
from ..platform.control import ControlCommand, ControlSnapshot
from ..network_recovery import reconnect_delay
from ..session_statistics import measured_integer
from .knowledge_store import SqliteKnowledgeRepository

# SCHEMA：本仓储拥有的当前表、索引与约束；由 Store 原子初始化，不叠加旧格式迁移。
# projects.root 是明确项目范围；archived/pinned 只管理未来可见性，不删除既有引用。
# turns.snapshot_json 冻结准入上下文；settings_json 可经显式 Control 修订，已发出的模型请求对象不改写。
# steps 的 step/current_step 单位为规划步骤；decision/result 绑定固定机会，不因重新渲染生成另一项执行。
# operations 的 reserved_bytes 是写入字节预留；ticket_id 是授权，result_json 不能靠模型自述填成收据。
# execution_cursors.checkpoint_step 表示已持久消费步骤；leases 时间为 UTC epoch 秒，owner/generation 防迟到释放。
SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_projects(
 id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,instructions TEXT NOT NULL,
 root TEXT,archived INTEGER NOT NULL DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS workspace_sessions(
 id TEXT PRIMARY KEY,project_id TEXT REFERENCES workspace_projects(id),title TEXT NOT NULL,
 pinned INTEGER NOT NULL DEFAULT 0,archived INTEGER NOT NULL DEFAULT 0,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS workspace_turns(
 run_id TEXT PRIMARY KEY REFERENCES runs(run_id),session_id TEXT REFERENCES workspace_sessions(id),
 request_id TEXT UNIQUE NOT NULL,entry_digest TEXT NOT NULL,settings_json TEXT NOT NULL,
 snapshot_json TEXT NOT NULL,status TEXT NOT NULL,current_step INTEGER NOT NULL DEFAULT 0,
 max_steps INTEGER NOT NULL,error TEXT,question_id TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS workspace_messages(
 id TEXT PRIMARY KEY,session_id TEXT REFERENCES workspace_sessions(id),run_id TEXT REFERENCES workspace_turns(run_id),
 role TEXT NOT NULL,content TEXT NOT NULL,metadata_json TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS workspace_steps(
 run_id TEXT REFERENCES workspace_turns(run_id),step INTEGER NOT NULL,state TEXT NOT NULL,
 decision_id TEXT,decision_json TEXT,result_json TEXT,PRIMARY KEY(run_id,step));
CREATE TABLE IF NOT EXISTS workspace_settings(id INTEGER PRIMARY KEY CHECK(id=1),value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_operations(
 decision_id TEXT PRIMARY KEY,run_id TEXT REFERENCES workspace_turns(run_id),capability TEXT NOT NULL,
 state TEXT NOT NULL,intent_json TEXT NOT NULL,result_json TEXT,ticket_id TEXT UNIQUE,
 reserved_bytes INTEGER NOT NULL DEFAULT 0,tool_wall_ms INTEGER);
CREATE TABLE IF NOT EXISTS workspace_execution_cursors(
 run_id TEXT PRIMARY KEY REFERENCES workspace_turns(run_id),
 step INTEGER NOT NULL DEFAULT 0,
 phase TEXT NOT NULL,
 checkpoint_step INTEGER NOT NULL DEFAULT 0,
 recovery_state TEXT NOT NULL DEFAULT 'NONE',
 detail TEXT NOT NULL DEFAULT '',
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS workspace_driver_leases(
 run_id TEXT PRIMARY KEY REFERENCES workspace_turns(run_id),
 owner_id TEXT NOT NULL,
 generation INTEGER NOT NULL DEFAULT 1,
 lease_until REAL NOT NULL,
 heartbeat_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_network_retries(
 run_id TEXT PRIMARY KEY REFERENCES workspace_turns(run_id),
 failures INTEGER NOT NULL,offline_since REAL NOT NULL,
 last_checked_at REAL NOT NULL,retry_at REAL NOT NULL,reason TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS workspace_messages_session ON workspace_messages(session_id);
CREATE INDEX IF NOT EXISTS workspace_messages_run ON workspace_messages(run_id);
CREATE INDEX IF NOT EXISTS workspace_turns_session ON workspace_turns(session_id);
CREATE INDEX IF NOT EXISTS workspace_sessions_project ON workspace_sessions(project_id,archived);
CREATE INDEX IF NOT EXISTS workspace_operations_run ON workspace_operations(run_id,state);
"""


# 生成带对象类别前缀的新身份；只用于新对象，不能作为重试时的效果证明。
def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"




# _write_turn_status：Turn 状态只能由仓储在事务内落库；纯 FSM 先校验语义，SQL 仍是唯一持久事实。
def _write_turn_status(db, rid: str, current: str, target: str, *, error=None, question_id=None) -> None:
    require_transition(current, target)
    db.execute(
        "UPDATE workspace_turns SET status=?,error=?,question_id=? WHERE run_id=?",
        (target, error, question_id, rid),
    )


# 拥有工作区与 Turn 状态的适配器；准入协调同连接个人仓储，冻结历史快照且维护恢复游标。
class SqliteWorkspaceRepository:
    # 保存共享连接及个人状态协作者，原子建立当前表；跨聚合准入必须加入同连接活动事务。
    def __init__(
        self,
        runtime,
        *,
        personal=None,
        intent_picker=None,
        resolution_controller=None,
        resolution_policy_id=None,
        vector_index=None,
        evaluation_harness_mechanisms=None,
        memory_state=None,
    ):
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        self.runtime = runtime
        # store：持久事实仓储；短事务维护本地一致性；外部效果不能并入数据库事务。
        self.store = runtime.store
        # personal：长期意图及进度的状态所有者；对话准入通过显式事务协作加入。
        self.personal = personal
        # memory_state：只读协作者提供 Current Facts 版本摘要；Memory 正文和 revision 仍由 Memory 仓储独占写入。
        self.memory_state = memory_state
        # decisions：模型请求/收据协调器；提供固定身份，不授予模型直接执行权。
        self.decisions = DecisionRuntime(runtime)
        # intent_picker：纯路径选择策略；输出是提案，不改变能力范围。
        self.intent_picker = intent_picker or RuleIntentPicker()
        # resolution_controller：同源信息表示策略；L0/L1/L2 不等于验收置信度。
        self.resolution_controller = resolution_controller or RuleResolutionController()
        # resolution_policy_id：本次准入固定的表示策略版本身份；活动指针变化不倒写历史 Turn。
        self.resolution_policy_id = str(resolution_policy_id or "injected/default")
        # evaluation_harness_mechanisms：仅固定评测注入；None 表示生产默认全部现有机制，显式集合用于受控消融。
        self.evaluation_harness_mechanisms = (
            None
            if evaluation_harness_mechanisms is None
            else tuple(str(item).strip() for item in evaluation_harness_mechanisms if str(item).strip())
        )
        # sota_route：由 Workspace 装配后注入；仓储缺省仍可独立工作，避免隐藏硬依赖。
        self.sota_route = None
        self.store.ensure_schema(SCHEMA)
        # knowledge：独立知识状态所有者；项目身份只经显式只读回调核对，共用连接便于冻结准入快照。
        self.knowledge = SqliteKnowledgeRepository(runtime, project_lookup=self.project, vector_index=vector_index)
    # 读取当前完整设置；首次未配置时提供默认值，保存后的配置不再做旧字段映射。
    def settings(self):
        row = self.store.db.execute(
            "SELECT value_json FROM workspace_settings WHERE id=1"
        ).fetchone()
        if row:
            value = json.loads(row[0])
            return value
        return {
            "provider": "ollama",
            "model": "",
            "ollama_url": "http://127.0.0.1:11434",
            "max_steps": 12,
            "max_output_tokens": 2048,
            "thinking": None,
            "num_ctx": 8192,
            "temperature": 0.0,
        }

    # 校验 endpoint、模型、窗口与输出/步骤上限后保存白名单字段；拒绝 token 等未声明持久字段。
    def save_settings(self, value, *, validate_only=False):
        from ..platform.model_pool import clean_pool, PROVIDERS
        provider = value.get("provider", "ollama")
        if provider not in PROVIDERS:
            raise ValueError("unsupported model provider")
        from urllib.parse import urlparse

        endpoint = str(value.get("ollama_url", "http://127.0.0.1:11434")).rstrip("/")
        parsed = urlparse(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid model endpoint")
        model = str(value.get("model", "")).strip()
        if len(model) > 200:
            raise ValueError("model name too long")
        steps = value.get("max_steps", 12)
        tokens = value.get("max_output_tokens", 2048)
        num_ctx = value.get("num_ctx", 8192)
        temperature = value.get("temperature", 0.0)
        if (
            type(steps) is not int
            or not 2 <= steps <= 32
            or type(tokens) is not int
            or not 128 <= tokens <= 393216
        ):
            raise ValueError("invalid step or token limit")
        if type(num_ctx) is not int or not 2048 <= num_ctx <= 262144:
            raise ValueError("num_ctx must be between 2048 and 262144")
        if provider == "ollama" and num_ctx <= min(tokens, 261632) + 512:
            raise ValueError(
                "num_ctx must leave room for output tokens and context reserve"
            )
        ceiling = 1 if provider == "anthropic" else 2
        if type(temperature) not in {int, float} or not 0 <= float(temperature) <= ceiling:
            raise ValueError(f"采样温度须为 0–{ceiling}")
        # thinking 保存 Provider 原生选项；Core 只限制形状，不维护全局 effort 枚举。
        from ..model_capabilities import normalize_thinking
        thinking = normalize_thinking(value.get("thinking"))
        clean = {
            "provider": provider,
            "model": model,
            "ollama_url": endpoint,
            "max_steps": steps,
            "max_output_tokens": tokens,
            "thinking": thinking,
            "num_ctx": num_ctx,
            "temperature": float(temperature),
            "model_pool": clean_pool(value.get("model_pool")),
        }
        if validate_only:
            return clean
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO workspace_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value_json=excluded.value_json",
                (canonical_json(clean),),
            )
        return clean

    def model_feedback(self):
        """经验是已结算主模型评分的投影；最多读取最近 200 条，不新建第二份可变真相。"""
        rows = self.store.db.execute(
            "SELECT result_json FROM workspace_operations WHERE capability='agent.evaluate' "
            "AND state='RESOLVED' ORDER BY rowid DESC LIMIT 200"
        ).fetchall()
        return [json.loads(row[0])["review"] for row in rows if json.loads(row[0]).get("review")]

    def delegation_state(self, decision_id):
        """子流程以不可变对象和有序事件保存检查点；已有工具合同负责限定父 Run 身份。"""
        op = self.operation(decision_id)
        if not op or not op["intent"].get("delegate"):
            return None
        row = self.store.db.execute(
            "SELECT payload_json FROM events WHERE run_id=? AND kind='SubagentCheckpoint' "
            "AND json_extract(payload_json,'$.delegation_id')=? ORDER BY sequence DESC LIMIT 1",
            (op["run_id"], decision_id),
        ).fetchone()
        return json.loads(self.runtime.objects.get(json.loads(row[0])["state_ref"])) if row else None

    def checkpoint_delegation(self, decision_id, state, *, expected_revision):
        """对象先发布，事件 CAS 后提交；崩溃只可能留下未引用对象，不部分更新子游标。"""
        value = {**state, "revision": expected_revision + 1}
        state_ref = self.runtime.objects.put(canonical_json(value).encode())
        with self.store.tx() as db:
            op = self.operation(decision_id)
            if not op or not op["intent"].get("delegate") or op["state"] == "RESOLVED":
                raise ValueError("delegation is not accepting checkpoints")
            current = self.delegation_state(decision_id)
            if (current or {}).get("revision", 0) != expected_revision:
                raise IdentityConflict("sub-agent checkpoint revision changed")
            self.store._event(db, op["run_id"], "SubagentCheckpoint", {
                "delegation_id": decision_id, "state_ref": state_ref, "revision": value["revision"],
                "status": value["status"], "step": value["current_step"],
            })
        return value

    # 投影未归档项目及会话/知识数量；统计不授予文件范围。
    def projects(self):
        return [
            dict(r)
            for r in self.store.db.execute(
                "SELECT p.*,(SELECT count(*) FROM workspace_sessions s WHERE s.project_id=p.id AND s.archived=0) session_count,(SELECT count(*) FROM workspace_documents d WHERE d.project_id=p.id AND d.archived=0) document_count FROM workspace_projects p WHERE p.archived=0 ORDER BY p.rowid DESC"
            )
        ]

    # 取得未归档项目的明确根目录与指令；参数不是任意文件访问授权。
    def project(self, pid):
        row = self.store.db.execute(
            "SELECT * FROM workspace_projects WHERE id=? AND archived=0", (pid,)
        ).fetchone()
        if not row:
            raise KeyError(pid)
        return dict(row)

    # 确认显式目录存在后保存项目身份与有界描述；未来 Turn 冻结这一范围。
    def create_project(self, value):
        name = str(value.get("name", "")).strip()
        if not name or len(name) > 100:
            raise ValueError("project name must contain 1-100 characters")
        root = value.get("root") or None
        if root:
            from pathlib import Path

            path = Path(root).expanduser().resolve()
            if not path.is_dir():
                raise ValueError("project directory does not exist")
            root = str(path)
        pid = new_id("project")
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO workspace_projects(id,name,description,instructions,root) VALUES(?,?,?,?,?)",
                (
                    pid,
                    name,
                    str(value.get("description", "")).strip()[:1000],
                    str(value.get("instructions", "")).strip()[:12000],
                    root,
                ),
            )
        return self.project(pid)

    # 更新未来会话可读取的项目元数据；已准入 Turn 的固定快照不倒写。
    def update_project(self, pid, value):
        old = self.project(pid)
        if "name" in value and not str(value["name"]).strip():
            raise ValueError("name is required")
        root = value.get("root", old["root"]) or None
        if root:
            from pathlib import Path

            path = Path(root).expanduser().resolve()
            if not path.is_dir():
                raise ValueError("project directory does not exist")
            root = str(path)
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "UPDATE workspace_projects SET name=?,description=?,instructions=?,root=?,archived=? WHERE id=?",
                (
                    str(value.get("name", old["name"])).strip()[:100],
                    str(value.get("description", old["description"]))[:1000],
                    str(value.get("instructions", old["instructions"]))[:12000],
                    root,
                    int(bool(value.get("archived", False))),
                    pid,
                ),
            )
        return {"id": pid}

    # 按归档、置顶和更新时间生成会话导航；运行状态仍来自 Turn。
    def sessions(self, archived=False):
        return [
            dict(r)
            for r in self.store.db.execute(
                "SELECT s.*,p.name project_name,(SELECT content FROM workspace_messages m WHERE m.session_id=s.id ORDER BY m.rowid DESC LIMIT 1) preview FROM workspace_sessions s LEFT JOIN workspace_projects p ON p.id=s.project_id WHERE s.archived=? ORDER BY pinned DESC,s.updated_at DESC,s.rowid DESC",
                (int(archived),),
            )
        ]

    # 验证项目身份后创建独立会话；会话本身没有模型或工具 Ticket。
    def create_session(self, title="新对话", project_id=None):
        if project_id:
            self.project(project_id)
        sid = new_id("session")
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "INSERT INTO workspace_sessions(id,title,project_id) VALUES(?,?,?)",
                (sid, str(title).strip()[:100] or "新对话", project_id),
            )
        return self.session(sid)

    # 读取会话及其消息/轮次投影；持久状态仍由仓储操作修改。
    def session(self, sid):
        row = self.store.db.execute(
            "SELECT s.*,p.name project_name FROM workspace_sessions s LEFT JOIN workspace_projects p ON p.id=s.project_id WHERE s.id=?",
            (sid,),
        ).fetchone()
        if not row:
            raise KeyError(sid)
        result = dict(row)
        result["messages"] = [
            {**dict(r), "metadata": json.loads(r["metadata_json"])}
            for r in self.store.db.execute(
                "SELECT * FROM workspace_messages WHERE session_id=? ORDER BY rowid",
                (sid,),
            )
        ]
        result["turns"] = [
            self.turn(r[0])
            for r in self.store.db.execute(
                "SELECT run_id FROM workspace_turns WHERE session_id=? ORDER BY rowid",
                (sid,),
            )
        ]
        return result

    # 保存会话标题/项目/置顶/归档元数据；有未完成工作时不允许归档。
    def update_session(self, sid, value):
        old = self.session(sid)
        if any(t["status"] in ACTIVE_TURN_STATUSES for t in old["turns"]) and value.get(
            "archived"
        ):
            raise ValueError("stop the active turn before archiving")
        pid = value.get("project_id", old["project_id"])
        if pid:
            self.project(pid)
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "UPDATE workspace_sessions SET title=?,project_id=?,pinned=?,archived=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    str(value.get("title", old["title"])).strip()[:100] or "新对话",
                    pid,
                    int(bool(value.get("pinned", old["pinned"]))),
                    int(bool(value.get("archived", old["archived"]))),
                    sid,
                ),
            )
        return self.session(sid)


    # 同事务去重入口、校验会话/Goal、冻结上下文、预算、Turn、Goal 关联和游标；调度 occurrence 可加入同一连接事务。
    def create_turn(
        self,
        sid,
        text,
        request_id,
        document_ids=None,
        memory_records=None,
        goal_id=None,
        goal_context=None,
        memory_retrieval_report=None,
        *,
        _db=None,
        _settings=None,
    ):
        # 调度机会显式加入相同连接事务；RuntimeStore.tx 保持不可嵌套，外部效果不因此移入事务。
        if _db is not None and (_db is not self.store.db or not _db.in_transaction):
            raise RuntimeError("admission requires this store's active transaction")
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text.encode("utf-8")) > 16000
        ):
            raise ValueError("message must contain 1-16000 UTF-8 bytes")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 200:
            raise ValueError("request_id is required")
        settings = dict(_settings) if _settings is not None else self.settings()
        if not settings["model"]:
            raise ValueError("请先在模型设置中选择模型。")
        document_ids = document_ids or []
        memory_records = memory_records or []
        if (
            not isinstance(document_ids, list)
            or len(document_ids) > 4
            or any(not isinstance(d, str) for d in document_ids)
        ):
            raise ValueError("attach at most four document ids")
        # 入口身份绑定用户意图、固定设置和显式附件；召回 Memory 是准入后投影，环境记忆变化不能破坏同 request_id 重试。
        from ..platform.model_pool import pricing_identity
        identity = digest_json(
            {
                "session_id": sid,
                "text": text,
                "settings": pricing_identity(settings),
                "documents": document_ids,
                "goal_id": goal_id,
                "evaluation_harness_mechanisms": self.evaluation_harness_mechanisms,
            }
        )
        with self.store.tx() if _db is None else nullcontext(_db) as db:
            existing = db.execute(
                "SELECT run_id,entry_digest FROM workspace_turns WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if existing:
                if existing["entry_digest"] != identity:
                    raise IdentityConflict(
                        "request_id reused with different message or settings"
                    )
                return self.turn(existing["run_id"])
            session = self.session(sid)
            if session["archived"]:
                raise ValueError("restore the archived conversation first")
            if any(t["status"] in ACTIVE_TURN_STATUSES for t in session["turns"]):
                raise ValueError("本会话仍有未完成一轮，请先继续、答复或停止。")
            if goal_id:
                if self.personal is None:
                    raise RuntimeError(
                        "Goal admission requires the personal-state repository"
                    )
                # 本仓储协调 Turn 原子准入；个人表的校验和写入交给其状态所有者。
                goal_context = self.personal.admission_snapshot(db, goal_id)
                occupied = db.execute(
                    "SELECT 1 FROM goal_runs g JOIN workspace_turns t ON t.run_id=g.run_id "
                    "WHERE g.goal_id=? AND t.status IN ('RUNNING','INTERRUPTED','UNKNOWN','WAITING_USER','PAUSED') LIMIT 1",
                    (goal_id,),
                ).fetchone()
                if occupied:
                    raise ValueError(
                        "Goal has unfinished work; continue or stop that Run first"
                    )
            project = (
                self.project(session["project_id"]) if session["project_id"] else None
            )
            # Current Facts 与 query-based Recall 分开：版本绑定来自权威 Memory 状态，不由相似度排名决定。
            current_facts = (
                self.memory_state.continuity_facts(
                    project_id=session["project_id"], session_id=sid
                )
                if self.memory_state is not None
                else {
                    "policy": "current-facts-unbound",
                    "count": 0,
                    "digest": None,
                }
            )
            retrieval = self.knowledge.search_report(text, session["project_id"])
            knowledge = list(retrieval["sources"])
            for did in document_ids:
                document = self.knowledge.document(did)
                if document["archived"]:
                    raise ValueError("attachment was removed from the retrieval index")
                if document["project_id"] not in {None, session["project_id"]}:
                    raise PermissionError("attachment belongs to another project")
                if not any(s["document_id"] == did for s in knowledge):
                    knowledge.append(
                        {
                            "document_id": did,
                            "title": document["title"],
                            "content": document["content"][:1800],
                            "chunk_index": 0,
                            "digest": document["digest"],
                            "citation": f"doc:{did}:0",
                            "score": 0,
                        }
                    )
            if document_ids:
                # 每份显式附件先保留至少一个代表来源；同文档多片段不能挤掉另一份固定附件。
                pinned = set(document_ids)
                representatives = []
                for did in document_ids:
                    candidates = [
                        item for item in knowledge if item["document_id"] == did
                    ]
                    if candidates:
                        representatives.append(
                            max(
                                candidates,
                                key=lambda item: float(item.get("score") or 0.0),
                            )
                        )
                representative_ids = {
                    (item["document_id"], item.get("chunk_index"))
                    for item in representatives
                }
                remainder = [
                    item
                    for item in knowledge
                    if (item["document_id"], item.get("chunk_index"))
                    not in representative_ids
                ]
                remainder.sort(
                    key=lambda item: (
                        item["document_id"] not in pinned,
                        -float(item.get("score") or 0.0),
                    )
                )
                knowledge = representatives + remainder
            pick = self.intent_picker.pick(
                text,
                {
                    "project": project,
                    "sources": knowledge,
                    "attached_document_ids": document_ids,
                },
            )
            plan = self.resolution_controller.choose(
                text,
                route=pick.route,
                sources=knowledge,
                attached_document_ids=document_ids,
            )
            projected_knowledge = []
            effective_max = max(plan.max_sources, len(document_ids))
            for source in knowledge[:effective_max]:
                item = dict(source)
                item["source_ref"] = f"doc:{item['document_id']}@{item['digest']}"
                if plan.resolution.value == "L0":
                    item["content"] = item.get("content", "")[
                        : plan.max_chars_per_source
                    ]
                elif plan.resolution.value == "L2":
                    document = self.knowledge.document(item["document_id"])
                    chunk_index = int(item.get("chunk_index") or 0)
                    start = max(0, chunk_index * 1600 - 800)
                    item["content"] = document["content"][
                        start : start + plan.max_chars_per_source
                    ]
                    item["source_ref"] = (
                        f"doc:{item['document_id']}@{document['digest']}"
                    )
                    item["resolution_offset"] = start
                item["resolution"] = plan.resolution.value
                projected_knowledge.append(item)
            # Continuity 在 Turn 准入事务内核对完整持久消息；Context Anchor 只在证明可复用后增量推进。
            history_records = list(session["messages"])
            history_messages = [
                {"role": m["role"], "content": m["content"]}
                for m in history_records
            ]
            previous_turn = None
            previous_row = db.execute(
                "SELECT run_id,status,snapshot_json FROM workspace_turns "
                "WHERE session_id=? ORDER BY rowid DESC LIMIT 1",
                (sid,),
            ).fetchone()
            if previous_row:
                previous_turn = {
                    "run_id": previous_row["run_id"],
                    "status": previous_row["status"],
                    "snapshot": json.loads(previous_row["snapshot_json"]),
                }
            continuity = plan_conversation_continuity(
                previous_turn=previous_turn,
                history=history_records,
                settings=settings,
                project=project,
                current_facts=current_facts,
            )
            previous_anchor = (
                previous_turn["snapshot"].get("context_anchor")
                if previous_turn and continuity["anchor_reuse"]
                else None
            )
            context_anchor = (
                build_context_anchor(
                    previous_anchor,
                    history_messages,
                    cover_count=max(0, len(history_messages) - 8),
                )
                if len(history_messages) > 12
                else previous_anchor
            )
            recent_history = (
                history_messages[-8:] if context_anchor else history_messages[-30:]
            )
            snapshot = {
                "project": project,
                "knowledge": projected_knowledge,
                "retrieval_report": retrieval["retrieval"],
                "intent_pick": {
                    "route": pick.route.value,
                    "objective": pick.objective,
                    "confidence": pick.confidence,
                    "reason": pick.reason,
                    "metadata": pick.metadata or {},
                },
                "information_resolution": plan.serializable(),
                "policy_bindings": {
                    "information_resolution": self.resolution_policy_id,
                },
                "attached_document_ids": list(document_ids),
                "context_anchor": context_anchor,
                "continuity": continuity,
                "turn_message_start": len(recent_history),
                "memory": [
                    {
                        "memory_id": m.get("memory_id"),
                        "kind": m.get("kind"),
                        "text": m.get("text", ""),
                        "source_ref": m.get("source_ref"),
                        "provenance_ref": m.get("provenance_ref"),
                        "scope_type": m.get("scope_type", "global"),
                        "scope_id": m.get("scope_id"),
                        "fact_level": m.get("fact_level", "context"),
                        "revision": m.get("revision"),
                        "resolution": m.get("resolution", "L0"),
                    }
                    for m in memory_records[:8]
                ],
                "memory_retrieval_report": dict(memory_retrieval_report or {}),
                "messages": recent_history
                + [{"role": "user", "content": text}],
                "goal": dict(goal_context or {}),
            }
            if self.evaluation_harness_mechanisms is not None:
                snapshot["evaluation_harness_mechanisms"] = list(
                    self.evaluation_harness_mechanisms
                )
            if self.sota_route is not None:
                # 冻结项目/上下文环境摘要，使“SOTA Route”只在可证明同条件时比较。
                snapshot["sota_route_environment"] = self.sota_route.freeze_environment(snapshot)
                hint = self.sota_route.hint_for_snapshot(text, settings, snapshot)
                if hint:
                    snapshot["sota_route_hint"] = hint
            rid = new_id("run")
            db.execute(
                "INSERT INTO runs(run_id,request_id,entry_digest,goal,acceptance_version,state) VALUES(?,?,?,?,?,'RUNNING')",
                (rid, request_id, identity, text, "conversation-v1"),
            )
            for meter, limit in {
                "model_calls": settings["max_steps"],
                "input_tokens": 2_000_000,
                "output_tokens": settings["max_steps"] * settings["max_output_tokens"],
                "tool_calls": settings["max_steps"],
                "write_bytes": 4_000_000,
            }.items():
                db.execute(
                    "INSERT INTO accounts(run_id,meter,limit_units) VALUES(?,?,?)",
                    (rid, meter, limit),
                )
            db.execute(
                "INSERT INTO workspace_turns(run_id,session_id,request_id,entry_digest,settings_json,snapshot_json,status,max_steps) VALUES(?,?,?,?,?,?,'RUNNING',?)",
                (
                    rid,
                    sid,
                    request_id,
                    identity,
                    canonical_json(settings),
                    canonical_json(snapshot),
                    settings["max_steps"],
                ),
            )
            if goal_id:
                self.personal.bind_admitted_run(db, goal_id, rid)
            db.execute(
                "INSERT INTO workspace_execution_cursors(run_id,step,phase,checkpoint_step,recovery_state,detail) VALUES(?,0,'ADMITTED',0,'NONE','Turn admitted')",
                (rid,),
            )
            self._message(db, sid, rid, "user", text, {})
            db.execute(
                "UPDATE workspace_sessions SET title=CASE WHEN title='新对话' THEN ? ELSE title END,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (text[:40], sid),
            )
            self.store._event(
                db,
                rid,
                "ConversationTurnStarted",
                {
                    "session_id": sid,
                    "intent_route": pick.route.value,
                    "information_resolution": plan.resolution.value,
                    "retrieval_scanned": retrieval["retrieval"]["scanned"],
                    "retrieval_matched": retrieval["retrieval"]["matched"],
                    "goal_id": goal_id,
                    "continuity_action": continuity["action"],
                    "continuity_epoch": continuity["epoch"],
                },
            )
            self.store._event(
                db,
                rid,
                "ConversationContinuityPlanned",
                {
                    "action": continuity["action"],
                    "reason": continuity["reason"],
                    "epoch": continuity["epoch"],
                    "anchor_reuse": continuity["anchor_reuse"],
                    "current_facts_digest": continuity["current_facts"]["digest"],
                },
            )
        return self.turn(rid)

    # 在调用方事务内写入消息事实及来源元数据；消息与步骤状态不能分开提交。
    def _message(self, db, sid, rid, role, text, metadata):
        # content_digest 随消息原子落库；以后正文若被改写，Continuity 可在复用前确定性拒绝旧历史。
        value = dict(metadata or {})
        value["content_digest"] = message_digest(role, text)
        db.execute(
            "INSERT INTO workspace_messages(id,session_id,run_id,role,content,metadata_json) VALUES(?,?,?,?,?,?)",
            (new_id("msg"), sid, rid, role, text, canonical_json(value)),
        )

    # 在已有事务中保存游标；checkpoint_step 是已消费步骤，纯连接恢复用 record_progress=False 保留进度时间。
    def _checkpoint(
        self,
        db,
        rid,
        step,
        phase,
        *,
        checkpoint_step=None,
        recovery_state="NONE",
        detail="",
        record_progress=True,
    ):
        checkpoint_step = step if checkpoint_step is None else checkpoint_step
        db.execute(
            "INSERT INTO workspace_execution_cursors(run_id,step,phase,checkpoint_step,recovery_state,detail,updated_at) "
            "VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(run_id) DO UPDATE SET step=excluded.step,phase=excluded.phase,"
            "checkpoint_step=excluded.checkpoint_step,recovery_state=excluded.recovery_state,"
            "detail=excluded.detail,updated_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE workspace_execution_cursors.updated_at END",
            (
                rid,
                int(step),
                str(phase),
                int(checkpoint_step),
                str(recovery_state),
                str(detail)[:1000],
                int(record_progress),
            ),
        )

    # 读取准入时原子创建的持久游标；缺失显式报错，禁止推算或制造恢复进度。
    def execution_cursor(self, rid):
        self.turn(rid)
        row = self.store.db.execute(
            "SELECT * FROM workspace_execution_cursors WHERE run_id=?", (rid,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"execution cursor missing for {rid}")
        return dict(row)

    # 在写事务竞争 owner/generation/到期时间；租约只声明负责人，真实互斥另由本机 Run 锁负责。
    def claim_driver(self, rid, owner_id, ttl_seconds=12):
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError("owner_id is required")
        now = time.time()
        lease_until = now + float(ttl_seconds)
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            turn = self.turn(rid)
            if not is_drivable(turn["status"]):
                return False
            old = db.execute(
                "SELECT * FROM workspace_driver_leases WHERE run_id=?", (rid,)
            ).fetchone()
            if old and old["owner_id"] != owner_id and float(old["lease_until"]) > now:
                return False
            generation = (
                (int(old["generation"]) + 1)
                if old and old["owner_id"] != owner_id
                else (int(old["generation"]) if old else 1)
            )
            db.execute(
                "INSERT INTO workspace_driver_leases(run_id,owner_id,generation,lease_until,heartbeat_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET owner_id=excluded.owner_id,generation=excluded.generation,"
                "lease_until=excluded.lease_until,heartbeat_at=excluded.heartbeat_at",
                (rid, owner_id, generation, lease_until, now),
            )
            self.store._event(
                db,
                rid,
                "DriverLeaseAcquired",
                {"owner_id": owner_id, "generation": generation},
            )
        return True

    # 仅当前 owner 更新 TTL；心跳失败停止本机持有资格，不能篡改其他 Driver 的租约。
    def heartbeat_driver(self, rid, owner_id, ttl_seconds=12):
        now = time.time()
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            changed = db.execute(
                "UPDATE workspace_driver_leases SET heartbeat_at=?,lease_until=? WHERE run_id=? AND owner_id=?",
                (now, now + float(ttl_seconds), rid, owner_id),
            )
            return bool(changed.rowcount)

    # 只释放匹配 owner 的租约；旧 Driver 退出不能删除新一代负责人。
    def release_driver(self, rid, owner_id):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            row = db.execute(
                "SELECT owner_id,generation FROM workspace_driver_leases WHERE run_id=?",
                (rid,),
            ).fetchone()
            if not row or row["owner_id"] != owner_id:
                return False
            db.execute("DELETE FROM workspace_driver_leases WHERE run_id=?", (rid,))
            self.store._event(
                db,
                rid,
                "DriverLeaseReleased",
                {"owner_id": owner_id, "generation": row["generation"]},
            )
        return True

    # 读取 owner/generation/epoch 到期时间，并派生 expired；派生布尔值不是执行结果。
    def driver_lease(self, rid):
        row = self.store.db.execute(
            "SELECT * FROM workspace_driver_leases WHERE run_id=?", (rid,)
        ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["expired"] = float(value["lease_until"]) <= time.time()
        return value

    # 只读持久等待；时间为 UTC epoch 秒，失败次数是连接机会而非模型消费，暂停/UNKNOWN 不获重发权。
    def network_retry(self, rid):
        row = self.store.db.execute("SELECT * FROM workspace_network_retries WHERE run_id=?", (rid,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["delay_seconds"] = reconnect_delay(int(value["failures"]))
        value["remaining_seconds"] = max(0, value["retry_at"] - time.time())
        return value

    # 原子提交等待和下次检查时间；没有未决效果才可自动继续，反复连接失败不推进业务 checkpoint。
    def defer_network(self, rid, *, now=None):
        now = time.time() if now is None else float(now)
        with self.store.tx() as db:
            turn = self.turn(rid)
            if not is_executor_candidate(turn["status"]) or self._has_uncertain_effect(rid):
                return None
            previous = db.execute("SELECT * FROM workspace_network_retries WHERE run_id=?", (rid,)).fetchone()
            # 同一次等待到期前的重复回调不增加退避，也不缩短已提交的截止时间。
            if previous and previous["retry_at"] > now:
                return dict(previous)
            failures = min(1_000_000, int(previous["failures"]) + 1) if previous else 1
            delay = reconnect_delay(failures)
            reason = "Provider unavailable; waiting to reconnect"
            db.execute("INSERT INTO workspace_network_retries VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET failures=excluded.failures,last_checked_at=excluded.last_checked_at,"
                "retry_at=excluded.retry_at,reason=excluded.reason",
                (rid, failures, previous["offline_since"] if previous else now, now, now + delay, reason))
            _write_turn_status(db, rid, turn["status"], "INTERRUPTED", error=reason)
            db.execute("UPDATE runs SET state='RECOVERING' WHERE run_id=?", (rid,))
            # 观察字段不更新 updated_at/checkpoint_step；重连心跳不能冒充真实任务进展。
            db.execute("UPDATE workspace_execution_cursors SET phase='WAITING_CONNECTION',recovery_state='RESUME',detail=? WHERE run_id=?",
                       (reason, rid))
            self.store._event(db, rid, "ReconnectScheduled", {"failures": failures, "delay_seconds": delay, "retry_at": now + delay})
        return self.network_retry(rid)

    # 只有工作真实继续（取得决定）才清除退避；凭据存在或健康检查通过不足以证明推理网络恢复。
    def network_restored(self, rid):
        with self.store.tx() as db:
            changed = db.execute("DELETE FROM workspace_network_retries WHERE run_id=?", (rid,))
            if changed.rowcount:
                self.store._event(db, rid, "ReconnectRestored", {})

    # 从已获 Ticket 的模型/工具机会判断效果不明；UI active 缓存不能替代此事实。
    def _has_uncertain_effect(self, rid):
        models = self.decisions.status(rid)["model_invocations"]
        if any(item["state"] in {"TICKETED", "UNKNOWN"} for item in models):
            return True
        return any(
            item["state"] in {"TICKETED", "UNKNOWN"}
            for item in self.pending_operations(rid)
            # 子工具 Ticket 是流程授权；已知游标可继续，不等于存在未决网络效果。
            if not ("parallel" in item["intent"] or item["intent"].get("delegate", {}).get("protocol_version") == "handoff-v2"
                    and (self.delegation_state(item["decision_id"]) or {}).get("status")
                    in {None, "RUNNING", "INTERRUPTED", "PAUSED", "COMPLETED", "FAILED", "BUDGET_EXHAUSTED", "CANCELLED"})
        )

    # 根据持久未决效果选择 INTERRUPTED 或 UNKNOWN，保存恢复游标；安全中断才可继续规划。
    def interrupt(self, rid, reason, *, record_progress=True):
        # 崩溃可能发生在收据发布与数据库结算之间；先核对已有模型证据，不能把已知零派发永久锁在 UNKNOWN。
        self.decisions.recover(rid)
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            turn = self.turn(rid)
            if not is_drivable(turn["status"]):
                return turn
            uncertain = self._has_uncertain_effect(rid)
            status = "UNKNOWN" if uncertain else "INTERRUPTED"
            recovery = "RECONCILE" if uncertain else "RESUME"
            if uncertain:
                for op in self.pending_operations(rid):
                    if op["state"] != "TICKETED":
                        continue
                    for meter, cost in {
                        "tool_calls": 1,
                        "write_bytes": op["reserved_bytes"],
                    }.items():
                        db.execute(
                            "UPDATE accounts SET reserved=reserved-?,unknown_held=unknown_held+? WHERE run_id=? AND meter=?",
                            (cost, cost, rid, meter),
                        )
                    db.execute(
                        "UPDATE workspace_operations SET state='UNKNOWN' WHERE decision_id=?",
                        (op["decision_id"],),
                    )
            _write_turn_status(db, rid, turn["status"], status, error=str(reason)[:2000])
            db.execute(
                "UPDATE runs SET state='RECOVERING',control_revision=control_revision+1 WHERE run_id=?",
                (rid,),
            )
            self._checkpoint(
                db,
                rid,
                turn["current_step"],
                "INTERRUPTED" if not uncertain else "OUTCOME_UNKNOWN",
                checkpoint_step=max(
                    [
                        int(item["step"])
                        for item in turn["activities"]
                        if item["state"] == "DONE"
                    ]
                    or [0]
                ),
                recovery_state=recovery,
                detail=reason,
                record_progress=record_progress,
            )
            self.store._event(
                db,
                rid,
                "ConversationInterrupted",
                {
                    "status": status,
                    "reason": str(reason)[:500],
                    "recovery_state": recovery,
                },
            )
        return self.turn(rid)

    # 过期 Lease 的 Run 按效果事实收束；不能仅因浏览器关闭就宣称失败或可重发。
    def sweep_expired_driver(self, rid):
        turn = self.turn(rid)
        if turn["status"] != "RUNNING":
            return turn
        lease = self.driver_lease(rid)
        if lease is None or lease["expired"]:
            return self.interrupt(
                rid,
                "Driver heartbeat expired; durable checkpoint preserved.",
                # Lease/恢复扫描只是观察，不得刷新 durable progress 时间。
                record_progress=False,
            )
        return turn

    # 读取 Turn、固定快照与步骤结果；返回值为投影，修改它不会提交持久事实。
    def turn(self, rid):
        row = self.store.db.execute(
            "SELECT * FROM workspace_turns WHERE run_id=?", (rid,)
        ).fetchone()
        if not row:
            raise KeyError(rid)
        result = dict(row)
        result["settings"] = json.loads(result.pop("settings_json"))
        result["snapshot"] = json.loads(result.pop("snapshot_json"))
        result["activities"] = [
            {
                **dict(r),
                "decision": (
                    json.loads(r["decision_json"]) if r["decision_json"] else None
                ),
                "result": json.loads(r["result_json"]) if r["result_json"] else None,
            }
            for r in self.store.db.execute(
                "SELECT * FROM workspace_steps WHERE run_id=? ORDER BY step", (rid,)
            )
        ]
        result["budgets"] = self.store.get_accounts(rid)
        cursor = self.store.db.execute(
            "SELECT * FROM workspace_execution_cursors WHERE run_id=?", (rid,)
        ).fetchone()
        result["execution_cursor"] = dict(cursor) if cursor else None
        result["network_retry"] = self.network_retry(rid)
        return result

    # 原子分配或复用当前未完成步骤；耗尽步数返回空值，恢复不跳过未消费的决定。
    def begin_step(self, rid):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            turn = self.turn(rid)
            if turn["status"] != "RUNNING":
                return None
            unfinished = next(
                (s for s in turn["activities"] if s["state"] != "DONE"), None
            )
            if unfinished:
                return unfinished
            number = turn["current_step"] + 1
            if number > turn["max_steps"]:
                return None
            db.execute(
                "INSERT INTO workspace_steps(run_id,step,state) VALUES(?,?,'STARTED')",
                (rid, number),
            )
            db.execute(
                "UPDATE workspace_turns SET current_step=? WHERE run_id=?",
                (number, rid),
            )
            self._checkpoint(
                db,
                rid,
                number,
                "STEP_STARTED",
                checkpoint_step=number - 1,
                detail=f"Step {number} started",
            )
            self.store._event(
                db,
                rid,
                "ExecutionCheckpoint",
                {
                    "step": number,
                    "phase": "STEP_STARTED",
                    "checkpoint_step": number - 1,
                },
            )
            return {"step": number}

    # 记录确定路径回退原因，供运行观测与评测审计；不改变权限范围。
    def record_route_fallback(self, rid, step, route, reason):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            turn = self.turn(rid)
            snapshot = turn["snapshot"]
            fallbacks = list(snapshot.get("route_fallbacks") or [])
            fallbacks.append({"step": step, "route": route, "reason": reason})
            snapshot["route_fallbacks"] = fallbacks[-8:]
            db.execute(
                "UPDATE workspace_turns SET snapshot_json=? WHERE run_id=?",
                (canonical_json(snapshot), rid),
            )
            self.store._event(
                db,
                rid,
                "RouteFallback",
                {"step": step, "route": route, "reason": reason},
            )

    # 把当前步骤与固定决定关联，并推进 durable cursor；禁止不同决定复用同一步。
    def bind(self, rid, step, decision_id, decision):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            db.execute(
                "UPDATE workspace_steps SET state='DECIDED',decision_id=?,decision_json=? WHERE run_id=? AND step=?",
                (decision_id, canonical_json(decision.serializable()), rid, step),
            )
            self._checkpoint(
                db,
                rid,
                step,
                "DECISION_BOUND",
                checkpoint_step=max(0, step - 1),
                detail=decision.decision_type,
            )
            self.store._event(
                db,
                rid,
                "ExecutionCheckpoint",
                {"step": step, "phase": "DECISION_BOUND", "decision_id": decision_id},
            )

    def _consume_step(self, db, rid, step, result_json=None):
        """在调用方事务里消费当前步骤；重复相同结果幂等，冲突或未准入步骤拒绝。

        先核对步骤存在和当前序号，再更新 DONE。否则 UPDATE 影响零行时也可能
        继续写消息/事件/游标，制造不存在的进度；重复回调还会覆盖已经完成的证据。
        """
        row = db.execute(
            "SELECT s.state,s.result_json,t.current_step FROM workspace_steps s "
            "JOIN workspace_turns t ON t.run_id=s.run_id WHERE s.run_id=? AND s.step=?",
            (rid, step),
        ).fetchone()
        if row is None:
            raise InvalidTransition("step has not been admitted")
        if row["state"] == "DONE":
            if row["result_json"] != result_json:
                raise IdentityConflict("completed step cannot accept a different result")
            return False
        if row["current_step"] != step:
            raise InvalidTransition("only the current step can be consumed")
        db.execute(
            "UPDATE workspace_steps SET state='DONE',result_json=? WHERE run_id=? AND step=?",
            (result_json, rid, step),
        )
        return True

    # 原子记入工具结果与步骤完成事实；相同结果重试不重复事件，也不回退游标。
    def finish_tool(self, rid, step, result):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            if not self._consume_step(db, rid, step, canonical_json(result)):
                return
            self._checkpoint(
                db,
                rid,
                step,
                "TOOL_RECORDED",
                checkpoint_step=step,
                detail=result.get("capability_id") or "tool",
            )
            tool_event = {"step": step, "capability": result.get("capability_id")}
            fused = result.get("fused_successor")
            if isinstance(fused, dict):
                tool_event["fused_successor"] = {
                    "kind": fused.get("kind"),
                    "status": fused.get("status"),
                    "reason_code": fused.get("reason_code"),
                }
            self.store._event(
                db,
                rid,
                "ConversationToolRecorded",
                tool_event,
            )
            self.store._event(
                db,
                rid,
                "ExecutionCheckpoint",
                {"step": step, "phase": "TOOL_RECORDED", "checkpoint_step": step},
            )

    # 原子记入非工具 Observation；失败/Stop Guard 反馈被消费，但不冒充 Tool Receipt。
    def finish_observation(self, rid, step, result):
        with self.store.tx() as db:
            if not self._consume_step(db, rid, step, canonical_json(result)):
                return
            kind = str(result.get("observation_kind") or "observation")
            self._checkpoint(
                db,
                rid,
                step,
                "OBSERVATION_RECORDED",
                checkpoint_step=step,
                detail=kind,
            )
            self.store._event(
                db,
                rid,
                "ConversationObservationRecorded",
                {
                    "step": step,
                    "kind": kind,
                    "failure_code": ((result.get("failure") or {}).get("code")),
                },
            )
            self.store._event(
                db,
                rid,
                "ExecutionCheckpoint",
                {"step": step, "phase": "OBSERVATION_RECORDED", "checkpoint_step": step},
            )


    # 把回答/问题、步骤状态及游标一起提交；普通 COMPLETED 只表示对话回答已结束。
    def finish_reply(self, rid, step, text, question_id=None):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            turn = self.turn(rid)
            if turn["status"] != "RUNNING":
                return
            status = "WAITING_USER" if question_id else "COMPLETED"
            if not self._consume_step(db, rid, step):
                return
            self._message(
                db,
                turn["session_id"],
                rid,
                "assistant",
                text,
                {
                    "kind": "question" if question_id else "answer",
                    "citations": turn["snapshot"]["knowledge"],
                    "execution_verified": False,
                },
            )
            if question_id:
                snapshot = turn["snapshot"]
                snapshot["messages"].append({"role": "assistant", "content": text})
                db.execute(
                    "UPDATE workspace_turns SET snapshot_json=? WHERE run_id=?",
                    (canonical_json(snapshot), rid),
                )
            _write_turn_status(db, rid, turn["status"], status, question_id=question_id)
            db.execute(
                "UPDATE runs SET state=? WHERE run_id=?",
                ("WAITING" if question_id else "SUCCEEDED", rid),
            )
            db.execute(
                "UPDATE workspace_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (turn["session_id"],),
            )
            self._checkpoint(
                db,
                rid,
                step,
                "WAITING_USER" if question_id else "COMPLETED",
                checkpoint_step=step,
                recovery_state="WAIT_USER" if question_id else "NONE",
                detail=(
                    "Waiting for user input"
                    if question_id
                    else "Conversation answer persisted"
                ),
            )
            self.store._event(
                db,
                rid,
                "ConversationAnswered",
                {"semantic_verification": "not_claimed", "question_id": question_id},
            )
            self.store._event(
                db,
                rid,
                "ExecutionCheckpoint",
                {
                    "step": step,
                    "phase": "WAITING_USER" if question_id else "COMPLETED",
                    "checkpoint_step": step,
                },
            )

    # 校验待答问题身份并消费明确用户回答；不同问题不能相互代答。
    def answer(self, rid, text, question_id):
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text.encode("utf-8")) > 16000
        ):
            raise ValueError("invalid answer")
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            turn = self.turn(rid)
            if turn["status"] != "WAITING_USER" or turn["question_id"] != question_id:
                raise ValueError("answer must match current question")
            self._message(db, turn["session_id"], rid, "user", text, {})
            snapshot = turn["snapshot"]
            snapshot["messages"].append({"role": "user", "content": text})
            require_transition(turn["status"], "RUNNING")
            db.execute(
                "UPDATE workspace_turns SET status='RUNNING',question_id=NULL,error=NULL,snapshot_json=? WHERE run_id=?",
                (canonical_json(snapshot), rid),
            )
            db.execute("UPDATE runs SET state='RUNNING' WHERE run_id=?", (rid,))
            self._checkpoint(
                db,
                rid,
                turn["current_step"],
                "USER_ANSWERED",
                checkpoint_step=turn["current_step"],
                detail="User answer persisted",
            )

    def control_target(self, db, rid):
        """向控制协调器提供最小 Turn 数据；不加载历史消息、知识正文、步骤或对象文件。"""
        with self.store.transaction_scope(db):
            row = db.execute(
                "SELECT status,settings_json,snapshot_json,question_id,current_step "
                "FROM workspace_turns WHERE run_id=?", (rid,)
            ).fetchone()
            if row is None:
                raise KeyError(rid)
            return {
                "status": row["status"], "settings": json.loads(row["settings_json"]),
                "snapshot": json.loads(row["snapshot_json"]), "question_id": row["question_id"],
                "current_step": row["current_step"],
            }

    def apply_control(self, db, rid, control: ControlSnapshot, *, command=None):
        """在 Control 的提交事务内更新本仓储状态，并请 Core/Goal 所有者加入。

        控制只阻止后续准入，已获 Ticket 的机会照常留收据。暂停待答问题时保留
        WAITING_USER；Resume 不能替用户回答，也不能把未决效果当作可重放。
        """
        turn = self.control_target(db, rid)
        if not is_active(turn["status"]):
            return None
        if command in {ControlCommand.SWITCH_MODEL, ControlCommand.SWITCH_THINKING}:
            settings = turn["settings"]
            settings.update(model=control.model, thinking=control.thinking)
            db.execute("UPDATE workspace_turns SET settings_json=? WHERE run_id=?", (canonical_json(settings), rid))

        if control.stopped:
            self.block(rid, "CANCELLED", "用户已终止本轮。已获 Ticket 的调用仍会保留真实晚到结果。", _db=db)
            status = "CANCELLED"
        elif control.paused and is_pausable(turn["status"]):
            _write_turn_status(db, rid, turn["status"], "PAUSED")
            self.store.project_control(db, rid, state="PAUSED")
            self.store._event(db, rid, "RunPaused", {"revision": control.revision, "safe_point": True})
            status = "PAUSED"
        elif command is ControlCommand.RESUME and turn["status"] == "PAUSED":
            # Resume 只重新允许驱动；ConversationAgent 在任何新派发前必须先 recover，未知效果仍不重发。
            status = "RUNNING"
            _write_turn_status(db, rid, turn["status"], status)
            self.store.project_control(db, rid, state="RUNNING")
            self.store._event(db, rid, "RunResumed", {"revision": control.revision})
        else:
            status = turn["status"]

        if command in {ControlCommand.PAUSE, ControlCommand.RESUME, ControlCommand.STOP}:
            goal_id = (turn["snapshot"].get("goal") or {}).get("goal_id")
            if goal_id and self.personal is not None:
                self.personal.checkpoint_run(
                    goal_id, rid, status="PAUSED" if control.paused else status,
                    summary=f"Control action applied: {command.value}.",
                    waiting_for=(turn["snapshot"].get("messages") or [{}])[-1].get("content", "")
                    if status == "WAITING_USER" else "", _db=db,
                )
        return "CANCELLED" if control.stopped else "PAUSED" if control.paused else None

    # 持久记录阻塞/结束状态及原因；_db 可加入控制事务，不抹掉凭证与晚到收据。
    def block(self, rid, status, reason, *, _db=None):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.transaction_scope(_db) as db:
            turn = self.turn(rid)
            if not is_active(turn["status"]):
                return
            if status in {"UNKNOWN", "CANCELLED"}:
                for op in self.pending_operations(rid):
                    if op["state"] != "TICKETED":
                        continue
                    for meter, cost in {
                        "tool_calls": 1,
                        "write_bytes": op["reserved_bytes"],
                    }.items():
                        db.execute(
                            "UPDATE accounts SET reserved=reserved-?,unknown_held=unknown_held+? WHERE run_id=? AND meter=?",
                            (cost, cost, rid, meter),
                        )
                    db.execute(
                        "UPDATE workspace_operations SET state='UNKNOWN' WHERE decision_id=?",
                        (op["decision_id"],),
                    )
            _write_turn_status(db, rid, turn["status"], status, error=reason)
            if status in {"FAILED", "CANCELLED", "BUDGET_EXHAUSTED", "COMPLETED"}:
                db.execute("DELETE FROM workspace_network_retries WHERE run_id=?", (rid,))
            self.store.project_control(db, rid, state="RECOVERING" if status == "UNKNOWN" else status,
                                       advance_revision=True)
            recovery = "RECONCILE" if status == "UNKNOWN" else "NONE"
            self._checkpoint(
                db,
                rid,
                turn["current_step"],
                status,
                checkpoint_step=max(
                    [
                        int(item["step"])
                        for item in turn["activities"]
                        if item["state"] == "DONE"
                    ]
                    or [0]
                ),
                recovery_state=recovery,
                detail=reason,
            )
            self.store._event(
                db, rid, "ConversationBlocked", {"status": status, "reason": reason}
            )

    # 按当前持久状态重新进入驱动；恢复核对由执行端口负责，不凭重开动作重发未知效果。
    def reopen(self, rid):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            turn = self.turn(rid)
            if not is_drivable(turn["status"]):
                return
            _write_turn_status(db, rid, turn["status"], "RUNNING")
            db.execute("UPDATE runs SET state='RUNNING' WHERE run_id=?", (rid,))
            self._checkpoint(
                db,
                rid,
                turn["current_step"],
                "RESUMED",
                checkpoint_step=max(
                    [
                        int(item["step"])
                        for item in turn["activities"]
                        if item["state"] == "DONE"
                    ]
                    or [0]
                ),
                recovery_state="NONE",
                detail="Run resumed from durable checkpoint",
                record_progress=not bool(turn.get("network_retry")),
            )
            self.store._event(
                db, rid, "ConversationResumed", {"step": turn["current_step"]}
            )

    # 取得 decision_id 的工具机会；相同决定恢复必须复用这条记录。
    def operation(self, decision_id):
        row = self.store.db.execute(
            "SELECT * FROM workspace_operations WHERE decision_id=?", (decision_id,)
        ).fetchone()
        return (
            None
            if not row
            else {
                **dict(row),
                "intent": json.loads(row["intent_json"]),
                "result": (
                    json.loads(row["result_json"]) if row["result_json"] else None
                ),
            }
        )

    # 同事务登记工具意图、资源预留与唯一 Ticket；外部文件/Git 效果随后才发生。
    def start_operation(self, rid, decision_id, capability, intent):
        with self.store.tx() as db:
            self._start_operation(db, rid, decision_id, capability, intent)
        return self.operation(decision_id)

    def _start_operation(self, db, rid, decision_id, capability, intent, *, owner_decision_id=None):
        """仅供仓储同事务协调；批量子 Ticket 的权限来自已核对的父模型决定。"""
        old = self.operation(decision_id)
        if old:
            return old
        if self.turn(rid)["status"] != "RUNNING":
            raise ValueError("turn stopped")
        if capability == "agent.evaluate":
            # 一个子任务只接受一次主评分；与 Ticket 同事务检查，重启/并发不能重复训练。
            target = intent["result"]["review"]["delegation_id"]
            if db.execute(
                "SELECT 1 FROM workspace_operations WHERE run_id=? AND capability='agent.evaluate' "
                "AND json_extract(intent_json,'$.result.review.delegation_id')=?", (rid, target)
            ).fetchone():
                raise ValueError("子任务已经评分，不可重复记录")
        if capability == "agent.resolve":
            target = intent["result"]["resolution"]["delegation_id"]
            if db.execute(
                "SELECT 1 FROM workspace_operations WHERE run_id=? AND capability='agent.resolve' "
                "AND json_extract(intent_json,'$.result.resolution.delegation_id')=?", (rid, target)
            ).fetchone():
                raise ValueError("子任务已有主模型替代内容，不可重复补做记录")
        owner = db.execute(
            "SELECT run_id FROM step_decisions WHERE decision_id=?", (owner_decision_id or decision_id,)
        ).fetchone()
        if not owner or owner[0] != rid:
            raise ValueError("decision belongs to another turn")
        amount = intent.get("write_bytes", 0)
        for meter, cost in {"tool_calls": 1, "write_bytes": amount}.items():
            changed = db.execute(
                "UPDATE accounts SET reserved=reserved+? WHERE run_id=? AND meter=? AND limit_units-settled-reserved-unknown_held>=?",
                (cost, rid, meter, cost),
            )
            if not changed.rowcount:
                raise BudgetExceeded(f"insufficient {meter}")
        db.execute(
            "INSERT INTO workspace_operations(decision_id,run_id,capability,state,intent_json,ticket_id,reserved_bytes) VALUES(?,?,?,'TICKETED',?,?,?)",
            (
                decision_id,
                rid,
                capability,
                canonical_json(intent),
                new_id("ctkt"),
                amount,
            ),
        )
        self._checkpoint(
            db,
            rid,
            self.turn(rid)["current_step"],
            "TOOL_TICKETED",
            checkpoint_step=max(0, self.turn(rid)["current_step"] - 1),
            detail=capability,
        )
        self.store._event(
            db,
            rid,
            "ConversationToolTicket",
            {"decision_id": decision_id, "capability": capability},
        )

    def start_parallel(self, rid, decision_id, contracts, fallbacks):
        """一次短事务准入父批次及全部子 Ticket；额度不足整体回滚，任何子模型尚未派发。"""
        with self.store.tx() as db:
            old = self.operation(decision_id)
            if old:
                return old
            intent = {"write_bytes": 0, "requires_receipt": True,
                      "parallel": contracts, "fallbacks": fallbacks}
            self._start_operation(db, rid, decision_id, "agent.parallel", intent)
            for contract in contracts:
                self._start_operation(db, rid, contract["delegation_id"], "agent.delegate",
                    {"write_bytes": 0, "requires_receipt": True, "delegate": contract},
                    owner_decision_id=decision_id)
        return self.operation(decision_id)

    # 以已发布收据原子完成工具记录和计量；记录晚到结果，不抹去先前 Stop/Pause。
    def settle_operation(self, decision_id, result, *, tool_wall_ms=None):
        # 本地事务边界：下列写入一起提交，异常整体回滚；文件/网络效果须在事务外另行核对。
        with self.store.tx() as db:
            op = self.operation(decision_id)
            if op["state"] == "RESOLVED":
                return op["result"]
            if "result" in op["intent"] and result != op["intent"]["result"]:
                raise IdentityConflict("tool result differs from admitted intent")
            if "result" not in op["intent"] and not op["intent"].get("requires_receipt"):
                raise IdentityConflict("dynamic tool result requires an explicit receipt contract")
            liability = "unknown_held" if op["state"] == "UNKNOWN" else "reserved"
            for meter, cost in {
                "tool_calls": 1,
                "write_bytes": op["reserved_bytes"],
            }.items():
                db.execute(
                    f"UPDATE accounts SET {liability}={liability}-?,settled=settled+? WHERE run_id=? AND meter=?",
                    (cost, cost, op["run_id"], meter),
                )
            db.execute(
                "UPDATE workspace_operations SET state='RESOLVED',result_json=?,tool_wall_ms=? WHERE decision_id=?",
                (canonical_json(result), measured_integer(tool_wall_ms), decision_id),
            )
            turn = self.turn(op["run_id"])
            self._checkpoint(
                db,
                op["run_id"],
                turn["current_step"],
                "TOOL_SETTLED",
                checkpoint_step=turn["current_step"],
                detail=op["capability"],
            )
        return result

    # 列出仍待核对的工具机会；定时器不得绕过它创建替代工作。
    def pending_operations(self, rid):
        return [
            self.operation(r[0])
            for r in self.store.db.execute(
                "SELECT decision_id FROM workspace_operations WHERE run_id=? AND state IN ('TICKETED','UNKNOWN')",
                (rid,),
            )
        ]

    # 按 Run 读取工具状态与参数/结果投影；用于观测，不再次派发。
    def operations(self, rid):
        rows = self.store.db.execute(
            "SELECT decision_id FROM workspace_operations WHERE run_id=? ORDER BY rowid",
            (rid,),
        ).fetchall()
        return [self.operation(r[0]) for r in rows]

    # 读取 Run 持久有序事件供 Runtime 面板展示；页面刷新不会生成执行效果。
    def events(self, rid):
        result = []
        for row in self.store.db.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY sequence", (rid,)
        ).fetchall():
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    # 从已结算工具结果投影会话产物；下载按固定对象摘要读取，避免受管文件后续版本串台。
    def artifacts(self, sid):
        results = []
        versions = {}
        for r in self.store.db.execute(
            "SELECT o.result_json,t.run_id FROM workspace_operations o JOIN workspace_turns t USING(run_id) WHERE t.session_id=? AND o.state='RESOLVED'",
            (sid,),
        ):
            value = json.loads(r[0])
            if value.get("artifact"):
                artifact = value["artifact"]
                versions[artifact["name"]] = versions.get(artifact["name"], 0) + 1
                results.append(
                    {**artifact, "run_id": r[1], "version": versions[artifact["name"]]}
                )
        return results
