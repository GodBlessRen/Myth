"""可由操作者显式配置的本机 MCP 演示服务。
只提供无外部效果的加法；导入不启动服务，stdio 生命周期交给 MCP SDK 管理。"""

from mcp.server.fastmcp import FastMCP


# server：演示协议端点，不取得 Myth 的数据库、凭据、项目或工具权限。
server = FastMCP("Myth local example")


@server.tool()
def add(a: int, b: int) -> int:
    """返回两个整数的和，用于演示发现、输入 schema 与结构化返回。"""
    return a + b


if __name__ == "__main__":
    server.run(transport="stdio")
