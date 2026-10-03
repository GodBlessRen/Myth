"""小型组件上下文的纯预算投影器。
用于架构合同和离线检验；真实对话的优先级、折叠和来源报告由 conversation_context 实现，二者不共占业务状态。"""

from __future__ import annotations

from dataclasses import dataclass


# 上下文候选片段；来源、优先级和必需标记属于投影规则，不授予权限。
@dataclass(frozen=True)
class ContextItem:
    # source_ref：固定资料/对象/Run 来源身份；分辨率改变时保留原来源。
    source_ref: str
    # content：上下文或消息正文；属于数据，不授予 Runtime 权限。
    content: str
    # priority：上下文装箱优先级；数值较大优先，required 另优先。
    priority: int = 0
    # required：是否必须保留；放不下时提前失败，不偷偷丢关键约束。
    required: bool = False


# 已选片段与预算使用的不可变投影；保留未选来源，不删除原始事实。
@dataclass(frozen=True)
class ContextFrame:
    # items：实际选入上下文片段；原始事实不在此删除。
    items: tuple[ContextItem, ...]
    # dropped：未选入来源身份集合；用于解释投影预算。
    dropped: tuple[str, ...]
    # bytes_used：所选 UTF-8 字节数；不是供应商 Token 用量。
    bytes_used: int
    # max_bytes：本地 UTF-8 字节上限；不是准确 tokenizer 窗口。
    max_bytes: int


# 按 required/priority 的确定性字节装箱器；必需内容放不下显式失败。
class ContextCompiler:
    # 按 required 和 priority 稳定装箱 UTF-8 字节；必需项放不下拒绝，可选项留 dropped 引用。
    def compile(self, items: list[ContextItem], *, max_bytes: int) -> ContextFrame:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        chosen: list[ContextItem] = []
        dropped: list[str] = []
        used = 0
        ordered = sorted(
            enumerate(items),
            key=lambda pair: (not pair[1].required, -pair[1].priority, pair[0]),
        )
        for _, item in ordered:
            size = len(item.content.encode("utf-8"))
            if item.required and used + size > max_bytes:
                raise ValueError(f"required context exceeds budget: {item.source_ref}")
            if used + size <= max_bytes:
                chosen.append(item)
                used += size
            else:
                dropped.append(item.source_ref)
        return ContextFrame(tuple(chosen), tuple(dropped), used, max_bytes)
