"""固定 .myth/hooks.json 的声明式 Hook；不加载模型提供的 Python、脚本或命令。"""

import json

from ..tool_hooks import ToolHook, ToolHookDecision, ToolHookRegistry


def deny_tool(_context):
    """本机策略只拒绝匹配工具；它不替代 Runtime 的其他权限核对。"""
    return ToolHookDecision(denied=True)


def observe_tool(_context):
    """通过标准 Hook Trace 留下阶段记录；没有效果、结果改写或额外输出。"""
    return None


class LocalToolHooks(ToolHookRegistry):
    """把受信 Python 注册项与每次重新读取的本机规则合成固定调用计划。"""

    def __init__(self, config):
        """绑定本机 Hook 配置根，并保留进程内受信注册表作为同一快照来源。"""
        super().__init__()
        # config：复用扩展固定根/链接拒绝边界；Hook 配置与 MCP 配置摘要分别拥有。
        self.config = config

    def snapshot(self):
        """配置缺失为空，损坏则拒绝新工具；工具已有 Ticket 时执行器不调用本方法。"""
        # 先冻结进程内注册，再读取/校验文件规则，最后按优先级合并；中途损坏不返回半份策略。
        registered = super().snapshot()
        path = self.config.checked_path("hooks.json")
        if not path.exists():
            return registered
        try:
            with path.open("rb") as stream:
                raw = stream.read(65537)
        except OSError:
            raise ValueError("hooks.json is unavailable") from None
        if len(raw) > 65536:
            raise ValueError("hooks.json exceeds 64 KiB")
        try:
            value = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("hooks.json must be UTF-8 JSON") from None
        if not isinstance(value, dict) or set(value) - {"version", "hooks"} or type(value.get("version")) is not int or value["version"] != 1:
            raise ValueError("hooks.json requires version 1 and known fields")
        entries = value.get("hooks", [])
        if not isinstance(entries, list) or len(entries) + len(registered) > 32:
            raise ValueError("at most 32 tool hooks are supported")
        seen = {hook.hook_id for hook in registered}
        hooks = list(registered)
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - {"id", "phase", "tools", "priority", "enabled", "action"}:
                raise ValueError("unsupported hook configuration fields")
            phase, action = entry.get("phase"), entry.get("action")
            if action != "observe" and not (action == "deny" and phase == "before_tool"):
                raise ValueError("hook action must be observe, or deny before_tool")
            patterns = entry.get("tools", ["*"])
            if not isinstance(patterns, list):
                raise ValueError("hook tools must be a list")
            hook = ToolHook(entry.get("id"), phase, deny_tool if action == "deny" else observe_tool,
                            tuple(patterns), entry.get("priority", 0), entry.get("enabled", True))
            if hook.hook_id in seen:
                raise ValueError("duplicate tool hook identity")
            seen.add(hook.hook_id)
            hooks.append(hook)
        return tuple(sorted(hooks, key=lambda item: (item.priority, item.hook_id)))
