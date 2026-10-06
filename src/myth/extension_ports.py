"""Skill 资源与 MCP 调用的协作合同。
内圈只认识资源投影和固定调用计划；目录、SDK、进程与配置读取由外圈实现。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MCPPlan:
    """一次明确配置的调用计划；命令仅留在进程内，持久 Intent 保存摘要与工具身份。"""

    # server_id/configuration_digest：本机服务身份及配置版本，不代表已连接。
    server_id: str
    configuration_digest: str
    # command/args/cwd：操作者配置的固定 argv 与工作目录，模型不能覆盖。
    command: str
    args: tuple[str, ...]
    cwd: str
    # allowed_tools：本配置允许的远端工具；发现其他名称不会扩权。
    allowed_tools: tuple[str, ...]
    # timeout_seconds：包含握手、请求与清理的有界调用时间，单位秒。
    timeout_seconds: int
    # tool_name/arguments_json：空工具名表示 tools/list；参数 JSON 已在 Ticket 前校验。
    tool_name: str | None = None
    arguments_json: str = "{}"
    # cursor/schema_digest：发现页身份和本次工具定义摘要，执行前再次核对。
    cursor: str | None = None
    schema_digest: str | None = None


class SkillLibrary(Protocol):
    """只读技能资源端口；读取流程文本不授予新能力，也不执行其中脚本。"""

    def list_skills(self) -> dict:
        """返回有界元数据与全文摘要，供模型按需选取资源。"""
        ...

    def load(self, skill_id: str, expected_digest: str, offset: int = 0, max_chars: int = 12000) -> dict:
        """按已发现摘要分页读取 UTF-8 文本；资源变化要求重新发现。"""
        ...


class MCPGateway(Protocol):
    """同步调用端口；准备阶段不启动进程，invoke 必须由协调者在 Ticket 后执行。"""

    def servers(self) -> dict:
        """返回本机配置与依赖可用性，不探测连接或返回命令/凭据。"""
        ...

    def prepare(self, server_id: str, *, tool_name: str | None = None,
                arguments: dict | None = None, cursor: str | None = None,
                discovery: dict | None = None) -> MCPPlan:
        """验证白名单、配置版本与已发现工具的参数，生成固定计划。"""
        ...

    def invoke(self, plan: MCPPlan) -> dict:
        """执行一次握手/发现/调用并清理连接；传输失败不证明效果未发生。"""
        ...
