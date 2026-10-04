"""MCP 服务/工具发现的纯目录。
发现条目映射本地 Capability 身份，不等于通过远端网络执行或获得权限；连接和工具调用需独立适配器。"""

from __future__ import annotations

from dataclasses import dataclass


# MCP 服务的发现元数据；connected 是登记状态而非工具调用证据。
@dataclass(frozen=True)
class MCPServerSpec:
    # server_id：MCP 服务目录身份；不是网络连接凭证。
    server_id: str
    # transport：MCP 传输方式描述；实际连接由适配器实现。
    transport: str
    # connected：当前认证/服务连接投影；不证明任何业务效果已完成。
    connected: bool = False


# 远端工具名到本地 Capability 的映射；运行时仍需实际执行适配器及准入。
@dataclass(frozen=True)
class MCPToolSpec:
    # server_id：MCP 服务目录身份；不是网络连接凭证。
    server_id: str
    # tool_name：远端工具名称；映射本地 Capability 后仍须准入。
    tool_name: str
    # capability_id：明确本地能力身份；仍须核对版本、状态和准入范围。
    capability_id: str


# MCP 发现目录；先登记服务后登记工具，不执行网络调用。
class MCPRegistry:
    # 保存本实例的协作对象与配置；状态/I/O 边界见类合同，实例字段不能替代持久执行事实。
    def __init__(self) -> None:
        # _servers：已登记 MCP 服务元数据；不自动连接网络。
        self._servers: dict[str, MCPServerSpec] = {}
        # _tools：远端 MCP 工具到本地能力的目录映射；目录状态不是效果事实。
        self._tools: dict[tuple[str, str], MCPToolSpec] = {}

    # 登记显式 MCP 服务元数据，拒绝重复身份；不在此连接网络。
    def register_server(self, spec: MCPServerSpec) -> None:
        if spec.server_id in self._servers:
            raise ValueError(f"duplicate MCP server: {spec.server_id}")
        self._servers[spec.server_id] = spec

    # 先确认服务已登记，再绑定远端工具到本地 Capability；重复工具拒绝。
    def register_tool(self, spec: MCPToolSpec) -> None:
        if spec.server_id not in self._servers:
            raise ValueError("register MCP server before its tools")
        key = (spec.server_id, spec.tool_name)
        if key in self._tools:
            raise ValueError("duplicate MCP tool")
        self._tools[key] = spec

    # 按目录 connected 状态投影工具；仍不代表获得执行权或实际调用成功。
    def connected_tools(self) -> tuple[MCPToolSpec, ...]:
        return tuple(
            tool
            for key, tool in sorted(self._tools.items())
            if self._servers[tool.server_id].connected
        )
