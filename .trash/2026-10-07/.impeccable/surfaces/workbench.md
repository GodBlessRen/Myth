# Myth 工作台

Mode: Operate. Build path: code-led. 用户确认「艺术机构：安静、精确、有辨识度」，进一步要求三栏内部的划分、布局、折叠更有创造力。2026-10-06 修订：移除纸构，白色固定 #F8F4ED、黑色固定 #0E100F；静态身份采用透明水墨太极波浪 M。没有批准过独立设计稿，本轮是在既有世界内细化身份、选择器、参数与价格设置。

## Direction contract

THESIS：把工作空间理解为可展开的装帧。三栏拥有不同的密度与阅读尺度，通过显式折叠重新分配空间；造型服从实际操作。

FIRST VIEWPORT：左栏分为工作、资料、最近会话，中央真实输入构成工作区域，右栏始终保留运行状态与独立验收提示。水墨身份只用于品牌与工作空间，微型几何太极只用于真实等待；不替代被移除的首屏装饰。已有会话以问题目录和正文为主体，正文/输入框两侧严格对齐。

SIGNATURE：专注模式同时把两栏收成可操作的窄轨道，退出后恢复进入前的两栏状态。右栏三个观察角度展示同一组权威事实；证据类别可独立折叠。会话目录按真实消息身份定位并恢复焦点。

MOTION：空间分配 260ms，观察角度切换 180ms，展开箭头 180ms，均使用指数型 ease-out。真实等待使用14px太极，2.6秒匀速转一周；Reduced motion 全部静止。仅真实在线 Driver 或真实等待请求显示，不生成装饰进度。

RESPONSIVE：1120px 以下观测栏转为有焦点边界的抽屉；800px 以下导航也转为抽屉。中央阅读区与输入区共享宽度及内边距，320px 仍保留对齐和全部入口。

BOUNDARIES：UI 偏好只写 localStorage；不创建 Run、不改变授权、不改写消息。保留 Goal / Run / Ticket / Receipt / Artifact / Verification、恢复与所有观测类别。只翻译已知标签，未知后端内容原样展示。

## Current refinements

IDENTITY：`src/myth/webui/ink-taiji.png` 为内置生成的（1918×820）RGBA 透明资产。用户进一步要求原构图旋转180°、水平对齐两只相反颜色的鱼眼，并延伸中央分界形成波浪 M；当前资产左黑、右奶油白。品牌与工作空间为56×24px，折叠轨道宽36px，四方向 .3px 零模糊 `--ink-2` 轮廓从实际 alpha 导出，让两侧在双主题都可辨认。不增加徽章底色、框、装饰场景或品牌运动；旧几何品牌规则由本次明确指令覆盖。生成提示词在 PNG `impeccable:prompt` 与同名 JSON 中一致；14px 等待仍用 `taiji.svg`。

CHOICES：共享 `choices.js` 包装原 select / input，不创建第二份业务值；模型名称保留可编辑建议。主题 Listbox 使用 Popover 顶层，挂在所属 dialog 或 body 内；统一方向键、Home / End、Enter、Tab、Escape 和前缀输入，Escape 先关闭菜单再回到 dialog。动态目录与子槽位沿用同一控件层；删除源字段同步清理菜单。手机目标为44px，弹层按视口空间向上或向下打开。

SETTINGS：主/子模型分别保留数值边界与意义，输出 Token 受当前模型上限进一步约束；Thinking 显示模型原生档位并说明时间/输出成本。温度通常0–2，Claude0–1；模型默认采样时控件停用并恢复0，避免切换提供方后遗留无法编辑的超界值。普通 OpenAI API 模型传递温度；推理/OAuth、新 Claude 模型按实际能力使用默认采样。服务地址和上下文窗口仍只在 Ollama 出现。

PRICING：主/子模型按提供方和精确模型 ID 自动查询 models.dev，显示百万 Token 单位、来源、查询时间、过期状态和提供方价格说明。合同覆盖是可折叠的显式选项。未收录、不可连接、未公布、订阅、本地/自托管保持相应未知文字；目录零占位不视为免费。费用为估算，未计缓存折扣。查询在 Runtime 事务外，未来 Run 冻结已解析设置；目录价格及查询时间不扩张用户请求身份，自定义合同费率属于身份，历史/恢复 Run 不被新目录改写。

## Evidence

2026-10-06，源码基线 `origin/main 78487c2`。最终 [ink-design-review.md](../../output/playwright/ink-design-review.md) 的 disposition 为 **ship**；一次集中修正后，身份56/36px双主题可辨识度与「温度2 → Claude停用0 → 主模型保存200」两项 P2 均 **resolved**。子模型对应关闭证据是源码修正、真实控件断言与相同服务端边界，没有声称单独保存子模型已执行。

- 专项 [ink-settings-browser-report.json](../../output/playwright/ink-settings-browser-report.json)：7项检查、10张截图、errors=[]；覆盖主/子自动标价、原生 Thinking、数字边界、1440/390/320双主题菜单包含与 dialog Escape。另有2张折叠轨道确认图。
- 最终画面在 `.impeccable/review/ink-home-{light,dark}.png`、`ink-settings-{1440,390}-{light,dark}.png`、`ink-pricing-{1440,390}-{light,dark}.png`、`ink-collapsed-{light,dark}.png`；合计12张。设置手机保存后的短暂 toast 不遮挡报价、温度或菜单。
- 既有主浏览器报告为21 PASS且页面/HTTP/请求错误为空；本次评审没有重跑它。根代理报告 Python486项（485通过、1跳过）与 Node36通过，本次文档工作未重跑这些测试。
- PNG 在 Pillow `load()` 后的嵌入提示词为1628字符，与 JSON 一致。公开目录实际探测在 `2026-10-05T17:56:42Z` 得到 OpenAI `gpt-4.1` 的输入2/输出8 USD每百万Token；这是该次目录响应，截图中的1/2为夹具值。

固定 Provider/browser 流证明 UI、HTTP 与持久行为，不代表远端模型质量、OAuth、真实账单或生产可用性。价格错误/过期、展开后的子参数及 Thinking 弹层本轮只有代码/自动检查证据，没有独立最终画面。完整源哈希与证据路径记录在 [design.json](../design.json)。
