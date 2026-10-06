# Skill / MCP 首版

本次搭建实际接入 Conversation Agent Loop 的首版，不恢复旧纯登记占位类。按用户明确要求，没有新增或运行测试，没有语法检查、SDK 安装、示例启动、浏览器或构建验证。以下是源码合同与配置方法，不是通过报告。

## 工具入口

| 工具 | 作用 |
| --- | --- |
| `skill.list` | 列出本机 Skill 的名称、说明、全文摘要和字符数。 |
| `skill.load(skill_id, expected_digest, offset?, max_chars?)` | 摘要核对后分页加载正文，资源变化需重新发现。结果进入持久工具 Observation 与后续模型上下文。 |
| `mcp.servers` | 读取配置、启用状态和可选 SDK 可用性；不连接，configured 不表示 connected。 |
| `mcp.tools(server_id, cursor?)` | 先签 Ticket，再启动明确配置的 stdio 服务、握手、读取一页工具及输入 schema；支持返回的 next_cursor。 |
| `mcp.call(server_id, tool_name, arguments)` | 核对允许名单、本 Turn 的发现、配置摘要与输入 schema；先 Ticket，再连接、重查定义并调用一次。 |

`GET /api/workspace/extensions` 提供只读 Skill/MCP 目录，不启动连接；配置错误以不可用状态返回。既有 Runtime Observatory 工具区与架构能力目录投影这些入口，详情仍显示真实结果。首版没有专用安装、启用或认证管理界面。

## 配置与示例

假设启动参数为 `--root <R>`，扩展目录固定为 `<R>/.myth`。它已经被 Git、项目工具与发布包排除，模型不能通过文件工具改写服务配置。

技能放在 `<R>/.myth/skills/<id>/SKILL.md`。`id` 为单段小写字母/数字/下划线/连字符，最长 64；拒绝路径越界、符号链接与 junction。首版从简易单行 `name:` / `description:` frontmatter 提取导航，完整文件按原文读取；不解释任意 YAML、不执行 scripts、不自动启用额外能力。可复制仓库的 `examples/skills/project-review/SKILL.md`。

MCP 需要可选依赖；使用源码时安装：

```powershell
python -m pip install -e ".[mcp]"
```

将 `examples/extensions.json` 复制到 `<R>/.myth/extensions.json`，替换 `command` 与 `args` 中的绝对路径，确认服务属于本机可信程序后将 `enabled` 改为 `true`：

```json
{
  "version": 1,
  "mcp_servers": [{
    "id": "local-demo",
    "enabled": true,
    "transport": "stdio",
    "command": "C:/path/to/Myth/.venv/Scripts/python.exe",
    "args": ["C:/path/to/Myth/examples/mcp_server.py"],
    "allowed_tools": ["add"],
    "timeout_seconds": 30
  }]
}
```

演示服务只提供 `add(a, b)`，导入不启动。上述安装、复制、启用和调用没有在本次执行。配置完成后，在正常对话中要求模型先列 MCP 服务、发现 `local-demo` 的工具，再调用 `add` 即可使用现有执行循环。`allowed_tools: []` 允许发现但拒绝所有远端工具调用。

## 协作与恢复边界

`extension_ports.py` 定义只读资源端口、MCP Gateway 和不可变计划；`Workspace` 装配文件配置、Skill 库与 stdio SDK 适配器，应用仍通过原执行端口协作。配置读取、SDK 导入、参数校验在 Ticket 前；真实进程、握手、发现/调用和收据文件发布在业务事务外。

MCP 的 argv/cwd 来自操作者，模型只提供允许工具的输入；Runtime Intent 保存服务、配置/参数/schema 摘要与发现页身份，命令不复制到数据库或 UI。SDK 首版固定 `>=1.26.0,<2`，参数按发现的输入 schema 以 JSON Schema 2020-12 本地验证；外部 `$ref`、外部 `$id` 作用域和其他声明的 schema 方言拒绝，避免校验自行读取外部来源。采样、roots 与用户交互回调未接入。实现参照[官方 SDK stdio 示例](https://github.com/modelcontextprotocol/python-sdk/blob/v1.26.0/examples/snippets/clients/stdio_client.py)和[会话合同](https://github.com/modelcontextprotocol/python-sdk/blob/v1.26.0/src/mcp/client/session.py)。

一条 MCP 操作拥有一个短生命周期连接，完成后由 SDK 清理。传输/超时/收据错误以安全原因进入 UNKNOWN；存在 Receipt 时复用结果，不再次连接；没有 Receipt 时 `requires_receipt` 阻止恢复重发。远端明确返回错误仍保留返回收据；返回、schema 校验和 Receipt 都不等于业务效果被独立验收。首版没有通用远端状态核对协议，UNKNOWN 需要人工结合服务事实处理。

SDK stdio 服务是操作者授权的本机进程，具有其 OS 账户权限，首版没有 OS 沙箱。未实现 MCP OAuth/API Key、HTTP/SSE、资源、提示模板、二进制内容、长期连接和自动安装；不要将凭据放入配置 argv、模型参数或服务返回值。认证参数字段拒绝，配置不接受 env/headers 等认证入口。

## 规模与后续验收

- 配置最多 64 KiB、16 个服务；每服务最多 32 个 argv、128 个允许工具；请求时限 1–120 秒，SDK 负责退出清理。
- 每个 Skill 最多 64 KiB；发现最多 128 项，加载每页最多 12000 字符，未读部分通过 next_offset 继续。
- MCP 参数与单个 schema 最多 32 KiB、嵌套最多 32 层；发现每个服务页最多呈现 64 个工具，超出显式 truncated/omitted_tools，不声称完整目录。
- MCP 文本最多保留 128000 字符，结构化结果最多 32 KiB，超出保留摘要及省略标记；二进制只记录类型。已有 `observation.read` 可分页回读保留的 content，不能恢复明确截断的部分。
- 本地计量记录工具调用数和墙钟用时，不推断上游服务成本或业务验收。

后续模型应验证资源变化/分页/路径边界、缺失与损坏配置、依赖缺失、允许名单、同 Turn 发现、输入 schema 变化、分页、错误/大返回、超时、跨进程退出、Ticket 前拒绝、收据发布间隙与 UNKNOWN 不重放，并分别记录替身、真实本机 MCP 与真实远端服务证据。本次全部未验证。
