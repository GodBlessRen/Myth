"""MCP registry skeleton.  Discovery metadata cannot grant execution authority."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MCPServerSpec:
    server_id: str
    transport: str
    connected: bool = False


@dataclass(frozen=True)
class MCPToolSpec:
    server_id: str
    tool_name: str
    capability_id: str


class MCPRegistry:
    def __init__(self) -> None:
        self._servers: dict[str, MCPServerSpec] = {}
        self._tools: dict[tuple[str, str], MCPToolSpec] = {}

    def register_server(self, spec: MCPServerSpec) -> None:
        if spec.server_id in self._servers:
            raise ValueError(f"duplicate MCP server: {spec.server_id}")
        self._servers[spec.server_id] = spec

    def register_tool(self, spec: MCPToolSpec) -> None:
        if spec.server_id not in self._servers:
            raise ValueError("register MCP server before its tools")
        key = (spec.server_id, spec.tool_name)
        if key in self._tools:
            raise ValueError("duplicate MCP tool")
        self._tools[key] = spec

    def connected_tools(self) -> tuple[MCPToolSpec, ...]:
        return tuple(
            tool for key, tool in sorted(self._tools.items())
            if self._servers[tool.server_id].connected
        )
