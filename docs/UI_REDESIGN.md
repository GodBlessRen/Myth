# 前端重构记录

日期：2026-10-04。用户委托对 Myth 前端完整重新设计，明确要求简洁专业、简体中文、奶油白与星空黑双主题，并授权自行决定细节。本记录区分设计意图、代码事实与实际验证。

实现基于当前远端 `main`：`06df11b6de5d4440e3cd8d542b0185f84c484060`，已重新核对并合入项目后续变化：DeepSeek、系统安全凭据库、模型原生 Thinking 目录、输出上限以及 Provider Evidence。分支为 `codex/frontend-studio-rebuild`。

## 产品与范围

重构覆盖导航、对话与输入、项目、知识库、会话、Goal 与计划、Runtime、模型设置、弹窗、空态、错误与响应式布局。既有功能全部保留；具体产品事实见 [PRODUCT.md](../PRODUCT.md)。后端授权、持久化、恢复、Provider、预算和数据库语义不属于本次视觉重构范围。

已读取的基线：[旧桌面截图](../output/playwright/before-desktop.png)。主要问题是欢迎区口号占比过大、文字层级和密度失衡、普通英文导航与中文内容混杂，界面重点需要回到工作与真实状态。

## 方向比较与决策

[离线同屏对比页](../output/playwright/design-directions.html) 包含旧界面基线和五个结构方向。小样用于比较信息组织，使用未开始任务的空态，不表示这些替代布局已接入产品后端。

| 方向 | 结构与交互差异 | 主要风险 | 决策 |
| --- | --- | --- | --- |
| 纸面工作台 | 左侧紧凑文字导航；中间宽松对话与稳定输入；右侧完整观测摘要 | 摘要若过密会压缩阅读感 | 采用：最符合现有工作流与常驻观测合同 |
| 窄轨聚焦 | 导航收为图标轨；会话列表独立成列；主操作集中于顶部命令行 | 图标记忆和四列结构增加首次使用负担 | 不采用 |
| 项目索引 | 以项目目录作一级组织；会话作为项目下的列表；资料与对话双区阅读 | 无项目的临时对话被弱化 | 不采用 |
| 执行时间线 | 顶部横向导航；中间按执行阶段纵向展开；输入在时间线末端 | 轻量对话被执行细节打断 | 不采用 |
| 分区编辑器 | 工作区标签切换；中间对话与结果并排；底部状态带 | 小屏复杂、接近 IDE 的操作负担 | 不采用 |

选择依据是用户任务、首屏清晰度和仓库约束；不合并多个方向凑成拼贴。共同视觉合同：`#f8f6f0` / `#101216` 双主题、墨色主动作、鼠尾草正常状态、琥珀运行状态、细线和稳定间距。无营销 Hero、粒子背景或额外口号。

## 七个 Skill 的实际分工

| Skill | 本次用途 | 适用边界 |
| --- | --- | --- |
| creative-design-search | 比较五个结构方向，固定设计合同，最终以实图做减法复核 | 差异来自布局与任务组织，不只换颜色 |
| oil-ui | 任务与主动作分析，用自带生成器留存同屏方向比较，按画面收敛 | 用户已委托决定；无需重复询问方向 |
| impeccable | 产品事实记录、Operate 模式、双主题与响应式、可访问性和整体细节检查 | 既有产品能力与事实必须保留 |
| gpt-taste | 检查主次关系、文字宽度、按钮反差与卡片克制 | AIDA、GSAP、Hero 和巨大章间距不适用于本工作台 |
| frontend-slides | 用可视小样比较方向，控制信息密度，克制出场效果 | 交付是工作台而非演示文稿；不采用固定 16:9 舞台 |
| lieflat-charts | 审查统计的单位、比例、缺失值和真实来源；保持单一颜色语义 | 本轮无独立图表数据交付，不生成装饰图表或伪造趋势 |
| shadcn | 以语义 Token、控件组合、表单标签、弹窗名称和状态规则审查组件 | 仓库为原生前端；不为套 Skill 引入 React 或构建链 |

Skill 指导服从用户需求与当前技术边界。没有把营销、广告、虚构评分、示例计量或未经验证的成功声明放入实际产品。

## 功能与证据边界

第三栏保留 Goal、Execution Flow、Recovery、Trajectory、Tokens / Cache Hit、Context、Tools、Control、Budget 以及已有 Delivery、SOTA Route 和会话统计。Executor heartbeat、Driver heartbeat、durable progress 继续分开；UNKNOWN 先 RECONCILE，INTERRUPTED 对应 RESUME。没有计量显示缺失，不伪装为零或完成。

连接目录绑定 Provider/端点，迟到响应不能重填已切换的设置；保存期间的新 Thinking 选择保留为未保存编辑。草稿、附件、Goal 和稳定 `request_id` 按会话隔离；中文 IME 确认不会发送消息。观测刷新保留展开的 Provider Evidence、历史消息、Goal 卡片和最近会话节点；仅更新时间不重建对话。证据请求同时核对 Run、摘要及读取代数，A→B→A 切换不会接纳旧 A 的迟到响应。表单与抽屉支持键盘焦点、背景 `inert`、关闭后恢复及跨断点释放；迟到原生弹窗打开前释放 Runtime 抽屉。仓库固定默认提示在展示层翻译，用户与模型自由文本、数据库事实保持原文。

