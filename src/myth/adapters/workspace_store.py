"""工作区持久适配器：项目、会话、消息、知识与对话执行状态的原子所有者。"""
from __future__ import annotations
import json
import uuid
from ..conversation import chunks, rank_chunks
from ..domain import canonical_json, digest_json, IdentityConflict, BudgetExceeded
from ..decision_runtime import DecisionRuntime

SCHEMA="""
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
CREATE TABLE IF NOT EXISTS workspace_documents(
 id TEXT PRIMARY KEY,project_id TEXT REFERENCES workspace_projects(id),title TEXT NOT NULL,
 digest TEXT NOT NULL,bytes INTEGER NOT NULL,archived INTEGER NOT NULL DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS workspace_chunks(
 document_id TEXT REFERENCES workspace_documents(id),chunk_index INTEGER,content TEXT NOT NULL,
 PRIMARY KEY(document_id,chunk_index));
CREATE TABLE IF NOT EXISTS workspace_settings(id INTEGER PRIMARY KEY CHECK(id=1),value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_operations(
 decision_id TEXT PRIMARY KEY,run_id TEXT REFERENCES workspace_turns(run_id),capability TEXT NOT NULL,
 state TEXT NOT NULL,intent_json TEXT NOT NULL,result_json TEXT,ticket_id TEXT UNIQUE,
 reserved_bytes INTEGER NOT NULL DEFAULT 0);
"""


def new_id(prefix):return f"{prefix}_{uuid.uuid4().hex}"


ACTIVE_TURN_STATUSES = {"RUNNING", "UNKNOWN", "WAITING_USER", "PAUSED"}


