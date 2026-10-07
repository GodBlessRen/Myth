"""对话工具的本机执行适配器。
限定项目读取/搜索、知识展开、Diff、只读 Git 和受管产物；每次真实工具执行以稳定决策身份记录 Ticket/收据，恢复按已有事实核对。"""

from __future__ import annotations

import difflib
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from ..artifacts import atomic_write
from .driver_lock import local_run_lock
from ..conversation import TOOL_CATALOG, conversation_request, calculate, validate_tool_arguments
from ..domain import BudgetExceeded, RecoveryRequired, canonical_json, exact_patch, sha256_bytes
from ..platform.capabilities import CapabilityState, default_capabilities
from ..models import ModelMessage, ModelRequest, StepDecision, ProviderKnownFailure
from ..platform.subagents import default_subagents
from ..platform.tool_discovery import describe_tool, search_tools, visible_tool_ids
from ..strategies import LiveInformationController, RuleIntentPicker
from ..verification import SqliteVerificationProfiles
from ..failures import failure_result, observe_failure
from ..extension_ports import SkillLibrary, MCPGateway
from ..tool_hooks import ToolHookContext, ToolHookDenied, ToolHookRegistry, dispatch_tool_hooks, readonly_json
from .delegation import DelegationCoordinator
from .parallel_delegation import ParallelDelegation

