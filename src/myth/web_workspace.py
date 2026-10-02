"""HTTP 的工作区门面；每次调用拥有独立连接，后台推进通用对话。"""
from __future__ import annotations
import threading
from .runtime import MythRuntime
from .workspace import Workspace
from .providers import create_provider
from .providers.ollama import OllamaProvider


class ConversationWebService:
    def __init__(self,root):
        self.root=root
        self.active=set()
        self.lock=threading.Lock()

    def _use(self,method,*args):
        with MythRuntime(self.root) as runtime:return getattr(Workspace(runtime).repository,method)(*args)

    def platform(self):
        with MythRuntime(self.root) as runtime:return Workspace(runtime).kernel.snapshot()

    def bootstrap(self):
        return {
            "projects":self._use("projects"),
            "sessions":self._use("sessions"),
            "settings":self._use("settings"),
            "documents":self._use("documents"),
            "platform":self.platform(),
        }

    @staticmethod
    def provider(settings):return create_provider(settings["provider"],ollama_base_url=settings.get("ollama_url"))

    def connection(self,payload=None):
        settings=payload or self._use("settings")
        provider=OllamaProvider(settings.get("ollama_url","http://127.0.0.1:11434"),timeout=5) if settings.get("provider","ollama")=="ollama" else self.provider(settings)
        status=provider.check()
        return {"ready":status.ready,"provider":status.provider_id,"details":status.details or {}}

    def session(self,sid):
        value=self._use("session",sid)
        with self.lock:
            for turn in value["turns"]:turn["driver_active"]=turn["run_id"] in self.active
        value["artifacts"]=self._use("artifacts",sid)
        return value

    def _spawn(self,rid):
        with self.lock:
            if rid in self.active:return
            self.active.add(rid)
        def work():
            try:
                with MythRuntime(self.root) as runtime:
                    workspace=Workspace(runtime)
                    settings=workspace.repository.turn(rid)["settings"]
                    workspace.run(rid,self.provider(settings))
            except Exception as exc:
                with MythRuntime(self.root) as runtime:Workspace(runtime).repository.block(rid,"UNKNOWN",f"{type(exc).__name__}: {exc}")
            finally:
                with self.lock:self.active.discard(rid)
        threading.Thread(target=work,name=f"chat-{rid[:12]}",daemon=True).start()

    def send(self,sid,value):
        settings=self._use("settings")
        check=self.connection(settings)
        if not check["ready"]:raise ValueError("模型服务未连接，请在设置中检查 Ollama 地址与模型。")
        if settings["provider"]=="ollama" and settings["model"] not in check["details"].get("models",[]):raise ValueError("所选模型未安装，请选择已有 Ollama 模型。")
        turn=self._use("create_turn",sid,value.get("text"),value.get("request_id"),value.get("document_ids"))
        if turn["status"]=="RUNNING":self._spawn(turn["run_id"])
        return {"run_id":turn["run_id"],"session_id":sid}

    def control(self,rid,action,value):
        if action=="cancel":self._use("block",rid,"CANCELLED","本轮已停止。已开始的调用仍保留实际结果。")
        elif action=="answer":
            self._use("answer",rid,value.get("text"),value.get("question_id"));self._spawn(rid)
        elif action=="continue":
            if self._use("turn",rid)["status"] not in {"RUNNING","UNKNOWN"}:raise ValueError("turn cannot continue")
            self._spawn(rid)
        else:raise ValueError("unsupported control")
        return {"run_id":rid}

    def project_files(self,pid,path="."):
        with MythRuntime(self.root) as runtime:
            workspace=Workspace(runtime)
            return workspace.execution.list_project({"snapshot":{"project":workspace.repository.project(pid)}},path)

    def artifact(self,decision_id):
        with MythRuntime(self.root) as runtime:
            repository=Workspace(runtime).repository
            op=repository.operation(decision_id)
            if not op or op["state"]!="RESOLVED" or not op["result"].get("artifact"):raise KeyError(decision_id)
            artifact=op["result"]["artifact"]
            return artifact["name"],runtime.objects.get(artifact["digest"])

    def export(self,kind,identity):
        with MythRuntime(self.root) as runtime:
            repository=Workspace(runtime).repository
            if kind=="messages":
                row=runtime.store.db.execute("SELECT role,content FROM workspace_messages WHERE id=?",(identity,)).fetchone()
                if not row or row["role"]!="assistant":raise KeyError(identity)
                return "myth-answer.md",row["content"].encode("utf-8")
            session=repository.session(identity)
            text="# "+session["title"]+"\n\n"+"\n\n---\n\n".join("## "+("你" if m["role"]=="user" else "Myth")+"\n\n"+m["content"] for m in session["messages"])
            return "myth-conversation.md",text.encode("utf-8")

    def get(self,parts,query):
        if not parts:return self.bootstrap()
        if parts==["platform"]:return self.platform()
        if parts==["connection"]:return self.connection()
        if parts==["sessions"]:return {"sessions":self._use("sessions",query.get("archived",["0"])[0]=="1")}
        if len(parts)==2 and parts[0]=="sessions":return self.session(parts[1])
        if len(parts)==2 and parts[0]=="documents":return self._use("document",parts[1])
        if parts==["search"]:return {"sources":self._use("search",query.get("q",[""])[0],query.get("project_id",[None])[0])}
        if len(parts)==3 and parts[0]=="projects" and parts[2]=="files":return self.project_files(parts[1],query.get("path",["."])[0])
        raise KeyError("endpoint")

    def post(self,parts,value):
        if parts==["settings"]:return self._use("save_settings",value)
        if parts==["connection"]:return self.connection(value)
        if parts==["projects"]:return self._use("create_project",value)
        if len(parts)==2 and parts[0]=="projects":return self._use("update_project",parts[1],value)
        if parts==["sessions"]:return self._use("create_session",value.get("title","新对话"),value.get("project_id"))
        if len(parts)==2 and parts[0]=="sessions":return self._use("update_session",parts[1],value)
        if len(parts)==3 and parts[0]=="sessions" and parts[2]=="messages":return self.send(parts[1],value)
        if parts==["documents"]:return self._use("import_document",value)
        if len(parts)==3 and parts[0]=="documents" and parts[2]=="archive":return self._use("archive_document",parts[1])
        if len(parts)==3 and parts[0]=="turns":return self.control(parts[1],parts[2],value)
        raise KeyError("endpoint")
