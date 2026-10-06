# 当前工作台与验证边界

设计合同见 [DESIGN.md](../DESIGN.md)。亮色 `#FFFEF8`、暗色 `#0E100F`，原创远山回锋 SVG 与本地字体；保留导航/对话/Runtime Observatory 三栏和窄屏入口。

本轮吸收线性会话索引、每个 Run 的产物单次扫描、全字段工具结果展开、UNKNOWN 原始技术原因。修复原生字段与主题选择器不同步、第二跳设置响应覆盖用户编辑、伪 DOM 检查及中文输入法键盘处理。

现已实际运行 9 个生产 JS 语法检查与 68 项 Node UI 合同，全部通过。这证明确定性合同，不证明全部画面或真实 Provider。

`tests/browser_fixture.py` 使用真实 HTTP/SQLite/Runtime 与固定 Provider；`tests/browser_matrix.cjs` 支持五宽度、双主题和 13 类状态，另以负探针检查 native select、角色控件等检测盲区。矩阵代码已提交，完整运行与逐张读图尚未完成。旧截图移入垃圾站，不继续作为当前视觉验收图。

本轮按用户最新指示优先推送 PR，未重跑完整浏览器矩阵、五组浏览器专项、干净构建或新环境安装。后续完整验收由 [续跑记录](CONTINUATION_REVIEW.md) 跟踪。
