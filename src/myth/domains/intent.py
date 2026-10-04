"""Intent Pick 的纯协议。
选择处理路径而不授予权限；实现可替换为规则或模型，但固定 Run 的执行权仍归 Runtime。"""

from __future__ import annotations

from typing import Any, Protocol

from .information import IntentPick


# 输入与上下文到路由提案的纯协议；保持实现可替换并与权限分离。
class IntentPicker(Protocol):
    # 从输入与已给上下文选择处理路径；输出是路由提案，具体准入与效果仍由 Runtime 控制。
    def pick(self, value: str, context: dict[str, Any]) -> IntentPick: ...


# __all__：当前公开入口；新增入口必须有实际调用方。
__all__ = ["IntentPick", "IntentPicker"]
