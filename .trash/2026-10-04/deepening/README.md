# 本轮淘汰代码

基线 main `27462b2`；10 月 4 日开始，10 月 5 日完成。这里只留删除部分，部分文件是说明加源码片段，不能运行或导入。

- `ports.py`：15 个没有实现/调用方的 Protocol；当前 Exact 端口仍保留。
- `acceptance.py` / `domain.py` / `conversation.py`：全仓无调用者的帮助函数、结果类型及重复分片排序。
- `workspace.py`：`mental_models` / `knowledge_pages` 旧别名；调用者统一 `knowledge_views`。
- `memory_store.py`：只有测试调用的 `search_views` 包装；测试改为验证实际 `search_view_report`。
- `knowledge.read` 相关：统一为已有 `knowledge.resolve` L0/L1/L2，删除旧 wrapper、schema、目录、策略分支和提示词。
- Control 重写、Goal 进度静默补造、Exact 空验收合同等原件见 `.trash/2026-10-05/deepening/replaced-source/`。

环境 API Key 是仍被 CLI 使用的明确配置入口；缺失耗时是合法的未测量事实。这些不是无用户兼容负担，保留当前语义并修正误导注释。成熟度枚举仍供真实能力观察使用，不等于恢复占位实现。
