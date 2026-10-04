# 2026-10-04 淘汰记录

基线：c0446dd。完整处置理由见生产树 docs/FILE_REVIEW.md。

- docs/archive、旧审查/画面报告与旧证据：历史结论不作当前版本通过证据。
- output/playwright：一次性设计方向、截图与浏览器报告，不属于运行资源。
- evals/archive：foundation-v1/v2/v3 退役，当前回归统一 foundation-v4；daily-v1 是另一条当前任务集，保留。
- platform/kernel、mcp、skills、workflow：无生产调用的别名/占位实现。
- providers/capabilities：纯合同内移到 model_capabilities，旧路径淘汰。
- AGENTS、宪法、组件地图、Delivery 计划：旧文本留档；当前版本只按新事实维护。
- removed-code：从活跃文件去掉的旧 API、迁移/回填与旧格式专用测试片段；原函数/方法按文件留存。

发布排除由 .gitattributes、MANIFEST.in、src 包根和 scripts/validate_release.py 共同核对。垃圾站不得进入生产 import 和项目检索。
