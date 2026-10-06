# 工作台交互清单

这是当前实现入口与后续验收清单，不是通过报告。2026-10-07 收尾按用户要求未运行测试；来源为 `index.html`、`app.css`、`app.js`、`choices.js`、`studio.js`、`goals.js`、`model-pool.js` 与 `inspector.js`。静态字段和动态控件按协作族列出，新增控件归入对应族。

## 通用状态与键盘

| 状态 | 呈现与约束 |
| --- | --- |
| 默认 | 两主题使用明确的正文、次要文字、边界与背景角色；真实缺测显示 N/A，陌生业务状态保留原文。 |
| 悬停 | 按钮、链接、选项用边界或背景反馈；操作名称不依赖悬停才能读取。 |
| 焦点 | `:focus-visible` 提供轮廓；消息输入由编辑器 `:focus-within` 标识。Tab/Shift+Tab 沿可见可用控件移动，原生隐藏 select 不重复进入焦点链。 |
| 按下 | 按钮按下位移 1 px；减少动效偏好以当前 CSS/脚本分支为准，后续浏览器检查确认实际表现。 |
| 禁用 | 原生 disabled 阻止提交，颜色与鼠标提示同步；选择菜单读取字段、fieldset、optgroup 与选项的真实可用性，只读输入不得从建议菜单改写。 |
| 加载 | 操作族按现有禁用、状态文字或等待标志呈现；轮询不得重置用户编辑或正在导航的菜单位置。不能把心跳当作持久进度。 |
| 错误 | 连接结果、Toast、运行提示、计划错误保留后端原因；必填/数值边界由表单原生有效性参与提交，浏览器表现待验。 |
| 已选 | 页面 active、菜单 aria-selected、观测 tab aria-selected、专注 aria-pressed 与主题状态分别描述视图。方向键活动项不等于已提交选项。 |

普通按钮以 Enter/Space 激活，链接以 Enter 激活，details/summary 使用原生展开行为。选择器支持方向键、Home/End、Enter 确认、Escape 收起、Tab 离开；菜单中禁用项跳过，全部禁用时没有活动项。中文 composition 的确认键不被菜单或全局快捷键消费。

原生对话框保留模态 Tab 围栏、Escape 与 `[data-close]` 退出、打开前焦点归还；从内容拖选到遮罩不关闭。其选择弹层随退出收起。正文对比目标 7:1、次要文字 4.5:1、边界/图标 3:1；桌面目标至少 40 px，手机主要控件 44 px，均须实测。

## 入口与状态所有者

