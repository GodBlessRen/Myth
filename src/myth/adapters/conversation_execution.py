"""对话工具的本机执行适配器。
限定项目读取/搜索、知识展开、Diff、只读 Git 和受管产物；每次真实工具执行以稳定决策身份记录 Ticket/收据，恢复按已有事实核对。"""

from __future__ import annotations

import difflib
import json
from pathlib import Path
import shutil
import subprocess

from ..artifacts import atomic_write
from .driver_lock import local_run_lock
from ..conversation import TOOL_CATALOG, conversation_request, calculate
from ..domain import RecoveryRequired, exact_patch, sha256_bytes
from ..platform.capabilities import CapabilityState, default_capabilities
from ..models import StepDecision
from ..strategies import RuleIntentPicker

# EXCLUDED：项目读取/检索排除项；避免把秘钥、版本库和生成缓存纳入上下文。
EXCLUDED = {
    ".git",
    ".runtime",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".aws",
    ".ssh",
    "secrets",
}
# TEXT_SUFFIXES：项目检索允许的文本后缀；枚举不放开秘钥/符号链接限制。
TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".py",
    ".json",
    ".csv",
    ".yaml",
    ".yml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".toml",
    ".ini",
    ".cfg",
    ".xml",
    ".sh",
    ".ps1",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".h",
    ".cpp",
}


