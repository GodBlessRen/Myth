"""旧 MythKernel 导入的薄兼容入口。
实际实现为 MythComponents；保留已公开入口，当前代码使用 components，不再复制旧层次模型。"""

from .components import ADAPTERS, CORE, DOMAINS, MythComponents

# MythKernel：旧公开命名的兼容别名；新代码按能力组合使用 MythComponents。
MythKernel = MythComponents

# __all__：公开导出名单；兼容别名只有在确认外部迁移完成后才删除。
__all__ = ["ADAPTERS", "CORE", "DOMAINS", "MythComponents", "MythKernel"]
