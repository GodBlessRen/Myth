"""本地对话执行适配器：项目读取、搜索、Diff、Git 只读检查与受管输出。"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
import shutil
import subprocess

from ..artifacts import atomic_write
from ..adapters.agent_execution import LocalAgentExecution
from ..conversation import TOOL_CATALOG, conversation_request, calculate
from ..domain import RecoveryRequired, exact_patch, sha256_bytes
from ..platform.capabilities import CapabilityState, default_capabilities

EXCLUDED={".git",".runtime",".venv","venv","node_modules","__pycache__",".aws",".ssh","secrets"}
TEXT_SUFFIXES={
    ".txt",".md",".py",".json",".csv",".yaml",".yml",".html",".css",".js",".ts",
    ".tsx",".jsx",".toml",".ini",".cfg",".xml",".sh",".ps1",".go",".rs",".java",".c",".h",".cpp"
}


class LocalConversationExecution:
    def __init__(self,runtime,repository,capability_registry=None):
        self.runtime,self.repository=runtime,repository
        self.registry=capability_registry or default_capabilities()
        self._lock_adapter=LocalAgentExecution(runtime,repository)
        self.receipts=runtime.runtime_dir/"conversation-receipts"
        self.receipts.mkdir(exist_ok=True)

    def lock(self,rid):return self._lock_adapter.lock(rid)

    def decide(self,turn,step,provider):
        activities=[]
        for item in turn["activities"]:
            if not item.get("decision") and not item.get("result"):continue
            decision=item.get("decision") or {}
            result=dict(item.get("result") or {})
            activities.append({
                "step":item["step"],
                "decision_id":item.get("decision_id"),
                "capability":decision.get("capability_id"),
                "question":decision.get("question"),
                "result":result,
            })
        request=conversation_request(
            turn["settings"],
            turn["snapshot"],
            turn["snapshot"]["messages"],
            activities,
            control=turn.get("control"),
        )
        return self.repository.decisions.request_decision(
            run_id=turn["run_id"],
            provider=provider,
            model=turn["settings"]["model"],
            max_output_tokens=turn["settings"]["max_output_tokens"],
            request_key=f"conversation:{turn['run_id']}:{step}",
            model_request_override=request,
        )

    @staticmethod
    def relative_path(value):
        if not isinstance(value,str) or not value.strip() or len(value)>500:
            raise ValueError("relative path is required")
        path=Path(value)
        if (
            path.is_absolute() or path.drive or ".." in path.parts or ":" in value or "\x00" in value
            or any(
                p.lower() in EXCLUDED or p.lower().startswith(".env")
                or p.lower().endswith((".key",".pem"))
                for p in path.parts
            )
        ):
            raise PermissionError("path is outside admitted project/output scope")
        return path

    def project_path(self,turn,value="."):
        project=turn["snapshot"].get("project") or {}
        if not project.get("root"):
            raise ValueError("本会话没有关联本地项目目录。请在项目页创建项目并选择目录。")
        root=Path(project["root"]).resolve();relative=self.relative_path(value)
        path=(root/relative).resolve()
        if not path.is_relative_to(root):raise PermissionError("path escapes project root")
        return root,path

    def list_project(self,turn,value="."):
        root,path=self.project_path(turn,value)
        if not path.is_dir():raise ValueError("directory does not exist")
        files=[]
        for entry in sorted(path.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower())):
            try:self.relative_path(str(entry.relative_to(root)))
            except PermissionError:continue
            if entry.is_symlink():continue
            files.append({
                "path":str(entry.relative_to(root)).replace("\\","/"),
                "type":"directory" if entry.is_dir() else "file",
                "bytes":entry.stat().st_size if entry.is_file() else None,
            })
            if len(files)>=150:break
        return {"files":files,"truncated":len(files)==150}

    def _read_project(self,turn,args):
        _,path=self.project_path(turn,args.get("path"))
        if not path.is_file() or path.stat().st_size>1_000_000:
            raise ValueError("file must exist and be <= 1 MB")
        data=path.read_bytes()
        try:text=data.decode("utf-8")
        except UnicodeDecodeError as exc:raise ValueError("only UTF-8 text files are supported") from exc
        offset=args.get("offset",0);limit=args.get("max_chars",args.get("limit",6000))
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=12000:
            raise ValueError("invalid pagination")
        preview=text[offset:offset+limit]
        while len(preview.encode("utf-8"))>18000:preview=preview[:len(preview)//2]
        digest=self.runtime.objects.put(data)
        return {
            "path":args["path"],"content":preview,"digest":digest,"offset":offset,
            "next_offset":offset+len(preview),"has_more":offset+len(preview)<len(text),
        }

    def _iter_text_files(self,turn,start="."):
        root,path=self.project_path(turn,start)
        if not path.is_dir():raise ValueError("search path must be a directory")
        count=0
        for candidate in sorted(path.rglob("*")):
            if count>=2500:break
            if not candidate.is_file() or candidate.is_symlink():continue
            relative=candidate.relative_to(root)
            try:self.relative_path(str(relative))
            except PermissionError:continue
            if candidate.suffix.lower() not in TEXT_SUFFIXES or candidate.stat().st_size>512_000:
                continue
            count+=1
            yield root,candidate,relative

    def _search_project(self,turn,args):
        query=str(args.get("query",""))
        if not query.strip() or len(query)>300:raise ValueError("search query must contain 1-300 characters")
        limit=args.get("limit",12)
        if type(limit) is not int or not 1<=limit<=20:raise ValueError("limit must be 1-20")
        needle=query.lower()
        matches=[]
        for root,path,relative in self._iter_text_files(turn,args.get("path") or "."):
            try:text=path.read_text(encoding="utf-8")
            except UnicodeDecodeError:continue
            for line_no,line in enumerate(text.splitlines(),1):
                if needle in line.lower():
                    matches.append({
                        "path":str(relative).replace("\\","/"),
                        "line":line_no,
                        "preview":line.strip()[:500],
                    })
                    if len(matches)>=limit:return {"matches":matches,"truncated":True}
        return {"matches":matches,"truncated":False}

    def _diff_preview(self,turn,args):
        root,path=self.project_path(turn,args.get("path"))
        if not path.is_file() or path.stat().st_size>1_000_000:
            raise ValueError("source must exist and be <= 1 MB")
        content=args.get("content")
        if not isinstance(content,str) or len(content.encode("utf-8"))>1_000_000:
            raise ValueError("content must be UTF-8 text <= 1 MB")
        try:before=path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:raise ValueError("only UTF-8 text files are supported") from exc
        diff="".join(difflib.unified_diff(
            before.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"a/{path.relative_to(root).as_posix()}",
            tofile=f"b/{path.relative_to(root).as_posix()}",
        ))
        truncated=len(diff)>24000
        return {"path":path.relative_to(root).as_posix(),"diff":diff[:24000],"truncated":truncated}

    def _git(self,turn,kind,args):
        root,_=self.project_path(turn,".")
        if shutil.which("git") is None:raise ValueError("git executable is not available")
        if not (root/".git").exists():raise ValueError("project root is not a Git repository")
        if kind=="git.status":
            command=["git","status","--short","--untracked-files=normal"]
        else:
            command=["git","diff","--no-ext-diff"]
            raw=args.get("path")
            if raw:
                relative=self.relative_path(raw)
                command+=["--",relative.as_posix()]
        result=subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
        if result.returncode!=0:
            raise ValueError((result.stderr or "git command failed")[:1000])
        output=result.stdout
        return {
            "output":output[:24000],
            "truncated":len(output)>24000,
            "command":" ".join(command[:3])+" …" if len(command)>3 else " ".join(command),
        }

    def _output_target(self,sid,value):
        relative=self.relative_path(value)
        root=(self.runtime.runtime_dir/"session-outputs"/sid).resolve()
        target=(root/relative).resolve()
        if target==root or not target.is_relative_to(root):raise PermissionError("output escapes session scope")
        return target

    def execute(self,turn,decision_id,decision):
        saved=self.repository.operation(decision_id)
        if saved:
            if saved["run_id"]!=turn["run_id"]:raise PermissionError("operation belongs to another turn")
            if saved["state"]=="RESOLVED":return saved["result"]
            raise RecoveryRequired("tool Ticket already exists; reconcile receipt before continuing")

        capability=decision.capability_id;args=decision.arguments or {}
        if capability not in TOOL_CATALOG:raise PermissionError("tool is not admitted")
        spec=self.registry.get(capability)
        if spec.state is not CapabilityState.EXECUTABLE:
            raise PermissionError(f"capability is not executable: {capability}")

        result={"capability_id":capability}
        intent={"write_bytes":0}
        if capability=="knowledge.search":
            result["sources"]=self.repository.search(
                args.get("query",""),
                (turn["snapshot"].get("project") or {}).get("id"),
                args.get("limit",5),
            )
        elif capability=="project.list":
            result.update(self.list_project(turn,args.get("path",".")))
        elif capability=="project.read":
            result.update(self._read_project(turn,args))
        elif capability=="project.search":
            result.update(self._search_project(turn,args))
        elif capability=="diff.preview":
            result.update(self._diff_preview(turn,args))
        elif capability in {"git.status","git.diff"}:
            result.update(self._git(turn,capability,args))
        elif capability=="math.calculate":
            result["value"]=calculate(args.get("expression"))
        else:
            target=self._output_target(turn["session_id"],args.get("path"))
            if capability=="project.patch_exact":
                _,source=self.project_path(turn,args.get("path"))
                if not source.is_file() or source.stat().st_size>1_000_000:
                    raise ValueError("source must exist and be <=1MB")
                before=source.read_bytes()
                data=exact_patch(
                    before,
                    args.get("old_text"),
                    args.get("new_text"),
                    args.get("expected_count"),
                ).after
            else:
                content=args.get("content")
                if not isinstance(content,str):raise ValueError("content must be a string")
                data=content.encode("utf-8")
            if len(data)>1_000_000:raise ValueError("output exceeds 1 MB")
            digest=self.runtime.objects.put(data)
            artifact={
                "name":str(args["path"]).replace("\\","/"),
                "digest":digest,
                "bytes":len(data),
                "decision_id":decision_id,
            }
            result.update({
                "artifact":artifact,
                "evidence_ref":f"artifact:{decision_id}@{digest}",
                "note":"output copy; original project files unchanged",
            })
            intent.update({"write_bytes":len(data),"target":str(target),"digest":digest})

        intent["result"]=result
        op=self.repository.start_operation(turn["run_id"],decision_id,capability,intent)
        if intent.get("target"):
            atomic_write(Path(intent["target"]),self.runtime.objects.get(intent["digest"]))
        atomic_write(
            self.receipts/f"{decision_id}.json",
            json.dumps(
                {"decision_id":decision_id,"ticket_id":op["ticket_id"],"result":result},
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        return self.repository.settle_operation(decision_id,result)

    def recover(self,rid):
        self.repository.decisions.recover(rid)
        models=self.repository.decisions.status(rid)["model_invocations"]
        if any(m["state"] in {"TICKETED","UNKNOWN"} for m in models):return False
        for op in self.repository.pending_operations(rid):
            receipt=self.receipts/f"{op['decision_id']}.json"
            if receipt.is_file():
                value=json.loads(receipt.read_text(encoding="utf-8"))
                if (
                    value["ticket_id"]!=op["ticket_id"]
                    or value["decision_id"]!=op["decision_id"]
                    or value["result"]!=op["intent"]["result"]
                ):
                    raise RecoveryRequired("receipt differs from fixed tool intent")
                result=value["result"]
            elif op["intent"].get("target"):
                target=Path(op["intent"]["target"])
                if not target.is_file() or sha256_bytes(target.read_bytes())!=op["intent"]["digest"]:
                    return False
                result=op["intent"]["result"]
            else:
                result=op["intent"]["result"]
            self.repository.settle_operation(op["decision_id"],result)
        return True