本轮界面验证需覆盖会话和模型设置、项目与知识、Goal 与计划、弹窗键盘行为、双主题窄屏，以及浏览器刷新后的状态呈现。静态设计对比不构成后端能力或真实模型验证。

## 验证结果

| 验证 | 结果与范围 |
| --- | --- |
| Python `unittest discover -s tests -v` | 325 项通过，57.3 秒；覆盖仓库原有 Runtime、Provider、恢复、计划及新增静态 HTTP 合同 |
| Node 四组行为回归 | 33 项通过；含缺测/零、预算 UNKNOWN、心跳、A→B→A 证据请求隔离、中文 IME、草稿隔离、重试、连接迟到、未保存 Thinking 与轮询焦点稳定 |
| 实际 Chrome / Playwright | 21 条操作链通过；实际 HTTP、SQLite 和 Runtime，仅模型目录/传输固定；四种 Provider、自适应 Thinking 保存、项目、资料、检索、对话与刷新、会话设置、Goal 与明日计划创建/暂停/重读、键盘和断点；含两档真实资料 GET 延迟后与 Runtime 抽屉的焦点交接 |
| 响应式 | 1440×900、1024×768、390×844、320×740，双主题各页面；66 次主流程宽度检查通过。最终小屏调整另做 32 次双主题页面复验，模型短标签保持单行；手机/平板抽屉焦点与跨断点 `inert` 释放通过 |
| 标准服务 | 当前代码实际启动，CSP、首屏主题脚本、SVG 图标与 Runtime 页面可访问；浏览器 console、pageerror、HTTP 非预期错误均为 0 |
| 包资源 | 无网络依赖构建 wheel 成功，九个 Web 静态文件全部进入 wheel；没有添加前端框架或构建链 |
| 语法与注释 | `compileall`、中文说明检查、五个修改/新增脚本的 `node --check`、`git diff --check` 通过 |

实际浏览器脚本：[check_workspace_browser.cjs](../tests/check_workspace_browser.cjs)。运行前以独立测试根目录启动 [固定传输服务](../tests/ui_fixture_server.py)：

```powershell
$env:PYTHONPATH='src'
python tests/ui_fixture_server.py --root .runtime/ui-browser --port 8770
# 另一个终端；需已安装 Playwright 和 Chrome，路径可通过环境变量覆盖。
node tests/check_workspace_browser.cjs
```

报告：[操作链](../output/playwright/qa-browser-report.json)、[标准服务](../output/playwright/standard-preview-report.json)。截图含实际创建的回归资料、项目和固定模型回答；这些内容用于验证长中文、安全文本与状态，不能当作真实模型质量证据。真实 Provider 推理、API Key / OAuth 授权未联调，没有使用真实密钥。

画面证据：[奶油白](../output/playwright/final-desktop-light.png)、[星空黑](../output/playwright/final-desktop-dark.png)、[模型设置](../output/playwright/qa-settings-dark.png)、[项目](../output/playwright/qa-project-light.png)、[知识检索](../output/playwright/qa-knowledge-light.png)、[目标与计划](../output/playwright/qa-goals-dark.png)、[会话](../output/playwright/qa-sessions-dark.png)、[手机对话](../output/playwright/qa-chat-320-dark.png)、[手机观测](../output/playwright/qa-runtime-390.png)。三组开始/中间/结束截图记录欢迎出场、导航抽屉与弹窗入场，文件名为 `final-*-motion-{start,middle,end}.png`。200% 阅读尺寸使用 720×480 CSS 视口与 DPR 2，在 1440×960 像素截图中检查重排；不把 CSS `zoom` 当作浏览器原生缩放结果。

Impeccable 最终检测剩两项可解释提示：奶油色来自用户明确要求；处理点仅在 RUNNING 且 Driver 在线时动态呈现，断连为静态说明。对比度、小字及重复边框/阴影提示已修正。离线方向页留作设计记录，未把它声明为经过浏览器渲染验证的产品。

## 独立画面评审与最终取舍

无制作历史上下文的评审者只根据实际桌面/手机画面、两套主题与三组动效帧评审，评分 **8.2/10**。主要优点是稳定的工作台层级、双主题一致性、中文表单与克制的装饰；剩余差距集中在 320 px 顶栏/输入选项密度、完成与验收的区分、重复提示。

同一批修正已落地：手机模型入口缩为“模型”，通过可访问名称和悬浮提示保留完整模型；空 Goal 选项缩为“无 Goal”；输入占位缩为“输入消息…”。观测台摘要明确显示“Turn 已完成”及独立验收状态，避免把回答保存解释为任务已验收。删除重复英文观测副标题，默认 Goal 预览优先呈现用户目标说明，固定下一步事实仍留在展开详情。重复键盘提示仅保留桌面输入工具栏一处。

修正后由主执行者确认实际画面与浏览器行为，没有再次打分。三帧记录可确认欢迎与导航的位置/透明度变化；弹窗帧差异较小，不能据此宣称帧率或完整动效性能已测定。