# Conversation 的工具执行器；把模型参数约束为项目范围和受管产物，Ticket/收据以决策身份关联。
class LocalConversationExecution:
    # 连接固定项目范围、工具仓储和收据目录；取锁只依赖独立 driver_lock，不实例化 Exact 用例。
    def __init__(self, runtime, repository, capability_registry=None):
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        # repository：用例仓储端口/实现；持久状态写入归此协作对象所有。
        self.runtime, self.repository = runtime, repository
        # registry：能力/合同目录；注册不是执行授权。
        self.registry = capability_registry or default_capabilities()
        # intent_picker：纯路径选择策略；输出是提案，不改变能力范围。
        self.intent_picker = RuleIntentPicker()
        # receipts：持久效果日志协作对象；不存在日志不自动证明调用未发出。
        self.receipts = runtime.runtime_dir / "conversation-receipts"
        self.receipts.mkdir(exist_ok=True)

    # 取得一个 Run 的本机执行互斥作用域；竞争不表示效果失败，需按恢复事实判断后续。
    def lock(self, rid):
        return local_run_lock(self.runtime.runtime_dir, rid)

    # 首步可消费冻结算术路由，否则按 Turn/step 构造持久模型请求；确定规则失败留回退事件，不改变权限。
    def decide(self, turn, step, provider):
        activities = []
        for item in turn["activities"]:
            if not item.get("decision") and not item.get("result"):
                continue
            decision = item.get("decision") or {}
            result = dict(item.get("result") or {})
            activities.append(
                {
                    "step": item["step"],
                    "decision_id": item.get("decision_id"),
                    "capability": decision.get("capability_id"),
                    "question": decision.get("question"),
                    "result": result,
                }
            )
        if step == 1 and not activities:
            frozen_pick = turn["snapshot"].get("intent_pick") or {}
            metadata = frozen_pick.get("metadata") or {}
            if (
                frozen_pick.get("route") == "deterministic"
                and metadata.get("kind") == "bounded_arithmetic"
            ):
                expression = metadata["expression"]
                try:
                    value = calculate(expression)
                except ValueError as exc:
                    self.repository.record_route_fallback(
                        turn["run_id"],
                        step,
                        "deterministic->agent",
                        str(exc),
                    )
                else:
                    decision_id = f"intent:{turn['run_id']}:{step}:arithmetic"
                    return decision_id, StepDecision(
                        decision_type="request_completion",
                        reason=frozen_pick.get("reason")
                        or "deterministic intent route",
                        claim=str(value),
                        goal_coverage="answer",
                    )

        request = conversation_request(
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

    # 拒绝绝对路径、上跳、驱动器/流、秘钥目录和配置文件；路径校验与实际 resolve 后根范围双重检查。
    @staticmethod
    def relative_path(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise ValueError("relative path is required")
        path = Path(value)
        if (
            path.is_absolute()
            or path.drive
            or ".." in path.parts
            or ":" in value
            or "\x00" in value
            or any(
                p.lower() in EXCLUDED
                or p.lower().startswith(".env")
                or p.lower().endswith((".key", ".pem"))
                for p in path.parts
            )
        ):
            raise PermissionError("path is outside admitted project/output scope")
        return path

    # 将已准入项目根与受限相对路径解析为真实路径；symlink 解析后仍须位于根下。
    def project_path(self, turn, value="."):
        project = turn["snapshot"].get("project") or {}
        if not project.get("root"):
            raise ValueError(
                "本会话没有关联本地项目目录。请在项目页创建项目并选择目录。"
            )
        root = Path(project["root"]).resolve()
        relative = self.relative_path(value)
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise PermissionError("path escapes project root")
        return root, path

    # 列出有界项目条目并跳过禁止路径/符号链接；truncated 明确表示未展示完整目录。
    def list_project(self, turn, value="."):
        root, path = self.project_path(turn, value)
        if not path.is_dir():
            raise ValueError("directory does not exist")
        files = []
        for entry in sorted(
            path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
        ):
            try:
                self.relative_path(str(entry.relative_to(root)))
            except PermissionError:
                continue
            if entry.is_symlink():
                continue
            files.append(
                {
                    "path": str(entry.relative_to(root)).replace("\\", "/"),
                    "type": "directory" if entry.is_dir() else "file",
                    "bytes": entry.stat().st_size if entry.is_file() else None,
                }
            )
            if len(files) >= 150:
                break
        return {"files": files, "truncated": len(files) == 150}

    # 验证知识文档身份及项目作用域；其他项目资料不能借工具展开绕过 admission。
    def _knowledge_document(self, turn, document_id):
        if (
            not isinstance(document_id, str)
            or not document_id.strip()
            or len(document_id) > 200
        ):
            raise ValueError("document_id is required")
        document = self.repository.document(document_id)
        project_id = (turn["snapshot"].get("project") or {}).get("id")
        if document["project_id"] not in {None, project_id}:
            raise PermissionError("knowledge document belongs to another project")
        return document

    # 在同 document/digest 下分页展开 L0/L1/L2；cursor/limit 单位随视图声明，旧 digest 不悄悄变源。
    def _resolve_knowledge(self, turn, args):
        document_id = args.get("document_id")
        document = self._knowledge_document(turn, document_id)
        resolution = str(args.get("resolution") or "L2").upper()
        cursor = args.get("cursor", 0)
        limit = args.get("limit", 6000 if resolution == "L2" else 12)
        if type(cursor) is not int or cursor < 0:
            raise ValueError("cursor must be a non-negative integer")
        source_ref = f"doc:{document_id}@{document['digest']}"
        if resolution == "L0":
            excerpt = document["content"][: min(600, max(120, int(limit) * 40))]
            return {
                "document_id": document_id,
                "title": document["title"],
                "digest": document["digest"],
                "bytes": document["bytes"],
                "content": excerpt,
                "resolution": "L0",
                "source_ref": source_ref,
                "cursor": 0,
                "next_cursor": None,
                "has_more": False,
            }
        if resolution == "L1":
            if type(limit) is not int or not 1 <= limit <= 20:
                raise ValueError("L1 limit must be 1-20 chunks")
            rows = self.repository.store.db.execute(
                "SELECT chunk_index,content FROM workspace_chunks "
                "WHERE document_id=? AND chunk_index>=? ORDER BY chunk_index LIMIT ?",
                (document_id, cursor, limit + 1),
            ).fetchall()
            values = [
                {
                    "chunk_index": int(row["chunk_index"]),
                    "preview": row["content"][:500],
                    "citation": f"doc:{document_id}:{row['chunk_index']}",
                }
                for row in rows[:limit]
            ]
            has_more = len(rows) > limit
            next_cursor = (
                (values[-1]["chunk_index"] + 1) if values and has_more else None
            )
            return {
                "document_id": document_id,
                "title": document["title"],
                "digest": document["digest"],
                "resolution": "L1",
                "source_ref": source_ref,
                "chunks": values,
                "cursor": cursor,
                "next_cursor": next_cursor,
                "has_more": has_more,
            }
        if resolution != "L2":
            raise ValueError("resolution must be L0/L1/L2")
        if type(limit) is not int or not 1 <= limit <= 12000:
            raise ValueError("L2 limit must be 1-12000 characters")
        text = document["content"]
        preview = text[cursor : cursor + limit]
        while len(preview.encode("utf-8")) > 18000:
            preview = preview[: len(preview) // 2]
        return {
            "document_id": document_id,
            "title": document["title"],
            "content": preview,
            "digest": document["digest"],
            "cursor": cursor,
            "next_cursor": (
                cursor + len(preview) if cursor + len(preview) < len(text) else None
            ),
            "has_more": cursor + len(preview) < len(text),
            "resolution": "L2",
            "source_ref": source_ref,
        }

    # 读取该作用域知识文档的 L2 分页证据；固定来源摘要随结果返回。
    def _read_knowledge(self, turn, args):
        value = self._resolve_knowledge(
            turn,
            {
                "document_id": args.get("document_id"),
                "resolution": "L2",
                "cursor": args.get("offset", 0),
                "limit": args.get("max_chars", 6000),
            },
        )
        # 旧 knowledge.read 的 offset/next_offset 保留线协议兼容；新分页仍固定 document/digest 来源。
        return {
            **value,
            "offset": value["cursor"],
            "next_offset": value["next_cursor"],
        }

    # 有界读取 UTF-8 项目文件并记录快照摘要；offset/limit 是 Unicode 字符，不是字节。
    def _read_project(self, turn, args):
        _, path = self.project_path(turn, args.get("path"))
        if not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("file must exist and be <= 1 MB")
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("only UTF-8 text files are supported") from exc
        offset = args.get("offset", 0)
        limit = args.get("max_chars", args.get("limit", 6000))
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 12000
        ):
            raise ValueError("invalid pagination")
        preview = text[offset : offset + limit]
        while len(preview.encode("utf-8")) > 18000:
            preview = preview[: len(preview) // 2]
        digest = self.runtime.objects.put(data)
        return {
            "path": args["path"],
            "content": preview,
            "digest": digest,
            "offset": offset,
            "next_offset": offset + len(preview),
            "has_more": offset + len(preview) < len(text),
        }

    # 在受限根下扫描允许文本候选，排除秘钥/缓存/链接并施加规模上限。
    def _iter_text_files(self, turn, start="."):
        root, path = self.project_path(turn, start)
        if not path.is_dir():
            raise ValueError("search path must be a directory")
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file() or candidate.is_symlink():
                continue
            relative = candidate.relative_to(root)
            try:
                self.relative_path(str(relative))
            except PermissionError:
                continue
            if (
                candidate.suffix.lower() not in TEXT_SUFFIXES
                or candidate.stat().st_size > 512_000
            ):
                continue
            yield root, candidate, relative

    # 在固定项目范围按字面查询分页结果；报告 candidate/cursor/has_more，不能把一个页当作全项目无命中。
    def _search_project(self, turn, args):
        query = str(args.get("query", ""))
        if not query.strip() or len(query) > 300:
            raise ValueError("search query must contain 1-300 characters")
        limit = args.get("limit", 12)
        cursor = args.get("cursor", 0)
        max_files = args.get("max_files", 500)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("limit must be 1-20")
        if type(cursor) is not int or cursor < 0:
            raise ValueError("cursor must be a non-negative integer")
        if type(max_files) is not int or not 1 <= max_files <= 2500:
            raise ValueError("max_files must be 1-2500")
        needle = query.lower()
        matches = []
        matched_count = 0
        eligible_seen = 0
        scanned = 0
        has_more = False
        for root, path, relative in self._iter_text_files(
            turn, args.get("path") or "."
        ):
            if eligible_seen < cursor:
                eligible_seen += 1
                continue
            if scanned >= max_files:
                has_more = True
                break
            eligible_seen += 1
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if needle in line.lower():
                    matched_count += 1
                    if len(matches) < limit:
                        matches.append(
                            {
                                "path": str(relative).replace("\\", "/"),
                                "line": line_no,
                                "preview": line.strip()[:500],
                            }
                        )
        next_cursor = cursor + scanned if has_more else None
        return {
            "matches": matches,
            "scanned_files": scanned,
            "matched_lines": matched_count,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "truncated": has_more or matched_count > len(matches),
        }

    # 对候选文本生成有界 unified diff；只预览，不修改原项目文件。
    def _diff_preview(self, turn, args):
        root, path = self.project_path(turn, args.get("path"))
        if not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("source must exist and be <= 1 MB")
        content = args.get("content")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 1_000_000:
            raise ValueError("content must be UTF-8 text <= 1 MB")
        try:
            before = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("only UTF-8 text files are supported") from exc
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{path.relative_to(root).as_posix()}",
                tofile=f"b/{path.relative_to(root).as_posix()}",
            )
        )
        truncated = len(diff) > 24000
        return {
            "path": path.relative_to(root).as_posix(),
            "diff": diff[:24000],
            "truncated": truncated,
        }

    # 用固定只读 argv 调用 git.status/diff；不接受任意 shell 文本，也不修改仓库。
    def _git(self, turn, kind, args):
        root, _ = self.project_path(turn, ".")
        if shutil.which("git") is None:
            raise ValueError("git executable is not available")
        if not (root / ".git").exists():
            raise ValueError("project root is not a Git repository")
        if kind == "git.status":
            command = ["git", "status", "--short", "--untracked-files=normal"]
        else:
            command = ["git", "diff", "--no-ext-diff"]
            raw = args.get("path")
            if raw:
                relative = self.relative_path(raw)
                command += ["--", relative.as_posix()]
        result = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=8,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError((result.stderr or "git command failed")[:1000])
        output = result.stdout
        return {
            "output": output[:24000],
            "truncated": len(output) > 24000,
            "command": (
                " ".join(command[:3]) + " …" if len(command) > 3 else " ".join(command)
            ),
        }

    # 把合法相对输出路径映射到受管产物目录；输出路径不能覆盖项目源文件。
    def _output_target(self, sid, value):
        relative = self.relative_path(value)
        root = (self.runtime.runtime_dir / "session-outputs" / sid).resolve()
        target = (root / relative).resolve()
        if target == root or not target.is_relative_to(root):
            raise PermissionError("output escapes session scope")
        return target

    # 执行已校验/准入的工作并留下结果证据；已存在稳定绑定时复用事实而非重复效果。
    def execute(self, turn, decision_id, decision):
        saved = self.repository.operation(decision_id)
        if saved:
            if saved["run_id"] != turn["run_id"]:
                raise PermissionError("operation belongs to another turn")
            if saved["state"] == "RESOLVED":
                return saved["result"]
            raise RecoveryRequired(
                "tool Ticket already exists; reconcile receipt before continuing"
            )

        capability = decision.capability_id
        args = decision.arguments or {}
        if capability not in TOOL_CATALOG:
            raise PermissionError("tool is not admitted")
        spec = self.registry.get(capability)
        if spec.state is not CapabilityState.EXECUTABLE:
            raise PermissionError(f"capability is not executable: {capability}")

        result = {"capability_id": capability}
        intent = {"write_bytes": 0}
        if capability == "knowledge.search":
            report = self.repository.search_report(
                args.get("query", ""),
                (turn["snapshot"].get("project") or {}).get("id"),
                args.get("limit", 5),
            )
            result.update(report)
        elif capability == "knowledge.read":
            result.update(self._read_knowledge(turn, args))
        elif capability == "knowledge.resolve":
            result.update(self._resolve_knowledge(turn, args))
        elif capability == "project.list":
            result.update(self.list_project(turn, args.get("path", ".")))
        elif capability == "project.read":
            result.update(self._read_project(turn, args))
        elif capability == "project.search":
            result.update(self._search_project(turn, args))
        elif capability == "diff.preview":
            result.update(self._diff_preview(turn, args))
        elif capability in {"git.status", "git.diff"}:
            result.update(self._git(turn, capability, args))
        elif capability == "math.calculate":
            result["value"] = calculate(args.get("expression"))
        else:
            target = self._output_target(turn["session_id"], args.get("path"))
            if capability == "project.patch_exact":
                _, source = self.project_path(turn, args.get("path"))
                if not source.is_file() or source.stat().st_size > 1_000_000:
                    raise ValueError("source must exist and be <=1MB")
                before = source.read_bytes()
                data = exact_patch(
                    before,
                    args.get("old_text"),
                    args.get("new_text"),
                    args.get("expected_count"),
                ).after
            else:
                content = args.get("content")
                if not isinstance(content, str):
                    raise ValueError("content must be a string")
                data = content.encode("utf-8")
            if len(data) > 1_000_000:
                raise ValueError("output exceeds 1 MB")
            digest = self.runtime.objects.put(data)
            artifact = {
                "name": str(args["path"]).replace("\\", "/"),
                "digest": digest,
                "bytes": len(data),
                "decision_id": decision_id,
            }
            result.update(
                {
                    "artifact": artifact,
                    "evidence_ref": f"artifact:{decision_id}@{digest}",
                    "note": "output copy; original project files unchanged",
                }
            )
            intent.update(
                {"write_bytes": len(data), "target": str(target), "digest": digest}
            )

        intent["result"] = result
        op = self.repository.start_operation(
            turn["run_id"], decision_id, capability, intent
        )
        if intent.get("target"):
            atomic_write(
                Path(intent["target"]), self.runtime.objects.get(intent["digest"])
            )
        atomic_write(
            self.receipts / f"{decision_id}.json",
            json.dumps(
                {
                    "decision_id": decision_id,
                    "ticket_id": op["ticket_id"],
                    "result": result,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        return self.repository.settle_operation(decision_id, result)

    # 用已有请求、Ticket、收据和对象核对执行状态；没有足够事实时保留 UNKNOWN，不盲目重发。
    def recover(self, rid):
        self.repository.decisions.recover(rid)
        models = self.repository.decisions.status(rid)["model_invocations"]
        if any(m["state"] in {"TICKETED", "UNKNOWN"} for m in models):
            return False
        for op in self.repository.pending_operations(rid):
            receipt = self.receipts / f"{op['decision_id']}.json"
            if receipt.is_file():
                value = json.loads(receipt.read_text(encoding="utf-8"))
                if (
                    value["ticket_id"] != op["ticket_id"]
                    or value["decision_id"] != op["decision_id"]
                    or value["result"] != op["intent"]["result"]
                ):
                    raise RecoveryRequired("receipt differs from fixed tool intent")
                result = value["result"]
            elif op["intent"].get("target"):
                target = Path(op["intent"]["target"])
                if (
                    not target.is_file()
                    or sha256_bytes(target.read_bytes()) != op["intent"]["digest"]
                ):
                    return False
                result = op["intent"]["result"]
            else:
                result = op["intent"]["result"]
            self.repository.settle_operation(op["decision_id"], result)
        return True
