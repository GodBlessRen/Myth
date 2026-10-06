# 工具 Hook 首版

Hook 已接入主 Conversation 工具执行器，默认没有规则。本版提供本机配置和受信 Python 注册，不自动执行 Skill 脚本，也不把模型文本作为 Hook。

顺序：已有 Ticket 则恢复/复用 → 能力与参数形状校验 → 信息准入 → 冻结 Hook 计划 → `before_tool` → 工具专用参数/路径/MCP schema 核对 → Ticket → 执行 → Receipt/结算 → `after_tool`。抛出执行异常或返回带错误的工具结果时派发 `on_tool_error`。

| 阶段 | 回调合同 | 失败处理 |
| --- | --- | --- |
| `before_tool` | 返回 `None`/继续决定，或明确拒绝 | 拒绝、回调失败、审计失败均不签 Ticket；作为已知 Observation 消费 |
| `after_tool` | 收到已结算结果的只读快照，返回 `None` | 只记 Hook 失败，保留原工具结果 |
| `on_tool_error` | 收到错误类别、当前 Ticket 状态及可用结果，返回 `None` | 保留原异常；UNKNOWN 仍须核对，不能被回调“修复” |

参数和结果递归复制后冻结；Hook 没有参数改写、结果替换、补签 Ticket、改预算或改变验收的接口。回调不获得 Runtime、仓储、Provider 或异常对象。继续只表示进入原工具流程，仍须通过原权限核对。

## 本机配置

把 [示例配置](../examples/hooks.json) 复制到 **Runtime 根** `.myth/hooks.json`，不是任意当前目录。示例的 `block-mcp` 默认关闭；开启后在 Ticket 前拒绝 `mcp.call`。`observe` 通过标准 Trace 记录匹配阶段，不执行额外命令。

配置支持 `id / phase / tools / priority / enabled / action`。能力名支持 `*` 和 `?` glob；priority 越小越先，同级按 id 排序。`deny` 仅允许在 `before_tool` 使用，`observe` 可用于三个阶段。最多 32 项、单项最多 16 个匹配模式、配置最多 64 KiB；重复身份、未知字段、链接或损坏配置拒绝新工具。配置在每次新工具调用前重新读取，后续阶段使用该调用的固定计划。

`GET /api/workspace/extensions` 的 `hooks` 返回只读目录；读取目录不会运行回调。

## Python 注册

装配根可以注入 `ToolHookRegistry`，或在 `Workspace.tool_hooks` 上注册。以下是调用方示例，当前交付未执行：

```python
from myth.tool_hooks import ToolHook, ToolHookDecision
from myth.workspace import Workspace


def reject_large_artifact(context):
    """受信纯策略：按参数拒绝，不执行文件或网络效果。"""
    if len(context.arguments.get("content", "")) > 2000:
        return ToolHookDecision(denied=True, reason_code="artifact_too_large")
    return None


workspace = Workspace(runtime)  # runtime 由现有入口负责创建和关闭
workspace.tool_hooks.register(ToolHook(
    hook_id="artifact-limit",
    phase="before_tool",
    tools=("artifact.write",),
    priority=-10,
    callback=reject_large_artifact,
))
```

`unregister(id)` 只移除 Python 注册项并影响未来调用；文件规则通过修改本机配置关闭。Python 注册是进程内装配，不跨重启持久化；Web 的其他 Workspace/连接不会自动共享该注册表。需要跨入口的规则放在本机配置中。

## Trace 与恢复

仓储短事务核对 Run、决定及能力归属后追加 `ConversationToolHook`，记录 Hook 身份、阶段、状态、机器原因码、耗时毫秒、Ticket 状态和错误类别。事件不保存参数、结果、回调输出或异常正文；回调在数据库事务之外运行。

有 Ticket 的调用不会再跑任何 Hook，已有收据直接复用；恢复路径不受后来损坏或变更的 Hook 配置影响。崩溃发生在收据结算与观察回调之间时，恢复不会补发观察回调。观察事件写入不可用时保留原执行事实，该事件可能缺失；前置审计不可用则关闭执行。

## 当前范围与后续验收

这是主 Conversation 执行器的首版，覆盖该执行器的 `test.run`、Skill、MCP、委派/并行批次及普通工具分支。父 `agent.delegate / agent.parallel` 接收 Hook；子引擎的独立 `input.read` 和 Exact 执行路径没有接入本管线。

Python 回调是同步、受信、进程内代码，应只做快速纯判断/观察；本版没有进程隔离、强制超时、外部 Hook 命令或 Hook 专项 Evaluation。Python 宿主代码本身有进程权限，只读快照不是 OS 沙箱。Hook Trace 不是独立 Verification。

按用户要求：未新增或运行测试，未执行语法检查、构建、浏览器验证或示例。后续模型需验收：优先级/匹配/注销、嵌套不可变性、前置拒绝无 Ticket/费用、回调/配置/审计故障、所有工具分支、MCP 错误返回与 UNKNOWN、结算后观察失败、崩溃/恢复不重发 Hook，以及已有工具的参数目录一致性。
