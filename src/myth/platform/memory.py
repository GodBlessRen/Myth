"""Memory 的用途分类。
纯枚举供持久仓储和上层策略共享；内容、revision 和撤销事实统一归 SqliteMemoryStore。"""

from __future__ import annotations

from enum import StrEnum


# 记忆用途分类；用途不自动改变事实等级或执行权限。
class MemoryKind(StrEnum):
    # WORKING：当前任务工作记忆；内容仍有来源和作用域。
    WORKING = "working"
    # EPISODIC：已结束经历投影；不自动升级为 verified。
    EPISODIC = "episodic"
    # SEMANTIC：声明的知识记忆用途；事实等级仍需证据。
    SEMANTIC = "semantic"
    # PROCEDURAL：可复用流程记忆用途；内容不能扩张能力权限。
    PROCEDURAL = "procedural"
