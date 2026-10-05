"""公开 Runtime/组件入口与按需导出。

按需加载具体入口；只导入纯领域模块时不连带加载数据库、供应商和认证依赖。
公开名称保持原类身份，缓存只用于导入，不能替代任何持久 Runtime 状态。
"""

from importlib import import_module

# __version__：软件包版本的单一代码入口；HTTP User-Agent 和组件快照复用此值。
__version__ = "0.26.0"

# 固定公开名称到具体模块的映射；不用扫描插件或在 import 时创建服务/连接。
_EXPORTS = {
    "AgentRuntime": (".agent_runtime", "AgentRuntime"),
    "MythRuntime": (".runtime", "MythRuntime"),
    "MythComponents": (".platform", "MythComponents"),
}

# __all__：当前公开入口；新增入口必须有实际调用方。
__all__ = list(_EXPORTS)


# 仅解析声明过的公开入口；缓存同一个类，公开类的身份与直接导入保持一致。
def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


# 让帮助/补全仍可发现尚未加载的公开名称；查询目录不主动装配 Runtime。
def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))
