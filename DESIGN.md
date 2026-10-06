# Myth · 远山回锋工作台

当前实现以 `src/myth/webui/app.css` 和封闭的 `web_assets.PUBLIC_ASSETS` 为准。三栏分别承担导航、对话与 Runtime Observatory；布局、专注与抽屉只保存浏览器偏好，不能改变 Goal、Run 或验收事实。

- 亮色基准 `#FFFEF8`，暗色基准 `#0E100F`。正文、次要文字与控件各用明确颜色角色，不把缺测成本显示成零。
- 本地 Noto Sans SC、Noto Serif SC、Manrope woff2；来源与许可见 [字体说明](src/myth/webui/fonts/README.md)。字体字重最低 400。
- 手工 SVG「远山回锋」用山势和回锋构成 M；主标、暗色、单色、16/32 px 与 favicon 均随包交付。旧太极素材仅在垃圾站。
- 原生 HTML/CSS/JS、无用户构建链、无 CDN；字段继续由原生 input/select 持有，主题选择器只负责呈现。
- 焦点、Escape、中文输入法、草稿与迟到响应保护保留；减少动效偏好停止等待标志运动。正文目标 7:1、次要文字 4.5:1、边界/图标 3:1、触控目标 40 px 是验收要求。

Node 合同检查已覆盖 DOM 身份、原生 Provider/数字参数、迟到连接结果、工具完整证据等。完整五宽度双主题状态矩阵及逐张视觉验收尚未完成；不能以自动检查或旧画面代替设计验收。续跑边界见 [交付审查](docs/CONTINUATION_REVIEW.md)。