class SqliteWorkspaceRepository:
    def __init__(self,runtime):
        self.runtime=runtime
        self.store=runtime.store
        self.decisions=DecisionRuntime(runtime)
        self.store.db.executescript(SCHEMA)

    def settings(self):
        row=self.store.db.execute("SELECT value_json FROM workspace_settings WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {"provider":"ollama","model":"","ollama_url":"http://127.0.0.1:11434","max_steps":12,"max_output_tokens":2048,"thinking":False}

    def save_settings(self,value):
        provider=value.get("provider","ollama")
        if provider not in {"ollama","openai","pi-openai"}:raise ValueError("unsupported model provider")
        from urllib.parse import urlparse
        endpoint=str(value.get("ollama_url","http://127.0.0.1:11434")).rstrip("/")
        parsed=urlparse(endpoint)
        if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username:raise ValueError("invalid model endpoint")
        model=str(value.get("model","")).strip()
        if len(model)>200:raise ValueError("model name too long")
        steps=value.get("max_steps",12);tokens=value.get("max_output_tokens",2048)
        if type(steps) is not int or not 2<=steps<=32 or type(tokens) is not int or not 128<=tokens<=8192:raise ValueError("invalid step or token limit")
        if type(value.get("thinking",False)) is not bool:raise ValueError("thinking must be boolean")
        clean={"provider":provider,"model":model,"ollama_url":endpoint,"max_steps":steps,"max_output_tokens":tokens,"thinking":value.get("thinking",False)}
        with self.store.tx() as db:db.execute("INSERT INTO workspace_settings VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value_json=excluded.value_json",(canonical_json(clean),))
        return clean

    def projects(self):
        return [dict(r) for r in self.store.db.execute("SELECT p.*,(SELECT count(*) FROM workspace_sessions s WHERE s.project_id=p.id AND s.archived=0) session_count,(SELECT count(*) FROM workspace_documents d WHERE d.project_id=p.id AND d.archived=0) document_count FROM workspace_projects p WHERE p.archived=0 ORDER BY p.rowid DESC")]

    def project(self,pid):
        row=self.store.db.execute("SELECT * FROM workspace_projects WHERE id=? AND archived=0",(pid,)).fetchone()
        if not row:raise KeyError(pid)
        return dict(row)

    def create_project(self,value):
        name=str(value.get("name","")).strip()
        if not name or len(name)>100:raise ValueError("project name must contain 1-100 characters")
        root=value.get("root") or None
        if root:
            from pathlib import Path
            path=Path(root).expanduser().resolve()
            if not path.is_dir():raise ValueError("project directory does not exist")
            root=str(path)
        pid=new_id("project")
        with self.store.tx() as db:db.execute("INSERT INTO workspace_projects(id,name,description,instructions,root) VALUES(?,?,?,?,?)",(pid,name,str(value.get("description","")).strip()[:1000],str(value.get("instructions","")).strip()[:12000],root))
        return self.project(pid)

    def update_project(self,pid,value):
        old=self.project(pid)
        if "name" in value and not str(value["name"]).strip():raise ValueError("name is required")
        root=value.get("root",old["root"]) or None
        if root:
            from pathlib import Path
            path=Path(root).expanduser().resolve()
            if not path.is_dir():raise ValueError("project directory does not exist")
            root=str(path)
        with self.store.tx() as db:
            db.execute("UPDATE workspace_projects SET name=?,description=?,instructions=?,root=?,archived=? WHERE id=?",(str(value.get("name",old["name"])).strip()[:100],str(value.get("description",old["description"]))[:1000],str(value.get("instructions",old["instructions"]))[:12000],root,int(bool(value.get("archived",False))),pid))
        return {"id":pid}

    def sessions(self,archived=False):
        return [dict(r) for r in self.store.db.execute("SELECT s.*,p.name project_name,(SELECT content FROM workspace_messages m WHERE m.session_id=s.id ORDER BY m.rowid DESC LIMIT 1) preview FROM workspace_sessions s LEFT JOIN workspace_projects p ON p.id=s.project_id WHERE s.archived=? ORDER BY pinned DESC,s.updated_at DESC,s.rowid DESC",(int(archived),))]

    def create_session(self,title="新对话",project_id=None):
        if project_id:self.project(project_id)
        sid=new_id("session")
        with self.store.tx() as db:db.execute("INSERT INTO workspace_sessions(id,title,project_id) VALUES(?,?,?)",(sid,str(title).strip()[:100] or "新对话",project_id))
        return self.session(sid)

    def session(self,sid):
        row=self.store.db.execute("SELECT s.*,p.name project_name FROM workspace_sessions s LEFT JOIN workspace_projects p ON p.id=s.project_id WHERE s.id=?",(sid,)).fetchone()
        if not row:raise KeyError(sid)
        result=dict(row)
        result["messages"]=[{**dict(r),"metadata":json.loads(r["metadata_json"])} for r in self.store.db.execute("SELECT * FROM workspace_messages WHERE session_id=? ORDER BY rowid",(sid,))]
        result["turns"]=[self.turn(r[0]) for r in self.store.db.execute("SELECT run_id FROM workspace_turns WHERE session_id=? ORDER BY rowid",(sid,))]
        return result

    def update_session(self,sid,value):
        old=self.session(sid)
        if any(t["status"] in ACTIVE_TURN_STATUSES for t in old["turns"]) and value.get("archived"):raise ValueError("stop the active turn before archiving")
        pid=value.get("project_id",old["project_id"])
        if pid:self.project(pid)
        with self.store.tx() as db:db.execute("UPDATE workspace_sessions SET title=?,project_id=?,pinned=?,archived=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(str(value.get("title",old["title"])).strip()[:100] or "新对话",pid,int(bool(value.get("pinned",old["pinned"]))),int(bool(value.get("archived",old["archived"]))),sid))
        return self.session(sid)

    def documents(self,project_id=None):
        return [dict(r) for r in self.store.db.execute("SELECT d.*,p.name project_name,(SELECT count(*) FROM workspace_chunks c WHERE c.document_id=d.id) chunks FROM workspace_documents d LEFT JOIN workspace_projects p ON p.id=d.project_id WHERE d.archived=0 ORDER BY d.rowid DESC") if project_id is None or r["project_id"]==project_id]

    def import_document(self,value):
        title=str(value.get("title","")).strip();text=value.get("content","")
        if not title or len(title)>200 or not isinstance(text,str) or not text.strip() or len(text.encode("utf-8"))>1_000_000:raise ValueError("document requires title and UTF-8 text up to 1 MB")
        pid=value.get("project_id") or None
        if pid:self.project(pid)
        digest=self.runtime.objects.put(text.encode("utf-8"));did=new_id("doc")
        with self.store.tx() as db:
            db.execute("INSERT INTO workspace_documents(id,project_id,title,digest,bytes) VALUES(?,?,?,?,?)",(did,pid,title,digest,len(text.encode("utf-8"))))
            db.executemany("INSERT INTO workspace_chunks VALUES(?,?,?)",[(did,i,part) for i,part in enumerate(chunks(text))])
        return {"id":did,"title":title,"digest":digest,"chunks":len(chunks(text))}

    def document(self,did):
        row=self.store.db.execute("SELECT * FROM workspace_documents WHERE id=?",(did,)).fetchone()
        if not row:raise KeyError(did)
        return {**dict(row),"content":self.runtime.objects.get(row["digest"]).decode("utf-8")}

    def archive_document(self,did):
        self.document(did)
        with self.store.tx() as db:db.execute("UPDATE workspace_documents SET archived=1 WHERE id=?",(did,))
        return {"id":did}

    def search(self,query,project_id=None,limit=5):
        if not isinstance(query,str) or len(query)>1000:raise ValueError("query up to 1000 characters")
        if type(limit) is not int or not 1<=limit<=8:raise ValueError("limit must be 1-8")
        rows=self.store.db.execute("SELECT c.*,d.title,d.digest FROM workspace_chunks c JOIN workspace_documents d ON d.id=c.document_id WHERE d.archived=0 AND (d.project_id IS NULL OR d.project_id=?) LIMIT 10000",(project_id,)).fetchall()
        return rank_chunks(query,[dict(r) for r in rows],limit)

    def create_turn(self,sid,text,request_id,document_ids=None,memory_records=None):
        if not isinstance(text,str) or not text.strip() or len(text.encode("utf-8"))>16000:raise ValueError("message must contain 1-16000 UTF-8 bytes")
        if not isinstance(request_id,str) or not 1<=len(request_id)<=200:raise ValueError("request_id is required")
        settings=self.settings()
        if not settings["model"]:raise ValueError("请先在模型设置中选择 Ollama 模型。")
        document_ids=document_ids or []
        memory_records=memory_records or []
        if not isinstance(document_ids,list) or len(document_ids)>4 or any(not isinstance(d,str) for d in document_ids):raise ValueError("attach at most four document ids")
        # Request identity binds caller intent + fixed user-selected settings/attachments.
        # Retrieved Memory is an execution snapshot derived after admission; changing
        # ambient memory must not break idempotent retries of the same request_id.
        identity=digest_json({"session_id":sid,"text":text,"settings":settings,"documents":document_ids})
        with self.store.tx() as db:
            existing=db.execute("SELECT run_id,entry_digest FROM workspace_turns WHERE request_id=?",(request_id,)).fetchone()
            if existing:
                if existing["entry_digest"]!=identity:raise IdentityConflict("request_id reused with different message or settings")
                return self.turn(existing["run_id"])
            session=self.session(sid)
            if session["archived"]:raise ValueError("restore the archived conversation first")
            if any(t["status"] in ACTIVE_TURN_STATUSES for t in session["turns"]):raise ValueError("本会话仍有未完成一轮，请先继续、答复或停止。")
            project=self.project(session["project_id"]) if session["project_id"] else None
            knowledge=self.search(text,session["project_id"])
            for did in document_ids:
                document=self.document(did)
                if document["archived"]:raise ValueError("attachment was removed from the retrieval index")
                if document["project_id"] not in {None,session["project_id"]}:raise PermissionError("attachment belongs to another project")
                if not any(s["document_id"]==did for s in knowledge):
                    knowledge.append({"document_id":did,"title":document["title"],"content":document["content"][:1000],"chunk_index":0,"digest":document["digest"],"citation":f"doc:{did}:0","score":0})
            snapshot={
                "project":project,
                "knowledge":knowledge,
                "attached_document_ids":list(document_ids),
                "turn_message_start":min(30,len(session["messages"])),
                "memory":[
                    {
                        "memory_id":m.get("memory_id"),
                        "kind":m.get("kind"),
                        "text":m.get("text",""),
                        "source_ref":m.get("source_ref"),
                        "revision":m.get("revision"),
                    }
                    for m in memory_records[:8]
                ],
                "messages":[{"role":m["role"],"content":m["content"]} for m in session["messages"][-30:]]+[{"role":"user","content":text}],
            }
            rid=new_id("run")
            db.execute("INSERT INTO runs(run_id,request_id,entry_digest,goal,acceptance_version,state) VALUES(?,?,?,?,?,'RUNNING')",(rid,request_id,identity,text,"conversation-v1"))
            for meter,limit in {"model_calls":settings["max_steps"],"input_tokens":2_000_000,"output_tokens":settings["max_steps"]*settings["max_output_tokens"],"tool_calls":settings["max_steps"],"write_bytes":4_000_000}.items():db.execute("INSERT INTO accounts(run_id,meter,limit_units) VALUES(?,?,?)",(rid,meter,limit))
            db.execute("INSERT INTO workspace_turns(run_id,session_id,request_id,entry_digest,settings_json,snapshot_json,status,max_steps) VALUES(?,?,?,?,?,?,'RUNNING',?)",(rid,sid,request_id,identity,canonical_json(settings),canonical_json(snapshot),settings["max_steps"]))
            self._message(db,sid,rid,"user",text,{})
            db.execute("UPDATE workspace_sessions SET title=CASE WHEN title='新对话' THEN ? ELSE title END,updated_at=CURRENT_TIMESTAMP WHERE id=?",(text[:40],sid))
            self.store._event(db,rid,"ConversationTurnStarted",{"session_id":sid})
        return self.turn(rid)

    def _message(self,db,sid,rid,role,text,metadata):
        db.execute("INSERT INTO workspace_messages(id,session_id,run_id,role,content,metadata_json) VALUES(?,?,?,?,?,?)",(new_id("msg"),sid,rid,role,text,canonical_json(metadata)))

    def turn(self,rid):
        row=self.store.db.execute("SELECT * FROM workspace_turns WHERE run_id=?",(rid,)).fetchone()
        if not row:raise KeyError(rid)
        result=dict(row);result["settings"]=json.loads(result.pop("settings_json"));result["snapshot"]=json.loads(result.pop("snapshot_json"))
        if "turn_message_start" not in result["snapshot"]:
            # Legacy snapshots contain recent history followed by this turn's
            # task/questions/answers. Infer the boundary without rewriting DBs.
            count=self.store.db.execute("SELECT count(*) FROM workspace_messages WHERE run_id=?",(rid,)).fetchone()[0]
            result["snapshot"]["turn_message_start"]=max(0,len(result["snapshot"]["messages"])-count)
        result["activities"]=[{**dict(r),"decision":json.loads(r["decision_json"]) if r["decision_json"] else None,"result":json.loads(r["result_json"]) if r["result_json"] else None} for r in self.store.db.execute("SELECT * FROM workspace_steps WHERE run_id=? ORDER BY step",(rid,))]
        result["budgets"]=self.store.get_accounts(rid)
        return result

    def begin_step(self,rid):
        with self.store.tx() as db:
            turn=self.turn(rid)
            if turn["status"]!="RUNNING":return None
            unfinished=next((s for s in turn["activities"] if s["state"]!="DONE"),None)
            if unfinished:return unfinished
            number=turn["current_step"]+1
            if number>turn["max_steps"]:return None
            db.execute("INSERT INTO workspace_steps(run_id,step,state) VALUES(?,?,'STARTED')",(rid,number))
            db.execute("UPDATE workspace_turns SET current_step=? WHERE run_id=?",(number,rid))
            return {"step":number}

    def bind(self,rid,step,decision_id,decision):
        with self.store.tx() as db:db.execute("UPDATE workspace_steps SET state='DECIDED',decision_id=?,decision_json=? WHERE run_id=? AND step=?",(decision_id,canonical_json(decision.serializable()),rid,step))

    def finish_tool(self,rid,step,result):
        with self.store.tx() as db:
            db.execute("UPDATE workspace_steps SET state='DONE',result_json=? WHERE run_id=? AND step=?",(canonical_json(result),rid,step))
            self.store._event(db,rid,"ConversationToolRecorded",{"step":step,"capability":result.get("capability_id")})

    def reject(self,rid,step,reason):self.finish_tool(rid,step,{"error":reason})

    def finish_reply(self,rid,step,text,question_id=None):
        with self.store.tx() as db:
            turn=self.turn(rid)
            if turn["status"]!="RUNNING":return
            status="WAITING_USER" if question_id else "COMPLETED"
            db.execute("UPDATE workspace_steps SET state='DONE' WHERE run_id=? AND step=?",(rid,step))
            self._message(db,turn["session_id"],rid,"assistant",text,{"kind":"question" if question_id else "answer","citations":turn["snapshot"]["knowledge"],"execution_verified":False})
            if question_id:
                snapshot=turn["snapshot"];snapshot["messages"].append({"role":"assistant","content":text})
                db.execute("UPDATE workspace_turns SET snapshot_json=? WHERE run_id=?",(canonical_json(snapshot),rid))
            db.execute("UPDATE workspace_turns SET status=?,question_id=?,error=NULL WHERE run_id=?",(status,question_id,rid))
            db.execute("UPDATE runs SET state=? WHERE run_id=?",("WAITING" if question_id else "SUCCEEDED",rid))
            db.execute("UPDATE workspace_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(turn["session_id"],))
            self.store._event(db,rid,"ConversationAnswered",{"semantic_verification":"not_claimed","question_id":question_id})

    def answer(self,rid,text,question_id):
        if not isinstance(text,str) or not text.strip() or len(text.encode("utf-8"))>16000:raise ValueError("invalid answer")
        with self.store.tx() as db:
            turn=self.turn(rid)
            if turn["status"]!="WAITING_USER" or turn["question_id"]!=question_id:raise ValueError("answer must match current question")
            self._message(db,turn["session_id"],rid,"user",text,{})
            snapshot=turn["snapshot"];snapshot["messages"].append({"role":"user","content":text})
            db.execute("UPDATE workspace_turns SET status='RUNNING',question_id=NULL,snapshot_json=? WHERE run_id=?",(canonical_json(snapshot),rid))
            db.execute("UPDATE runs SET state='RUNNING' WHERE run_id=?",(rid,))

    def block(self,rid,status,reason):
        with self.store.tx() as db:
            if self.turn(rid)["status"] not in {"RUNNING","UNKNOWN","WAITING_USER","PAUSED"}:return
            if status in {"UNKNOWN","CANCELLED"}:
                for op in self.pending_operations(rid):
                    if op["state"]!="TICKETED":continue
                    for meter,cost in {"tool_calls":1,"write_bytes":op["reserved_bytes"]}.items():
                        db.execute("UPDATE accounts SET reserved=reserved-?,unknown_held=unknown_held+? WHERE run_id=? AND meter=?",(cost,cost,rid,meter))
                    db.execute("UPDATE workspace_operations SET state='UNKNOWN' WHERE decision_id=?",(op["decision_id"],))
            db.execute("UPDATE workspace_turns SET status=?,error=? WHERE run_id=?",(status,reason,rid))
            db.execute("UPDATE runs SET state=?,control_revision=control_revision+1 WHERE run_id=?",("RECOVERING" if status=="UNKNOWN" else status,rid))
            self.store._event(db,rid,"ConversationBlocked",{"status":status,"reason":reason})

    def reopen(self,rid):
        with self.store.tx() as db:
            if self.turn(rid)["status"] not in {"UNKNOWN","RUNNING"}:return
            db.execute("UPDATE workspace_turns SET status='RUNNING',error=NULL WHERE run_id=?",(rid,))
            db.execute("UPDATE runs SET state='RUNNING' WHERE run_id=?",(rid,))

    def operation(self,decision_id):
        row=self.store.db.execute("SELECT * FROM workspace_operations WHERE decision_id=?",(decision_id,)).fetchone()
        return None if not row else {**dict(row),"intent":json.loads(row["intent_json"]),"result":json.loads(row["result_json"]) if row["result_json"] else None}

    def start_operation(self,rid,decision_id,capability,intent):
        with self.store.tx() as db:
            old=self.operation(decision_id)
            if old:return old
            if self.turn(rid)["status"]!="RUNNING":raise ValueError("turn stopped")
            owner=db.execute("SELECT run_id FROM step_decisions WHERE decision_id=?",(decision_id,)).fetchone()
            if not owner or owner[0]!=rid:raise ValueError("decision belongs to another turn")
            amount=intent.get("write_bytes",0)
            for meter,cost in {"tool_calls":1,"write_bytes":amount}.items():
                changed=db.execute("UPDATE accounts SET reserved=reserved+? WHERE run_id=? AND meter=? AND limit_units-settled-reserved-unknown_held>=?",(cost,rid,meter,cost))
                if not changed.rowcount:raise BudgetExceeded(f"insufficient {meter}")
            db.execute("INSERT INTO workspace_operations(decision_id,run_id,capability,state,intent_json,ticket_id,reserved_bytes) VALUES(?,?,?,'TICKETED',?,?,?)",(decision_id,rid,capability,canonical_json(intent),new_id("ctkt"),amount))
            self.store._event(db,rid,"ConversationToolTicket",{"decision_id":decision_id,"capability":capability})
        return self.operation(decision_id)

    def settle_operation(self,decision_id,result):
        with self.store.tx() as db:
            op=self.operation(decision_id)
            if op["state"]=="RESOLVED":return op["result"]
            if result!=op["intent"]["result"]:raise IdentityConflict("tool result differs from admitted intent")
            liability="unknown_held" if op["state"]=="UNKNOWN" else "reserved"
            for meter,cost in {"tool_calls":1,"write_bytes":op["reserved_bytes"]}.items():db.execute(f"UPDATE accounts SET {liability}={liability}-?,settled=settled+? WHERE run_id=? AND meter=?",(cost,cost,op["run_id"],meter))
            db.execute("UPDATE workspace_operations SET state='RESOLVED',result_json=? WHERE decision_id=?",(canonical_json(result),decision_id))
        return result

    def pending_operations(self,rid):
        return [self.operation(r[0]) for r in self.store.db.execute("SELECT decision_id FROM workspace_operations WHERE run_id=? AND state IN ('TICKETED','UNKNOWN')",(rid,))]

    def operations(self,rid):
        rows=self.store.db.execute("SELECT decision_id FROM workspace_operations WHERE run_id=? ORDER BY rowid",(rid,)).fetchall()
        return [self.operation(r[0]) for r in rows]

    def events(self,rid):
        result=[]
        for row in self.store.db.execute("SELECT * FROM events WHERE run_id=? ORDER BY sequence",(rid,)).fetchall():
            item=dict(row);item["payload"]=json.loads(item.pop("payload_json"))
            result.append(item)
        return result

    def artifacts(self,sid):
        results=[];versions={}
        for r in self.store.db.execute("SELECT o.result_json,t.run_id FROM workspace_operations o JOIN workspace_turns t USING(run_id) WHERE t.session_id=? AND o.state='RESOLVED'",(sid,)):
            value=json.loads(r[0])
            if value.get("artifact"):
                artifact=value["artifact"];versions[artifact["name"]]=versions.get(artifact["name"],0)+1
                results.append({**artifact,"run_id":r[1],"version":versions[artifact["name"]]})
        return results
