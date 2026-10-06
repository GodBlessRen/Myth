"""官方 MCP Python SDK v1 的可选 stdio 适配器。
显式配置决定 argv 与工具白名单；一次请求一个连接，不接收模型命令，不自动重试外部调用。"""

import importlib.util
import json
import os
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ..domain import canonical_json, sha256_bytes
from ..extension_ports import MCPPlan
from .extension_config import LocalExtensionConfig


def sdk_available() -> bool:
    """只检查可选分发版本，不导入 SDK 或连接服务；基线固定为 1.26 至 2.0 之前。"""
    try:
        parts = version("mcp").split(".")
        return parts[0] == "1" and int(parts[1]) >= 26 and importlib.util.find_spec("mcp") is not None
    except (PackageNotFoundError, ValueError, IndexError):
        return False


def safe_schema(schema: dict) -> None:
    """限制远端 schema 规模，并拒绝外部引用；参数校验不得自行读取网络/本机引用。"""
    if not isinstance(schema, dict) or len(canonical_json(schema).encode("utf-8")) > 32768:
        raise ValueError("MCP schema must be an object within 32 KiB")
    pending = [(schema, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:
            raise ValueError("MCP schema nesting exceeds 32")
        if isinstance(item, dict):
            for key, value in item.items():
                if key == "$id" and (not isinstance(value, str) or not value.startswith("#")):
                    raise ValueError("MCP external schema scopes are unsupported")
                if key == "$schema" and value not in {"https://json-schema.org/draft/2020-12/schema", "https://json-schema.org/draft/2020-12/schema#"}:
                    raise ValueError("MCP schemas require JSON Schema 2020-12")
                if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (not isinstance(value, str) or not value.startswith("#")):
                    raise ValueError("MCP external schema references are unsupported")
                pending.append((value, depth + 1))
        elif isinstance(item, list):
            pending.extend((value, depth + 1) for value in item)


def safe_arguments(arguments: dict) -> str:
    """固定有界 JSON 参数；认证字段不经过模型决定/Runtime 数据库，首版不支持 MCP 认证。"""
    if not isinstance(arguments, dict):
        raise ValueError("MCP arguments must be an object")
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (ValueError, TypeError):
        raise ValueError("MCP arguments must be JSON") from None
    if len(encoded.encode("utf-8")) > 32768:
        raise ValueError("MCP arguments exceed 32 KiB")
    credentials = {"apikey", "accesstoken", "refreshtoken", "password", "clientsecret", "authorization", "token", "secret"}
    pending = [(arguments, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:
            raise ValueError("MCP arguments nesting exceeds 32")
        if isinstance(item, dict):
            for key, value in item.items():
                if key.lower().replace("_", "").replace("-", "") in credentials:
                    raise ValueError("MCP credential arguments are unsupported")
                pending.append((value, depth + 1))
        elif isinstance(item, list):
            pending.extend((value, depth + 1) for value in item)
    return encoded


class StdioMCPGateway:
    """外圈 MCP Gateway；准备只读本机配置，invoke 的进程与网络效果必须位于 Ticket 之后。"""

    def __init__(self, config: LocalExtensionConfig):
        # config：操作者的唯一权限来源；服务描述和远端 annotations 不能修改白名单。
        self.config = config

    def servers(self) -> dict:
        """输出安全目录，不返回 argv、不启动进程，也不把 configured 写成 connected。"""
        configuration, digest = self.config.read()
        return {"configuration_digest": digest, "sdk_available": sdk_available(), "servers": [
            {"server_id": item["id"], "transport": "stdio", "enabled": item.get("enabled", False),
             "status": "configured" if item.get("enabled", False) else "disabled",
             "allowed_tools": item.get("allowed_tools", []), "timeout_seconds": item.get("timeout_seconds", 30)}
            for item in configuration.get("mcp_servers", [])]}

    @staticmethod
    def _sdk():
        """延迟导入可选依赖；缺失在 Ticket 前作为已知配置拒绝，而非外部 UNKNOWN。"""
        if not sdk_available():
            raise ValueError('MCP requires the optional dependency: install "myth-runtime[mcp]"')
        try:
            import anyio
            import jsonschema
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            raise ValueError("MCP optional dependencies are unavailable") from None
        return anyio, jsonschema, ClientSession, StdioServerParameters, stdio_client

    def prepare(self, server_id: str, *, tool_name: str | None = None, arguments: dict | None = None,
                cursor: str | None = None, discovery: dict | None = None) -> MCPPlan:
        """在派发前核对当前配置和本 Turn 的发现证据；argv 始终来自操作者，参数只描述远端工具输入。"""
        configuration, digest = self.config.read()
        item = next((row for row in configuration.get("mcp_servers", []) if row["id"] == server_id), None)
        if item is None or not item.get("enabled", False):
            raise PermissionError("MCP server is not explicitly enabled")
        if not Path(item["command"]).is_file():
            raise ValueError("MCP configured executable does not exist")
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 2000):
            raise ValueError("MCP cursor must be a bounded server cursor")
        sdk = self._sdk()
        encoded = safe_arguments(arguments if arguments is not None else {})
        schema_digest = None
        if tool_name is not None:
            if tool_name not in item.get("allowed_tools", []):
                raise PermissionError("MCP tool is not in the operator allowlist")
            if not discovery or discovery.get("configuration_digest") != digest or discovery.get("server_id") != server_id:
                raise ValueError("MCP tool requires current mcp.tools evidence from this Turn")
            found = [row for row in discovery.get("tools", []) if row.get("name") == tool_name and row.get("allowed")]
            if len(found) != 1:
                raise ValueError("MCP tool must have one admitted discovery entry")
            schema = found[0]["input_schema"]
            safe_schema(schema)
            try:
                validator = sdk[1].Draft202012Validator
                validator.check_schema(schema)
                validator(schema).validate(json.loads(encoded))
            except sdk[1].exceptions.SchemaError:
                raise ValueError("MCP tool schema is invalid") from None
            except sdk[1].exceptions.ValidationError:
                raise ValueError("MCP arguments do not match the discovered tool schema") from None
            schema_digest = found[0]["schema_digest"]
            cursor = discovery.get("cursor")
            if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 2000):
                raise ValueError("MCP discovered cursor is invalid")
        return MCPPlan(server_id, digest, item["command"], tuple(item.get("args", [])), str(self.config.root),
                       tuple(item.get("allowed_tools", [])), item.get("timeout_seconds", 30),
                       tool_name, encoded, cursor, schema_digest)

    @staticmethod
    def _tool(tool, allowed_tools) -> dict:
        """保留远端输入 schema 和摘要；描述/annotations 都是外部数据，不能自行授权。"""
        schema = tool.inputSchema
        digest = sha256_bytes(canonical_json(schema).encode("utf-8"))
        row = {"name": tool.name, "description": (tool.description or "")[:1000],
               "input_schema": schema, "schema_digest": digest, "allowed": tool.name in allowed_tools}
        try:
            safe_schema(schema)
            if tool.outputSchema is not None:
                safe_schema(tool.outputSchema)
        except ValueError:
            row.update(input_schema=None, allowed=False, unavailable_reason="unsupported_schema")
        return row

    def invoke(self, plan: MCPPlan) -> dict:
        """执行前最后核对配置版本；一次 stdio 会话，无自动重试、采样或用户交互回调。"""
        if self.config.read()[1] != plan.configuration_digest:
            return {"server_id": plan.server_id, "status": "NOT_CALLED", "error": "MCP 配置已变化，请重新发现"}
        anyio = self._sdk()[0]
        return anyio.run(self._exchange, plan)

    async def _exchange(self, plan: MCPPlan) -> dict:
        """SDK 负责握手与进程清理；总超时覆盖请求生命周期，stderr 不进入 Runtime 结果或 UI。"""
        anyio, _, ClientSession, StdioServerParameters, stdio_client = self._sdk()
        parameters = StdioServerParameters(command=plan.command, args=list(plan.args), cwd=plan.cwd, env={})
        with open(os.devnull, "w", encoding="utf-8") as errlog, anyio.fail_after(plan.timeout_seconds):
            async with stdio_client(parameters, errlog=errlog) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=plan.timeout_seconds)) as session:
                    initialized = await session.initialize()
                    page = await session.list_tools(cursor=plan.cursor)
                    rows = [self._tool(tool, plan.allowed_tools) for tool in page.tools[:64]]
                    base = {"server_id": plan.server_id, "configuration_digest": plan.configuration_digest,
                            "protocol_version": initialized.protocolVersion, "source_kind": "mcp_external"}
                    if plan.tool_name is None:
                        return {**base, "status": "DISCOVERED", "tools": rows, "cursor": plan.cursor,
                                "next_cursor": page.nextCursor, "truncated": len(page.tools) > 64,
                                "omitted_tools": max(0, len(page.tools) - 64)}
                    found = [row for row in rows if row["name"] == plan.tool_name and row["allowed"]]
                    if len(found) != 1 or found[0]["schema_digest"] != plan.schema_digest:
                        return {**base, "status": "NOT_CALLED", "error": "MCP 工具定义已变化，请重新发现"}
                    response = await session.call_tool(plan.tool_name, arguments=json.loads(plan.arguments_json))
                    text = "\n".join(block.text for block in response.content if block.type == "text")
                    structured = response.structuredContent
                    structured_digest = None
                    if structured is not None:
                        raw = canonical_json(structured).encode("utf-8")
                        if len(raw) > 32768:
                            structured_digest, structured = sha256_bytes(raw), None
                    return {**base, "tool_name": plan.tool_name, "status": "RETURNED", "is_error": response.isError,
                            "error": "MCP 远端报告工具错误" if response.isError else None,
                            "content": text[:128000], "truncated": len(text) > 128000,
                            "content_digest": sha256_bytes(text.encode("utf-8")), "total_chars": len(text),
                            "structured_content": structured, "omitted_structured_digest": structured_digest,
                            "unsupported_content_types": sorted({block.type for block in response.content if block.type != "text"}),
                            "effect_verified": False}