# EXCLUDED：项目读取/检索排除项；避免把秘钥、版本库和生成缓存纳入上下文。
EXCLUDED = {
    ".git",
    ".runtime",
    ".trash",
    ".work",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".aws",
    ".ssh",
    ".codex",
    ".myth",
    ".config",
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
    def __init__(
        self,
        runtime,
        repository,
        capability_registry=None,
        subagent_registry=None,
        information_controller=None,
        memory_store=None,
        provider_factory=None,
        parent_control=None,
        skill_library: SkillLibrary | None = None,
        mcp_gateway: MCPGateway | None = None,
        tool_hooks: ToolHookRegistry | None = None,
    ):
        # runtime：共享 Runtime 装配对象；其 SQLite 连接只在所属线程使用。
        # repository：用例仓储端口/实现；持久状态写入归此协作对象所有。
        self.runtime, self.repository = runtime, repository
        # registry：能力/合同目录；注册不是执行授权。
        self.registry = capability_registry or default_capabilities()
        # subagents：子角色合同目录；角色存在不授予工具或写入权限。
        self.subagents = subagent_registry or default_subagents()
        # provider_factory：装配根提供的模型配置解析端口；执行器不读取凭据或导入具体厂商。
        self.provider_factory = provider_factory
        # parent_control：子流程共享父 Pause/Stop/Compact 的唯一状态所有者。
        self.parent_control = parent_control
        # delegation：拥有委派/交接/评审协调，避免在工具执行器重复 Agent 引擎。
        self.delegation = DelegationCoordinator(self)
        # parallel：有界 fork/join；工作线程各自装配连接，父游标等待整批固定结果。
        self.parallel = ParallelDelegation(self)
        # intent_picker：纯路径选择策略；输出是提案，不改变能力范围。
        self.intent_picker = RuleIntentPicker()
        # information_controller：实时信息准入策略；只控制已有读取/检索工具，不执行 I/O 或持有新状态。
        self.information_controller = information_controller or LiveInformationController()
        # memory_store：Memory 的权威读取协作者；渐进披露工具只读，不授予执行权限。
        self.memory_store = memory_store
        # skills/mcp：装配根注入的扩展端口；资源目录和远端发现不能修改 Runtime 执行白名单。
        # skills：只读流程资源端口；内容进入 Observation，但不改变 Capability。
        self.skills = skill_library
        # mcp：远端工具协作端口；准备与真实 invoke 由 Ticket 边界分隔。
        self.mcp = mcp_gateway
        # tool_hooks：只拥有回调目录；执行身份、Ticket、收据与审计写入仍归仓储。
        self.tool_hooks = tool_hooks if tool_hooks is not None else ToolHookRegistry()
        # verification：显式受信项目的固定 Python unittest profile；不提供任意 shell。
        self.verification = SqliteVerificationProfiles(runtime, repository)
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

        from ..platform.handoff import project_handoffs
        activities = project_handoffs(activities)
        snapshot = dict(turn["snapshot"])
        snapshot["model_pool_feedback"] = self.repository.model_feedback()[:20]
        # 复用上一真实模型请求的 Context mode 作为滞回事实；只影响本次投影选择，不倒写 Turn Snapshot。
        previous_context = next(
            (
                event.get("payload") or {}
                for event in reversed(self.repository.events(turn["run_id"]))
                if event.get("kind") == "ConversationContextCompiled"
            ),
            None,
        )
        if isinstance(previous_context, dict) and previous_context.get("context_mode"):
            snapshot["previous_context_mode"] = previous_context["context_mode"]
        if getattr(self.repository, "sota_route", None) is not None:
            # 实时偏离只影响下一步提示，不改变冻结比较身份、权限或预算。
            view = self.repository.sota_route.view(turn["run_id"])
            snapshot["sota_route_live"] = {
                "drift": view.get("drift", False),
                "drift_reasons": view.get("drift_reasons") or [],
                "metrics": view.get("metrics") or {},
                "champion_costs": view.get("champion_costs") or {},
            }
        request = conversation_request(
            turn["settings"],
            snapshot,
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
        # 再检查解析后的真实相对路径：普通别名不能绕过 .env/认证目录的黑名单。
        self.relative_path(str(path.relative_to(root)))
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
        document = self.repository.knowledge.document(document_id)
        project_id = (turn["snapshot"].get("project") or {}).get("id")
        if document["project_id"] not in {None, project_id}:
            raise PermissionError("knowledge document belongs to another project")
        return document

    # 在同 document/digest 下分页展开 L0/L1/L2；cursor/limit 单位随视图声明，旧 digest 不悄悄变源。
    def _resolve_knowledge(self, turn, args):
        # 先核对文档作用域和固定摘要，再按 L0/L1/L2 的单位分页；L2 同时限制字符和 UTF-8 字节。
        document_id = args.get("document_id")
        document = self._knowledge_document(turn, document_id)
        resolution = str(args.get("resolution") or "L2").upper()
        cursor = args.get("cursor", 0)
        limit = args.get("limit", 6000 if resolution == "L2" else 12)
        if type(cursor) is not int or cursor < 0:
            raise ValueError("cursor must be a non-negative integer")
        source_ref = f"doc:{document_id}@{document['digest']}"
        if resolution == "L0":
            if cursor != 0 or type(limit) is not int or not 1 <= limit <= 20:
                raise ValueError("L0 cursor must be 0 and limit must be 1-20 preview units")
            excerpt = document["content"][: min(600, max(120, limit * 40))]
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
            return {
                "document_id": document_id,
                "title": document["title"],
                "digest": document["digest"],
                "resolution": "L1",
                "source_ref": source_ref,
                **self.repository.knowledge.chunk_page(document_id, cursor=cursor, limit=limit),
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

    # 从当前 Run 的已结算 Tool Operation 精确回读字段；分页只改变投影，不重跑工具或重新总结。
    def _read_observation(self, turn, args):
        decision_id = str(args.get("decision_id") or "").strip()
        field = str(args.get("field") or "").strip()
        if not decision_id or len(decision_id) > 200:
            raise ValueError("observation.read decision_id is required")
        if field not in {"content", "output", "diff", "stdout", "stderr", "summary"}:
            raise ValueError("observation.read field is not recallable")
        saved = self.repository.operation(decision_id)
        if not saved or saved.get("run_id") != turn["run_id"]:
            raise PermissionError("observation belongs to another turn or is unavailable")
        if saved.get("state") != "RESOLVED":
            raise RecoveryRequired("observation is not durably resolved")
        result = saved.get("result") if isinstance(saved.get("result"), dict) else {}
        value = result.get(field)
        if not isinstance(value, str):
            raise ValueError("requested observation field is not text")
        offset = args.get("offset", 0)
        limit = args.get("max_chars", 6000)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12000:
            raise ValueError("invalid observation pagination")
        preview = value[offset : offset + limit]
        digest = sha256_bytes(value.encode("utf-8"))
        return {
            "decision_id": decision_id,
            "field": field,
            "content": preview,
            "source_digest": digest,
            "source_chars": len(value),
            "offset": offset,
            "next_offset": offset + len(preview) if offset + len(preview) < len(value) else None,
            "has_more": offset + len(preview) < len(value),
            "source_ref": f"observation:{decision_id}:{field}@{digest}",
            "projection": "exact-recall",
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
        # 逐目录排序与剪枝，不能先展开 node_modules/.git 的整棵树再套 max_files。
        visited = 0
        for directory, dirs, names in os.walk(path, followlinks=False):
            allowed_dirs = []
            for name in sorted(dirs):
                entry = Path(directory) / name
                try:
                    self.project_path(turn, str(entry.relative_to(root)))
                except PermissionError:
                    continue
                if not entry.is_symlink() and not entry.is_junction():
                    allowed_dirs.append(name)
            dirs[:] = allowed_dirs
            visited += len(dirs) + len(names)
            if visited > 50000:
                raise ValueError("project search exceeds the entry limit; narrow the search path")
            for name in sorted(names):
                candidate = Path(directory) / name
                if candidate.is_symlink() or candidate.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                relative = candidate.relative_to(root)
                try:
                    self.project_path(turn, str(relative))
                except PermissionError:
                    continue
                if candidate.is_file() and candidate.stat().st_size <= 512_000:
                    yield root, candidate, relative

    # 在固定项目范围按字面查询分页结果；报告 candidate/cursor/has_more，不能把一个页当作全项目无命中。
    def _search_project(self, turn, args):
        # cursor 计候选文件，limit 计返回行；扫描上限与命中上限分别报告，不能把截断页当全项目结论。
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

    # 只读 Git 的 stdout 有界消费；达到上限主动停止进程，避免先收集全部大 diff 再截断。
    @staticmethod
    def _read_git(command, root, limit):
        expired = threading.Event()
        with subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
            # 超时线程只终止此固定只读 Git 进程；不运行 shell，不泄露项目配置错误正文。
            def expire():
                expired.set()
                try:
                    process.kill()
                except OSError:
                    pass
            timer = threading.Timer(8, expire)
            timer.daemon = True
            timer.start()
            try:
                raw = process.stdout.read(limit + 1)
                truncated = len(raw) > limit
                if truncated:
                    process.kill()
                result = process.wait()
            finally:
                timer.cancel()
            if expired.is_set():
                raise ValueError("git command exceeded its deadline")
            if result and not truncated:
                raise ValueError("git command failed")
            return raw[:limit], truncated

    # 只从环境中明确的绝对 PATH 目录选择 Git；不用 Windows 会隐式插入当前目录的 which。
    @staticmethod
    def _git_executable():
        name = "git.exe" if os.name == "nt" else "git"
        for entry in os.get_exec_path():
            directory = Path(entry)
            if not directory.is_absolute():
                continue
            candidate = directory / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
        raise ValueError("git executable is not available in an absolute PATH directory")

    # 用固定只读 argv 调用 git.status/diff；不接受任意 shell 文本，也不修改仓库。
    def _git(self, turn, kind, args):
        root, _ = self.project_path(turn, ".")
        executable = self._git_executable()
        if not (root / ".git").exists():
            raise ValueError("project root is not a Git repository")
        # 显式禁用项目配置的 fsmonitor/textconv/外部 diff；工具白名单不能成为程序执行通道。
        prefix = [executable, "-c", "core.fsmonitor=false", "--no-pager"]
        if kind == "git.status":
            command = prefix + ["status", "--short", "--untracked-files=normal"]
        else:
            command = prefix + ["diff", "--no-ext-diff", "--no-textconv"]
            raw = args.get("path")
            if raw:
                _, checked = self.project_path(turn, raw)
                if checked.is_dir():
                    raise ValueError("git diff path must identify a file")
                command += ["--", ":(literal)" + checked.relative_to(root).as_posix()]
            else:
                # Git 可跟踪被工具排除的秘钥文件；先枚举路径，逐个复核后才请求正文。
                listing, truncated = self._read_git(prefix + ["diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z"],
                    root, 1024 * 1024)
                if truncated:
                    raise ValueError("git diff exceeds the path listing limit; choose a file")
                admitted = []
                for name in listing.decode("utf-8").split("\0"):
                    if not name:
                        continue
                    try:
                        self.project_path(turn, name)
                    except PermissionError:
                        continue
                    admitted.append(":(literal)" + name)
                if not admitted:
                    return {"output": "", "truncated": False, "command": "git diff (admitted paths)"}
                if len(admitted) > 500 or sum(len(item.encode("utf-8")) + 3 for item in admitted) > 24000:
                    raise ValueError("git diff exceeds the path limit; choose a file")
                command += ["--", *admitted]
        output, truncated = self._read_git(command, root, 24000)
        return {
            "output": output.decode("utf-8", errors="replace"),
            "truncated": truncated,
            "command": (
                " ".join(command[:3]) + " …" if len(command) > 3 else " ".join(command)
            ),
        }

    # 从父 Turn 的冻结快照和已结算结果提取稳定来源引用；模型参数不能凭空制造证据身份。
    @staticmethod
    def _available_subagent_source_refs(turn):
        refs = set()
        stack = [
            ("", turn.get("snapshot") or {}),
            *[
                ("", item.get("result") or {})
                for item in turn.get("activities", [])
            ],
        ]
        while stack:
            key, value = stack.pop()
            if isinstance(value, dict):
                stack.extend(
                    (str(child_key), child_value)
                    for child_key, child_value in value.items()
                )
            elif isinstance(value, (list, tuple)):
                stack.extend((key, item) for item in value)
            elif (
                isinstance(value, str)
                and key in {"evidence_ref", "source_ref", "citation"}
                and value
            ):
                refs.add(value)
        return refs

    def _delegate(self, turn, decision_id, args, provider):
        """委派协调器固定合同并驱动共同子引擎；执行器不再维护第二套单次调用路径。"""
        return self.delegation.delegate(turn, decision_id, args, provider)

    def _evaluate_delegate(self, turn, args):
        """评分与元数据审核由委派协调器核对；真实计量仍归 Runtime。"""
        return self.delegation.evaluate(turn, args)

    # 把合法相对输出路径映射到受管产物目录；输出路径不能覆盖项目源文件。
    def _output_target(self, sid, value):
        relative = self.relative_path(value)
        root = (self.runtime.runtime_dir / "session-outputs" / sid).resolve()
        target = (root / relative).resolve()
        if target == root or not target.is_relative_to(root):
            raise PermissionError("output escapes session scope")
        return target

    def _record_tool_receipt(self, op, result, tool_wall_ms=None):
        """先原子发布固定 Ticket/结果，再结算数据库；崩溃窗口由 recover 复用这份收据。"""
        atomic_write(
            self.receipts / f"{op['decision_id']}.json",
            json.dumps({"decision_id": op["decision_id"], "ticket_id": op["ticket_id"],
                        "result": result, "tool_wall_ms": tool_wall_ms}, ensure_ascii=False).encode("utf-8"),
        )
        return self.repository.settle_operation(op["decision_id"], result, tool_wall_ms=tool_wall_ms)

    def _execute_mcp(self, turn, decision_id, capability, args):
        """先核对本 Turn 发现与配置，再签 Ticket；握手/调用在事务外，任何未决效果不自动重发。"""
        if self.mcp is None:
            raise ValueError("MCP gateway is not configured")
        discovery = None
        if capability == "mcp.call":
            if not isinstance(args.get("tool_name"), str) or not args["tool_name"] or not isinstance(args.get("arguments"), dict):
                raise ValueError("mcp.call requires tool_name and an arguments object")
            # 只消费本 Turn 的已结算工具发现；模型参数不能伪造 discovery、argv 或允许名单。
            for activity in reversed(turn.get("activities") or []):
                result = activity.get("result") or {}
                if result.get("capability_id") == "mcp.tools" and result.get("server_id") == args.get("server_id") and not result.get("error"):
                    if any(row.get("name") == args.get("tool_name") for row in result.get("tools", [])):
                        discovery = result
                        break
        plan = self.mcp.prepare(args.get("server_id"),
            tool_name=args.get("tool_name") if capability == "mcp.call" else None,
            arguments=args.get("arguments") if capability == "mcp.call" else None,
            cursor=args.get("cursor"), discovery=discovery)
        intent = {"write_bytes": 0, "requires_receipt": True, "mcp": {
            "server_id": plan.server_id, "configuration_digest": plan.configuration_digest,
            "tool_name": plan.tool_name, "schema_digest": plan.schema_digest, "cursor": plan.cursor,
            "arguments_digest": sha256_bytes(plan.arguments_json.encode("utf-8"))}}
        op = self.repository.start_operation(turn["run_id"], decision_id, capability, intent)
        started = time.monotonic()
        try:
            result = {**self.mcp.invoke(plan), "capability_id": capability}
        except Exception:
            # Ticket 已持久化；SDK/进程错误正文可能含敏感数据，不复制到异常、数据库或 UI。
            raise RecoveryRequired(f"MCP outcome unknown for {plan.server_id}; reconcile before replay") from None
        # 收据发布失败也属于待核对；不能被应用的参数错误分支消费成安全重试。
        try:
            return self._record_tool_receipt(op, result, max(0, int((time.monotonic() - started) * 1000)))
        except Exception:
            raise RecoveryRequired(f"MCP receipt pending for {plan.server_id}; reconcile before replay") from None

    # 围绕首次真实工具执行派发 Hook；已有 Ticket 的恢复/复用跳过回调与新策略读取。
    def execute(self, turn, decision_id, decision, *, provider=None):
        if self.repository.operation(decision_id):
            return self._execute_tool(turn, decision_id, decision, provider=provider)
        capability = decision.capability_id
        args = decision.arguments if decision.arguments is not None else {}
        information_decision = self._admit_tool(turn, capability, args)
        try:
            hooks = self.tool_hooks.snapshot()
        except (ValueError, PermissionError, OSError):
            raise ToolHookDenied("configuration", "tool_hook_configuration_invalid", "configuration_invalid") from None
        context = ToolHookContext(turn["run_id"], decision_id, capability, "before_tool", readonly_json(args))
        try:
            self._notify_tool_hooks(hooks, context)
            result = self._execute_tool(turn, decision_id, decision, provider=provider,
                                        information_decision=information_decision)
        except Exception as exc:
            # 错误回调只观察；派发后 RecoveryRequired/OSError 等仍原样进入 UNKNOWN 核对流程。
            category = (exc.code if isinstance(exc, ToolHookDenied) else
                        "recovery_required" if isinstance(exc, RecoveryRequired) else
                        "budget_exceeded" if isinstance(exc, BudgetExceeded) else
                        "permission_denied" if isinstance(exc, PermissionError) else
                        "invalid_argument" if isinstance(exc, ValueError) else "execution_error")
            self._notify_tool_hooks(hooks, replace(context, phase="on_tool_error", error_type=category))
            raise
        # 此时收据已发布并结算；观察失败不能把真实结果改写成失败或授权重跑。
        self._notify_tool_hooks(hooks, replace(context, phase="after_tool"), result=result)
        if result.get("error") or result.get("is_error") or result.get("isError") or result.get("failure"):
            self._notify_tool_hooks(hooks, replace(context, phase="on_tool_error", error_type="tool_result_error"), result=result)
        return result

    def _notify_tool_hooks(self, hooks, context, *, result=None):
        """构造只读阶段快照并调用仓储审计；所有回调都在短事务外运行。"""
        try:
            op = self.repository.operation(context.decision_id)
            observed = replace(context, operation_state=op["state"] if op else None,
                               result=readonly_json(result) if result is not None else None)
            def record(trace):
                """仓储核对决定归属后写入白名单元数据，回调不能取得写入函数。"""
                self.repository.record_tool_hook(context.run_id, context.decision_id, context.capability_id, trace)
            dispatch_tool_hooks(hooks, observed, record)
        except ToolHookDenied:
            if context.phase == "before_tool":
                raise
        except Exception:
            if context.phase == "before_tool":
                raise ToolHookDenied("pipeline", "tool_hook_failed", "pipeline_unavailable") from None
            # 快照或审计异常仅影响观察，不遮蔽执行器要返回的 Receipt/要抛出的原异常。

    def _admit_tool(self, turn, capability, args):
        """复用现有能力可见性、注册状态和信息读取准入；Hook 继续不等于授权。"""
        if capability not in TOOL_CATALOG:
            raise PermissionError("tool is not admitted")
        currently_visible = set(visible_tool_ids(TOOL_CATALOG, turn.get("activities") or []))
        if capability not in currently_visible:
            raise ValueError(f"tool is deferred: {capability}; use tool.search/tool.describe before requesting it")
        spec = self.registry.get(capability)
        if spec.state is not CapabilityState.EXECUTABLE:
            raise PermissionError(f"capability is not executable: {capability}")
        validate_tool_arguments(capability, args)
        information_decision = self.information_controller.admit(turn, capability, args)
        if information_decision is not None and not information_decision.admitted:
            raise ValueError("information control denied: " + information_decision.reason)
        return information_decision

    # 执行经过外层准入/Hook 的工作；已有稳定绑定时复用事实而非重复效果。
    def _execute_tool(self, turn, decision_id, decision, *, provider=None, information_decision=None):
        saved = self.repository.operation(decision_id)
        if saved:
            if saved["run_id"] != turn["run_id"]:
                raise PermissionError("operation belongs to another turn")
            if saved["state"] == "RESOLVED":
                return saved["result"]
            if "parallel" in saved["intent"]:
                if not self.recover(turn["run_id"]):
                    raise RecoveryRequired("parallel child receipt remains unresolved")
                return self.parallel.execute(turn, decision_id, decision.arguments or {})
            if saved["capability"] == "agent.delegate" and saved["intent"].get("delegate", {}).get("protocol_version") == "handoff-v2":
                if not self.recover(turn["run_id"]):
                    raise RecoveryRequired("delegated model receipt remains unresolved")
                current = self.repository.operation(decision_id)
                if current["state"] == "RESOLVED":
                    return current["result"]
                return self._record_tool_receipt(current, self._delegate(turn, decision_id, decision.arguments or {}, provider))
            raise RecoveryRequired(
                "tool Ticket already exists; reconcile receipt before continuing"
            )

        capability = decision.capability_id
        args = decision.arguments or {}

        # test.run 的结果必须在 Ticket 后产生；无收据时保持 UNKNOWN，绝不自动重跑项目代码。
        if capability == "test.run":
            intent = self.verification.intent(turn, args)
            op = self.repository.start_operation(
                turn["run_id"], decision_id, capability, intent
            )
            tool_started = time.monotonic()
            result = self.verification.run(turn, args.get("profile_id"))
            tool_wall_ms = max(0, int((time.monotonic() - tool_started) * 1000))
            return self._record_tool_receipt(op, result, tool_wall_ms)

        if capability in {"mcp.tools", "mcp.call"}:
            return self._execute_mcp(turn, decision_id, capability, args)

        # 单调时钟只测本次真实执行/结果准备；已结算的稳定决定在上方直接复用，不重复测量或累加。
        tool_started = time.monotonic()
        result = {"capability_id": capability}
        intent = {"write_bytes": 0}
        if capability == "agent.parallel":
            return self.parallel.execute(turn, decision_id, args)
        elif capability == "skill.list":
            if self.skills is None:
                raise ValueError("Skill library is not configured")
            result.update(self.skills.list_skills())
        elif capability == "skill.load":
            if self.skills is None:
                raise ValueError("Skill library is not configured")
            result.update(self.skills.load(args.get("skill_id"), args.get("expected_digest"),
                                           args.get("offset", 0), args.get("max_chars", 12000)))
        elif capability == "mcp.servers":
            if self.mcp is None:
                raise ValueError("MCP gateway is not configured")
            result.update(self.mcp.servers())
        elif capability == "agent.delegate":
            result.update(self._delegate(turn, decision_id, args, provider))
            # 已知子调用失败已经发布父工具收据，不能用另一份结果再次结算。
            settled = self.repository.operation(decision_id)
            if settled and settled["state"] == "RESOLVED":
                return settled["result"]
            if settled:
                # 委派已在子调用前固定父 Ticket；结果只写 Receipt，不能改写原 intent 再开一次 Ticket。
                tool_wall_ms = max(0, int((time.monotonic() - tool_started) * 1000))
                return self._record_tool_receipt(settled, result, tool_wall_ms)
        elif capability == "agent.evaluate":
            result.update(self._evaluate_delegate(turn, args))
        elif capability == "agent.result":
            result.update(self.delegation.read_result(turn, args))
        elif capability == "agent.resolve":
            result.update(self.delegation.resolve(turn, args))
        elif capability == "knowledge.search":
            report = self.repository.knowledge.search_report(
                args.get("query", ""),
                (turn["snapshot"].get("project") or {}).get("id"),
                args.get("limit", 5),
            )
            result.update(report)
        elif capability == "knowledge.resolve":
            result.update(self._resolve_knowledge(turn, args))
        elif capability == "memory.search":
            if self.memory_store is None:
                raise RuntimeError("memory store is unavailable")
            project_id = (turn["snapshot"].get("project") or {}).get("id")
            report = self.memory_store.search_view_report(
                args.get("query", ""),
                limit=args.get("limit", 5),
                project_id=project_id,
                session_id=turn["session_id"],
            )
            result.update(
                {
                    "memories": report["memories"],
                    "retrieval": {**report["retrieval"], "resolution": "L0"},
                }
            )
        elif capability == "memory.timeline":
            if self.memory_store is None:
                raise RuntimeError("memory store is unavailable")
            result.update(
                self.memory_store.timeline(
                    args.get("memory_id", ""),
                    radius=args.get("radius", 2),
                    project_id=(turn["snapshot"].get("project") or {}).get("id"),
                    session_id=turn["session_id"],
                )
            )
        elif capability == "memory.resolve":
            if self.memory_store is None:
                raise RuntimeError("memory store is unavailable")
            result.update(
                self.memory_store.resolve(
                    args.get("memory_id", ""),
                    resolution=args.get("resolution", "L2"),
                    project_id=(turn["snapshot"].get("project") or {}).get("id"),
                    session_id=turn["session_id"],
                )
            )
        elif capability == "project.list":
            result.update(self.list_project(turn, args.get("path", ".")))
        elif capability == "project.read":
            result.update(self._read_project(turn, args))
        elif capability == "observation.read":
            result.update(self._read_observation(turn, args))
        elif capability == "project.search":
            result.update(self._search_project(turn, args))
        elif capability == "diff.preview":
            result.update(self._diff_preview(turn, args))
        elif capability in {"git.status", "git.diff"}:
            result.update(self._git(turn, capability, args))
        elif capability == "math.calculate":
            result["value"] = calculate(args.get("expression"))
        elif capability == "tool.search":
            descriptions = {
                spec.capability_id: spec.description
                for spec in self.registry.list(executable_only=True)
                if spec.capability_id in TOOL_CATALOG
            }
            result["matches"] = search_tools(
                TOOL_CATALOG,
                descriptions,
                args.get("query"),
                limit=args.get("limit", 6),
            )
            result["note"] = "discovery only; matched tools become visible on the next model step"
        elif capability == "tool.describe":
            descriptions = {
                spec.capability_id: spec.description
                for spec in self.registry.list(executable_only=True)
                if spec.capability_id in TOOL_CATALOG
            }
            result.update(
                describe_tool(
                    TOOL_CATALOG,
                    descriptions,
                    args.get("capability_id"),
                )
            )
            result["note"] = "description only; execution still requires normal capability admission"
        else:
            target = self._output_target(turn["session_id"], args.get("path"))
            if capability == "project.patch_exact":
                _, source = self.project_path(turn, args.get("path"))
                if not source.is_file() or source.stat().st_size > 1_000_000:
                    raise ValueError("source must exist and be <=1MB")
                before = source.read_bytes()
                before_digest = sha256_bytes(before)
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
            eval_mechanisms = turn["snapshot"].get("evaluation_harness_mechanisms")
            action_fusion_enabled = (
                not isinstance(eval_mechanisms, list)
                or "action_fusion" in set(str(item) for item in eval_mechanisms)
            )
            if capability == "project.patch_exact" and action_fusion_enabled:
                # Action Fusion：精确 patch 的确定性后继是 diff 生成，不需要再花一次 LLM 决策。
                # 后继失败不能抹掉已生成候选；因此把 mutation 与 successor 状态分开表达。
                root, source = self.project_path(turn, args.get("path"))
                intent["source_path"] = str(source)
                intent["precondition_digest"] = before_digest
                try:
                    before_text = before.decode("utf-8")
                    after_text = data.decode("utf-8")
                    diff = "".join(
                        difflib.unified_diff(
                            before_text.splitlines(keepends=True),
                            after_text.splitlines(keepends=True),
                            fromfile=f"a/{source.relative_to(root).as_posix()}",
                            tofile=f"b/{source.relative_to(root).as_posix()}",
                        )
                    )
                    result["fused_successor"] = {
                        "kind": "deterministic_diff",
                        "status": "SUCCEEDED",
                        "precondition_digest": before_digest,
                        "candidate_digest": digest,
                        "diff": diff[:24000],
                        "truncated": len(diff) > 24000,
                        "semantic_verification": False,
                    }
                except (UnicodeDecodeError, ValueError) as exc:
                    result["fused_successor"] = {
                        "kind": "deterministic_diff",
                        "status": "FAILED",
                        "reason_code": "projection_failed",
                        "error": str(exc),
                        "precondition_digest": before_digest,
                        "candidate_digest": digest,
                        "semantic_verification": False,
                    }
            intent.update(
                {"write_bytes": len(data), "target": str(target), "digest": digest}
            )

        if information_decision is not None:
            # 控制投影只保存身份/预算/返回规模，不复制正文；后续步骤据 durable activity 重建同样状态。
            result["information_control"] = self.information_controller.record_result(
                information_decision, result
            )
        # Fused successor 在 Tool intent 固定前最后一次重查源身份；一旦 start_operation 提交，
        # intent/result 就不能再被本进程悄悄改写，否则崩溃恢复会看到 Receipt 与 fixed intent 冲突。
        if intent.get("source_path") and intent.get("precondition_digest"):
            current = Path(intent["source_path"]).read_bytes()
            if sha256_bytes(current) != intent["precondition_digest"]:
                fused = result.get("fused_successor")
                if isinstance(fused, dict):
                    fused.update(
                        {
                            "status": "SKIPPED",
                            "reason_code": "precondition_changed",
                            "diff": "",
                            "truncated": False,
                        }
                    )
        intent["result"] = result
        op = self.repository.start_operation(
            turn["run_id"], decision_id, capability, intent
        )
        if intent.get("target"):
            atomic_write(
                Path(intent["target"]), self.runtime.objects.get(intent["digest"])
            )
        # 时间与结果一起先发布到收据；崩溃后的恢复复用原毫秒，不把等待/重启时间算为工具耗时。
        tool_wall_ms = max(0, int((time.monotonic() - tool_started) * 1000))
        return self._record_tool_receipt(op, result, tool_wall_ms)

    # 用已有请求、Ticket、收据和对象核对执行状态；没有足够事实时保留 UNKNOWN，不盲目重发。
    def recover(self, rid):
        self.repository.decisions.recover(rid)
        models = self.repository.decisions.status(rid)["model_invocations"]
        if any(m["state"] in {"TICKETED", "UNKNOWN"} for m in models):
            return False
        for op in self.repository.pending_operations(rid):
            tool_wall_ms = None
            receipt = self.receipts / f"{op['decision_id']}.json"
            if receipt.is_file():
                value = json.loads(receipt.read_text(encoding="utf-8"))
                if (
                    value["ticket_id"] != op["ticket_id"]
                    or value["decision_id"] != op["decision_id"]
                    or (
                        "result" in op["intent"]
                        and value["result"] != op["intent"]["result"]
                    )
                ):
                    raise RecoveryRequired("receipt differs from fixed tool intent")
                result = value["result"]
                # 缺测保持未报告；坏观测字段由仓储忽略，不能改变工具效果核对/预算结算。
                tool_wall_ms = value.get("tool_wall_ms")
            elif "parallel" in op["intent"]:
                self.parallel.reconcile(op)
                continue
            elif op["intent"].get("delegate"):
                # 批次核对可能已经补齐本条子收据；旧 pending 列表不能再次驱动已结算子游标。
                if self.repository.operation(op["decision_id"])["state"] == "RESOLVED":
                    continue
                # 只驱动已记录子决定；需要新 Provider 的已知游标留给正常续跑，不自动重放。
                from .subagent_runtime import run_subagent
                contract = op["intent"]["delegate"]
                if contract.get("protocol_version") != "handoff-v2":
                    raise RecoveryRequired("delegate protocol requires its original runtime for reconciliation")
                state = self.repository.delegation_state(op["decision_id"])
                if state is None:
                    # 没有子 Ticket 时只保留已准入合同；正常驱动再继续，核对本身不派发。
                    continue
                else:
                    state = run_subagent(self, contract, None, replay_only=True)
                    if state["status"] not in {"COMPLETED", "FAILED", "BUDGET_EXHAUSTED", "CANCELLED"}:
                        continue
                    result = self.delegation.result(contract, state)
                self._record_tool_receipt(op, result)
                continue
            elif op["intent"].get("requires_receipt"):
                # 动态执行结果不能由 Intent 猜测；没有收据就保持不明。
                return False
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
            self.repository.settle_operation(op["decision_id"], result, tool_wall_ms=tool_wall_ms)
        return True
