"""操作者拥有的本机扩展配置读取。
固定 .myth/extensions.json 位于受保护目录；不接受模型路径、命令或明文认证配置。"""

import json
import re
from pathlib import Path

from ..domain import sha256_bytes


# 稳定目录身份只接受单段可移植名称，不能用点段或路径分隔符扩大读取范围。
EXTENSION_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")


class LocalExtensionConfig:
    """每次准备重新读取当前配置；实例不缓存可变权限或宣称服务已连接。"""

    def __init__(self, root):
        # root：明确 Runtime 根；扩展固定放在项目工具排除的 .myth 内。
        self.root = Path(root).resolve()
        self.directory = self.root / ".myth"

    def checked_path(self, relative: str) -> Path:
        """拒绝配置/技能目录的符号链接和越界；只用于本机资源，不接受模型任意路径。"""
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise PermissionError("extension resource must stay within .myth")
        target = self.directory / relative
        current = target
        while current != self.root:
            if current.is_symlink() or current.is_junction():
                raise PermissionError("extension resource cannot be a link")
            current = current.parent
        if not target.resolve().is_relative_to(self.root):
            raise PermissionError("extension resource escapes runtime root")
        return target

    def read(self) -> tuple[dict, str]:
        """读取最多 64 KiB 的 v1 配置；不存在时保持空目录，损坏配置明确拒绝。"""
        path = self.checked_path("extensions.json")
        if not path.exists():
            return {"version": 1, "mcp_servers": []}, sha256_bytes(b"")
        try:
            with path.open("rb") as stream:
                raw = stream.read(65537)
        except OSError:
            raise ValueError("extensions.json is unavailable") from None
        if len(raw) > 65536:
            raise ValueError("extensions.json exceeds 64 KiB")
        try:
            value = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("extensions.json must be UTF-8 JSON") from None
        if not isinstance(value, dict) or set(value) - {"version", "mcp_servers"}:
            raise ValueError("unsupported extension configuration fields")
        if type(value.get("version")) is not int or value["version"] != 1:
            raise ValueError("extensions.json requires version 1")
        servers = value.get("mcp_servers", [])
        if not isinstance(servers, list) or len(servers) > 16:
            raise ValueError("mcp_servers must contain at most 16 entries")
        seen = set()
        for item in servers:
            allowed = {"id", "enabled", "transport", "command", "args", "allowed_tools", "timeout_seconds"}
            if not isinstance(item, dict) or set(item) - allowed:
                raise ValueError("unsupported MCP configuration fields; credentials are not supported")
            sid = item.get("id")
            if not isinstance(sid, str) or not EXTENSION_ID.fullmatch(sid) or sid in seen:
                raise ValueError("MCP server id must be unique and portable")
            seen.add(sid)
            if type(item.get("enabled", False)) is not bool or item.get("transport", "stdio") != "stdio":
                raise ValueError("MCP v1 configuration supports explicit enabled and stdio only")
            command = item.get("command")
            if not isinstance(command, str) or "\0" in command or not Path(command).is_absolute():
                raise ValueError("MCP command must be an operator-configured absolute executable")
            argv = item.get("args", [])
            tools = item.get("allowed_tools", [])
            if not isinstance(argv, list) or len(argv) > 32 or any(not isinstance(arg, str) or len(arg) > 4096 or "\0" in arg for arg in argv):
                raise ValueError("MCP args must be at most 32 bounded strings")
            if not isinstance(tools, list) or len(tools) > 128 or any(not isinstance(name, str) or not name or len(name) > 200 for name in tools):
                raise ValueError("MCP allowed_tools must be explicit bounded tool names")
            timeout = item.get("timeout_seconds", 30)
            if type(timeout) is not int or not 1 <= timeout <= 120:
                raise ValueError("MCP timeout_seconds must be 1-120")
        return value, sha256_bytes(raw)