| 交互族 / 当前入口 | 行为与后续核对重点 |
| --- | --- |
| 导航：`[data-page]`、`[data-nav-group]`、`recentSessions`、`sidebarCollapse`、`menuToggle`、`sidebarShade` | 路由、组展开、桌面折叠、手机导航抽屉；当前页与组偏好保持。导航打开后的焦点顺序、Escape、遮罩退出由浏览器复核。 |
| 主题/专注：`themeToggle`、`[data-theme-choice]`、`focusMode` | 主题保存浏览器偏好；专注只在桌面可用，退出恢复进入前的两栏布局，Escape 避让输入法和模态对话框。 |
| 快捷操作：`commandToggle`、`commandPalette`、`commandSearch`、`commandResults` | Ctrl/⌘ K 打开；方向键选中、Enter 执行、Escape 退出；搜索结果和空态使用纯文本。 |
| 新会话：`newChat`、`newSession`、`[data-action]` | 显式创建/导航；Ctrl/⌘ Shift O 受输入法与模态状态约束。 |
| 编辑器：`composer`、`prompt`、`send`、`chatProject`、`chatGoal`、`quickGoal` | 原字段持有消息/项目/Goal；草稿按会话保存，中文组合输入期间不提前发送，提交才申请业务准入。核对 Enter、Shift+Enter 与禁用/失败后草稿。 |
| 附件：`attachButton`、`chatFiles`、`attachmentChips`、`.attachment-remove` | 显式文件选择、文本读取、移除；文件不被视为授权指令，错误反馈与再次选择同文件待核对。 |
| 会话阅读：`conversationIndex`、`conversationLinks`、`scrollToBottom`、消息/代码复制按钮 | 目录定位到真实消息 ID 并归还阅读焦点；回到最新消息遵循减少动效偏好；复制成功/失败按结果反馈。 |
| 工具/来源/产物：工具 details、完整结果展开、`.source-list`、`.artifact-card .download` | 默认摘要与完整证据分开；来源打开资料，产物下载真实字节。UNKNOWN 技术原因可展开，Receipt/Artifact/Verification 不互相替代。 |
| 当前运行：`steerTurn`、`pauseTurn`、`resumeTurn`、`compactTurn`、`stopRun`、`stopTurn`、`turnNotice` 的继续按钮 | 只提交明确控制命令；可用性来自当前 Turn，停止不抹除晚到事实。检查加载拒绝、终态及 UNKNOWN 提示。 |
| 控制对话框：`controlDialog`、`steerInput`、`turnModelInput`、`turnThinkingInput`、`applySteer`、`applyModelSwitch`、`applyThinkingSwitch` | 设置值仍由原字段持有；revision 与后端提交结果分开呈现。关闭不等于执行控制。 |
| 观测布局：`inspectorToggle`、`inspectorClose`、`inspectorDock`、`[data-inspector-lens]`、`[data-evidence-section]` | 窄屏抽屉、桌面窄轨道、三个角度与事实折叠；tab 用左右/Home/End 切换并移动焦点；不会创建 Run 或改验收。 |
| 观测证据：`providerEvidenceDetails`、执行链/图/工具 details、`inspectorTokens` | 明确展开才获取 Provider 证据；迟到响应核对页面身份。预算已结算与实测分列，输入/输出/缓存/用时显示 n/N 次报告；零与缺测分开。 |
| 会话管理：`sessionSearch`、`activeSessions`、`archivedSessions`、会话卡片、`sessionMenu`、`sessionDialog` | 搜索/分页状态、活动/归档页、重命名、项目选择、置顶、归档、`sessionExport` 下载；归档失败保持错误可见。 |
| 项目：`createProject`、项目卡片、`editProject`、`projectChat`、`projectImport`、`projectFiles`、`projectDocuments`、`projectForm` | 创建/编辑、显式本地根范围、进入会话、导入、目录前进/返回与文件资料预览。路径与文档文本不解释为 HTML。 |
| 知识：`knowledgeProject`、`knowledgeSearch`、`searchKnowledge`、`importKnowledge`、`knowledgeFile`、`knowledgeForm`、`documentDialog` | 项目筛选、搜索、文件/粘贴导入、来源预览、文档归档；等待、无结果与拒绝分开。 |
| Goal：`createGoal`、`goalForm`、`[data-goal-action]`、进度/计划 details | 创建长期意图、继续工作、安排、暂停/恢复；重绘按 Goal/动作身份恢复焦点，Goal 完成与 Turn 回答分别呈现。 |
| 计划：`scheduleForm`、`scheduleSession`、`schedulePrompt`、`scheduleDue`、`scheduleInterval`、计划行打开/启停 | 表单生命周期内保持 request_id；本地时间显式转 UTC；已消费的一次计划不能重新启用。 |
| 模型设置：`modelPill`、`provider`、`model`、`checkConnection`、`ollamaUrl`、`maxSteps`、`maxTokens`、`numCtx`、`temperature`、`reasoningSetting`、`saveSettings` | 原生字段与主题菜单同步；连接/目录的迟到结果不能覆盖新编辑；不支持温度时以服务端事实为准，保存失败不会冒充成功。 |
| 认证：`chatgptLogin/Logout`、`claudeClientId`、`claudeConfigure/Login/Logout`、`providerApiKey`、`providerKeyConnect/Disconnect` | 显式连接/退出、Client ID 配置；UI 只呈现安全状态，不把凭据写到浏览器持久偏好或 Runtime 事实。认证失败由结果反馈。 |
| 子模型/报价：`poolEnabled`、`poolAdaptive`、`poolAdd`、`poolChildren`、`poolMainPricing` 与动态检查/连接/移除/刷新按钮 | 原字段保存子槽位和自定义报价；连接、能力、目录报价各自投影，缺测不当作免费。禁用/编辑/迟到响应由后续模型复核。 |

## 后续模型验收入口

先对本次改动补菜单轮询导航、原字段/fieldset/optgroup 禁用、全部禁用、输入建议确认后的焦点、对话框弹层退出、中文输入法 Escape/方向键，以及实测 0/缺失/部分覆盖的回归。

随后运行 `scripts/check_web.cjs` 与真实浏览器矩阵，逐张检查五宽度 × 双主题 × 状态；专项复核键盘闭环、40/44 px 命中、正文/控件各状态对比、离线字体/资源与减少动效。真实 HTTP/SQLite 固定 Provider 和真实 Provider 验证分开记录。当前没有本次变更的测试通过结论，完整任务边界见 [续跑记录](CONTINUATION_REVIEW.md)。
