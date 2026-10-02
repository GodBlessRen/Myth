"""HTTP 工作区门面：Conversation、Control、Memory 和 Runtime facts 的产品 API。"""

from __future__ import annotations

import threading

from .runtime import MythRuntime
from .workspace import Workspace
from .providers import create_provider
from .providers.ollama import OllamaProvider
from .platform.control import ControlCommand
from .strategies import RuleIntentPicker


class ConversationWebService:
    def __init__(self,root):
        self.root=root
        self.active=set()
        self.lock=threading.Lock()

    def _use(self,method,*args):
        with MythRuntime(self.root) as runtime:
            return getattr(Workspace(runtime).repository,method)(*args)

    def platform(self):
        with MythRuntime(self.root) as runtime:
            workspace=Workspace(runtime)
            value=workspace.components.snapshot()
            value["active_policy"]=workspace.evolution.active("information_resolution")
            value["policy_history"]=workspace.evolution.history("information_resolution",10)
            return value

    def memories(self,query="",kind=None,limit=50):
        with MythRuntime(self.root) as runtime:
            memory=Workspace(runtime).memory
            if query:
                kinds=[kind] if kind else None
                return memory.search(query,kinds=kinds,limit=min(int(limit),20))
            values=memory.list(active_only=True,limit=min(int(limit),100))
            return [item for item in values if not kind or item["kind"]==kind]

    def bootstrap(self):
        return {
            "projects":self._use("projects"),
            "sessions":self._use("sessions"),
            "settings":self._use("settings"),
            "documents":self._use("documents"),
            "platform":self.platform(),
            "memory_count":len(self.memories(limit=100)),
            "goals":self.goals(),
            "goal_count":len(self.goals()),
        }

    @staticmethod
    def provider(settings):
        return create_provider(
            settings["provider"],
            ollama_base_url=settings.get("ollama_url"),
        )

    def connection(self,payload=None):
        settings=payload or self._use("settings")
        provider=(
            OllamaProvider(settings.get("ollama_url","http://127.0.0.1:11434"),timeout=5)
            if settings.get("provider","ollama")=="ollama"
            else self.provider(settings)
        )
        status=provider.check()
        return {
            "ready":status.ready,
            "provider":status.provider_id,
            "details":status.details or {},
        }

    def session(self,sid):
        with MythRuntime(self.root) as runtime:
            workspace=Workspace(runtime)
            value=workspace.repository.session(sid)
            with self.lock:
                active=set(self.active)
            for turn in value["turns"]:
                turn["driver_active"]=turn["run_id"] in active
                turn["control"]=workspace.control.view(turn["run_id"])
                turn["operations"]=workspace.repository.operations(turn["run_id"])
                turn["events"]=workspace.repository.events(turn["run_id"])
                goal_id=(turn.get("snapshot") or {}).get("goal",{}).get("goal_id")
                turn["goal_current"]=workspace.personal.goal_view(goal_id) if goal_id else None
            value["artifacts"]=workspace.repository.artifacts(sid)
            return value

    def _spawn(self,rid):
        with self.lock:
            if rid in self.active:return
            self.active.add(rid)
        def work():
            try:
                with MythRuntime(self.root) as runtime:
                    workspace=Workspace(runtime)
                    turn=workspace.repository.turn(rid)
                    settings=turn["settings"]
                    workspace.run(rid,self.provider(settings))
            except Exception as exc:
                with MythRuntime(self.root) as runtime:
                    Workspace(runtime).repository.block(
                        rid,"UNKNOWN",f"{type(exc).__name__}: {exc}"
                    )
            finally:
                with self.lock:self.active.discard(rid)
        threading.Thread(target=work,name=f"chat-{rid[:12]}",daemon=True).start()

    def send(self,sid,value):
        settings=self._use("settings")
        text=value.get("text")
        goal_id=value.get("goal_id") or None
        pick=RuleIntentPicker().pick(str(text or ""), {})
        if pick.route.value!="deterministic":
            check=self.connection(settings)
            if not check["ready"]:
                raise ValueError("模型服务未连接，请在设置中检查模型连接。")
            if settings["provider"]=="ollama" and settings["model"] not in check["details"].get("models",[]):
                raise ValueError("所选模型未安装，请选择已有 Ollama 模型。")

        with MythRuntime(self.root) as runtime:
            workspace=Workspace(runtime)
            # Admission validates the long-lived Goal before any Run/Turn exists.
            # Request identity also binds goal_id so idempotent retries cannot
            # silently attach the same request to a different Goal.
            goal_context=None
            if goal_id:
                goal_context=workspace.personal.goal_view(goal_id)
            session=workspace.repository.session(sid)
            memory=workspace.memory.search(
                str(text or ""),
                limit=6,
                project_id=session.get("project_id"),
                session_id=sid,
            )
            turn=workspace.repository.create_turn(
                sid,
                text,
                value.get("request_id"),
                value.get("document_ids"),
                memory_records=memory,
                goal_id=goal_id,
                goal_context=goal_context,
            )
            workspace.control.ensure(turn["run_id"],turn["settings"])
            if goal_id:
                workspace.personal.bind_run(goal_id,turn["run_id"])
                workspace.personal.checkpoint_run(
                    goal_id,
                    turn["run_id"],
                    status="RUNNING",
                    summary="A new admitted Turn has started for this Goal.",
                    next_action="Let the current Turn reach a durable checkpoint.",
                )
        if turn["status"]=="RUNNING":self._spawn(turn["run_id"])
        return {"run_id":turn["run_id"],"session_id":sid}

    def control(self,rid,action,value):
        if action=="answer":
            self._use("answer",rid,value.get("text"),value.get("question_id"))
            self._spawn(rid)
            return {"run_id":rid,"status":"RUNNING"}

        if action=="continue":
            if self._use("turn",rid)["status"] not in {"RUNNING","UNKNOWN"}:
                raise ValueError("turn cannot continue")
            self._spawn(rid)
            return {"run_id":rid,"status":"RUNNING"}

        mapping={
            "pause":ControlCommand.PAUSE,
            "resume":ControlCommand.RESUME,
            "stop":ControlCommand.STOP,
            "abort":ControlCommand.STOP,
            "cancel":ControlCommand.STOP,
            "steer":ControlCommand.STEER,
            "switch_model":ControlCommand.SWITCH_MODEL,
            "switch_thinking":ControlCommand.SWITCH_THINKING,
            "compact":ControlCommand.COMPACT,
        }
        if action not in mapping:raise ValueError("unsupported control")

        if action=="steer":payload=value.get("text")
        elif action=="switch_model":payload=value.get("model")
        elif action=="switch_thinking":payload=value.get("thinking")
        else:payload=None

        with MythRuntime(self.root) as runtime:
            workspace=Workspace(runtime)
            projection=workspace.control.command(rid,mapping[action],payload)
            turn=workspace.repository.turn(rid)

        if action=="resume":
            self._spawn(rid)
        elif action in {"steer","switch_model","switch_thinking","compact"} and turn["status"]=="RUNNING":
            self._spawn(rid)

        return {"run_id":rid,"status":turn["status"],"control":projection}

    def remember(self,value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).memory.remember(
                kind=value.get("kind","semantic"),
                text=value.get("text",""),
                source_ref=value.get("source_ref") or "user",
            )

    def goals(self,include_archived=False):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.goal_views(include_archived=include_archived)

    def create_goal(self,value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.create_goal(
                value.get("title",""),
                value.get("description",""),
            )

    def goal_triggers(self,goal_id):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.triggers(goal_id)

    def goal_runs(self,goal_id):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.runs(goal_id)

    def goal(self,goal_id):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.goal_view(goal_id)

    def update_goal_work(self,goal_id,value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.update_work_state(
                goal_id,
                current_state=value.get("current_state"),
                next_action=value.get("next_action"),
                waiting_for=value.get("waiting_for"),
                progress_note=value.get("progress_note"),
            )

    def add_goal_trigger(self,goal_id,value):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.add_trigger(
                goal_id,
                value.get("kind","user"),
                value.get("spec") or {},
            )

    def personal_state(self):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).personal.state()

    def set_personal_state(self,value):
        key=value.get("key","")
        with MythRuntime(self.root) as runtime:
            workspace=Workspace(runtime)
            workspace.personal.set_state(key,value.get("value"))
            return {"key":key,"value":workspace.personal.state().get(key)}

    def revoke_memory(self,memory_id):
        with MythRuntime(self.root) as runtime:
            return Workspace(runtime).memory.revoke(memory_id)

    def project_files(self,pid,path="."):
        with MythRuntime(self.root) as runtime:
            workspace=Workspace(runtime)
            return workspace.execution.list_project(
                {"snapshot":{"project":workspace.repository.project(pid)}},
                path,
            )

    def artifact(self,decision_id):
        with MythRuntime(self.root) as runtime:
            repository=Workspace(runtime).repository
            op=repository.operation(decision_id)
            if not op or op["state"]!="RESOLVED" or not op["result"].get("artifact"):
                raise KeyError(decision_id)
            artifact=op["result"]["artifact"]
            return artifact["name"],runtime.objects.get(artifact["digest"])

    def export(self,kind,identity):
        with MythRuntime(self.root) as runtime:
            repository=Workspace(runtime).repository
            if kind=="messages":
                row=runtime.store.db.execute(
                    "SELECT role,content FROM workspace_messages WHERE id=?",(identity,)
                ).fetchone()
                if not row or row["role"]!="assistant":raise KeyError(identity)
                return "myth-answer.md",row["content"].encode("utf-8")
            session=repository.session(identity)
            text="# "+session["title"]+"\n\n"+"\n\n---\n\n".join(
                "## "+("你" if m["role"]=="user" else "Myth")+"\n\n"+m["content"]
                for m in session["messages"]
            )
            return "myth-conversation.md",text.encode("utf-8")

    def get(self,parts,query):
        if not parts:return self.bootstrap()
        if parts==["platform"]:return self.platform()
        if parts==["connection"]:return self.connection()
        if parts==["memories"]:
            return {"memories":self.memories(
                query.get("q",[""])[0],
                query.get("kind",[None])[0],
                int(query.get("limit",["50"])[0]),
            )}
        if parts==["goals"]:
            return {"goals":self.goals(query.get("archived",["0"])[0]=="1")}
        if len(parts)==2 and parts[0]=="goals":
            return self.goal(parts[1])
        if len(parts)==3 and parts[0]=="goals" and parts[2]=="triggers":
            return {"triggers":self.goal_triggers(parts[1])}
        if len(parts)==3 and parts[0]=="goals" and parts[2]=="runs":
            return {"runs":self.goal_runs(parts[1])}
        if parts==["personal-state"]:
            return {"state":self.personal_state()}
        if parts==["sessions"]:
            return {"sessions":self._use("sessions",query.get("archived",["0"])[0]=="1")}
        if len(parts)==2 and parts[0]=="sessions":return self.session(parts[1])
        if len(parts)==2 and parts[0]=="documents":return self._use("document",parts[1])
        if parts==["search"]:
            return self._use(
                "search_report",
                query.get("q",[""])[0],
                query.get("project_id",[None])[0],
            )
        if len(parts)==3 and parts[0]=="projects" and parts[2]=="files":
            return self.project_files(parts[1],query.get("path",["."])[0])
        raise KeyError("endpoint")

    def post(self,parts,value):
        if parts==["settings"]:return self._use("save_settings",value)
        if parts==["connection"]:return self.connection(value)
        if parts==["memories"]:return self.remember(value)
        if parts==["goals"]:return self.create_goal(value)
        if len(parts)==3 and parts[0]=="goals" and parts[2]=="triggers":
            return self.add_goal_trigger(parts[1],value)
        if len(parts)==3 and parts[0]=="goals" and parts[2]=="work":
            return self.update_goal_work(parts[1],value)
        if parts==["personal-state"]:return self.set_personal_state(value)
        if len(parts)==3 and parts[0]=="memories" and parts[2]=="revoke":
            return self.revoke_memory(parts[1])
        if parts==["projects"]:return self._use("create_project",value)
        if len(parts)==2 and parts[0]=="projects":return self._use("update_project",parts[1],value)
        if parts==["sessions"]:
            return self._use("create_session",value.get("title","新对话"),value.get("project_id"))
        if len(parts)==2 and parts[0]=="sessions":return self._use("update_session",parts[1],value)
        if len(parts)==3 and parts[0]=="sessions" and parts[2]=="messages":return self.send(parts[1],value)
        if parts==["documents"]:return self._use("import_document",value)
        if len(parts)==3 and parts[0]=="documents" and parts[2]=="archive":
            return self._use("archive_document",parts[1])
        if len(parts)==3 and parts[0]=="turns":return self.control(parts[1],parts[2],value)
        raise KeyError("endpoint")
