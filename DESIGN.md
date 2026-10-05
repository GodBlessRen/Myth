---
name: Myth · 水墨太极工作台
description: 艺术机构的工作空间：安静、精确、有辨识度。
colors:
  paper: '#F8F4ED'
  surface: '#fffdf8'
  surface-2: '#f0ece4'
  sidebar-surface: '#f0ece4'
  inspector-surface: '#f4f0e9'
  ink: '#0E100F'
  ink-2: '#454d46'
  muted: '#646d64'
  line: '#c9c8bc'
  line-soft: '#dddbcf'
  selected: '#e5e4d9'
  selected-ink: '#303b31'
  accent: '#a44732'
  accent-hover: '#873822'
  accent-ink: '#fffdf8'
  signal: '#8b5626'
  signal-soft: '#f0e1c8'
  success: '#4e6658'
  success-soft: '#e1e8dc'
  danger: '#a63838'
  danger-soft: '#f7dfd9'
  unknown: '#875a21'
  unknown-soft: '#f4e4c5'
  focus: '#a44732'
  button-ink: '#fffdf8'
  paper-dark: '#0E100F'
  surface-dark: '#1b211d'
  surface-2-dark: '#252d27'
  sidebar-surface-dark: '#141915'
  inspector-surface-dark: '#141915'
  ink-dark: '#F8F4ED'
  ink-2-dark: '#d5dbd3'
  muted-dark: '#a9b3a9'
  line-dark: '#485249'
  line-soft-dark: '#303a31'
  selected-dark: '#303a31'
  selected-ink-dark: '#f3d6c4'
  accent-dark: '#e3a58b'
  accent-hover-dark: '#f0b89e'
  accent-ink-dark: '#0E100F'
  signal-dark: '#e1b878'
  signal-soft-dark: '#3b3024'
  success-dark: '#b1c7b4'
  success-soft-dark: '#2c382f'
  danger-dark: '#f0a7a0'
  danger-soft-dark: '#452a32'
  unknown-dark: '#e4bd85'
  unknown-soft-dark: '#423323'
  focus-dark: '#e3a58b'
  button-ink-dark: '#0E100F'
  taiji-outline: '#74786F'
typography:
  display:
    fontFamily: '"Myth Serif", "Myth Sans", serif'
    fontSize: 36px
    lineHeight: 1.55
    fontWeight: 400
    letterSpacing: -.025em
  headline:
    fontFamily: '"Myth Serif", "Myth Sans", serif'
    fontSize: 34px
    lineHeight: 1.5
    fontWeight: 400
    letterSpacing: -.025em
  brand:
    fontFamily: '"Myth Serif", "Myth Sans", serif'
    fontSize: 33px
    lineHeight: 1
    fontWeight: 400
    letterSpacing: -.03em
  body:
    fontFamily: '"Myth Latin", "Myth Sans", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 14px
    lineHeight: 1.65
  conversation:
    fontFamily: '"Myth Latin", "Myth Sans", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 15px
    lineHeight: 1.95
  label:
    fontFamily: '"Myth Latin", "Myth Sans", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 12px
    lineHeight: 1.65
  control:
    fontFamily: '"Myth Latin", "Myth Sans", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 12px
    lineHeight: 1.65
    fontWeight: 550
  inspector-title:
    fontFamily: '"Myth Latin", "Myth Sans", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 13px
    lineHeight: 1.65
    fontWeight: 550
  choice-option:
    fontFamily: '"Myth Latin", "Myth Sans", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: 13px
    lineHeight: 1.5
  code:
    fontFamily: '"Cascadia Code", "SFMono-Regular", Consolas, monospace'
    fontSize: 12px
    lineHeight: 1.8
rounded:
  choice-option: 4px
  action: 5px
  navigation: 6px
  field: 7px
  compact: 8px
  disclosure: 9px
  artifact: 10px
  composer: 12px
  composer-mobile: 14px
  dialog: 15px
  circle: 50%
spacing:
  control-gap: 7px
  small-gap: 8px
  navigation-gap: 12px
  list-gap: 16px
  section-gap: 20px
  panel-inset: 24px
  conversation-inset: 36px
  conversation-inset-mobile: 22px
components:
  button-primary:
    backgroundColor: '{colors.accent}'
    textColor: '{colors.accent-ink}'
    typography: '{typography.control}'
    rounded: '{rounded.action}'
    padding: 10px 15px
  button-primary-hover:
    backgroundColor: '{colors.accent-hover}'
  button-primary-dark:
    backgroundColor: '{colors.accent-dark}'
    textColor: '{colors.accent-ink-dark}'
  button-primary-dark-hover:
    backgroundColor: '{colors.accent-hover-dark}'
  button-secondary:
    backgroundColor: '{colors.surface}'
    textColor: '{colors.ink-2}'
    typography: '{typography.control}'
    rounded: '{rounded.action}'
    padding: 10px 15px
  button-secondary-hover:
    backgroundColor: '{colors.surface-2}'
    textColor: '{colors.ink}'
  button-text:
    textColor: '{colors.ink-2}'
    typography: '{typography.label}'
    padding: 5px 2px
  button-new-chat:
    backgroundColor: '{colors.ink}'
    textColor: '{colors.button-ink}'
    rounded: '{rounded.navigation}'
    padding: 12px
  input-field:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.ink}'
    typography: '{typography.label}'
    rounded: '{rounded.field}'
    padding: 8px 11px
  navigation-item:
    textColor: '{colors.ink-2}'
    rounded: '{rounded.navigation}'
    padding: 10px 12px
  navigation-item-active:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.ink}'
  attachment-chip:
    backgroundColor: '{colors.surface}'
    typography: '{typography.label}'
    rounded: '{rounded.compact}'
    padding: 6px 9px
  artifact-card:
    backgroundColor: '{colors.surface}'
    rounded: '{rounded.artifact}'
    padding: 15px
  composer:
    backgroundColor: '{colors.surface}'
    rounded: '{rounded.composer}'
    padding: 20px 18px 12px
  evidence-heading:
    textColor: '{colors.ink}'
    typography: '{typography.inspector-title}'
  choice-trigger:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.ink}'
    typography: '{typography.body}'
    rounded: '{rounded.navigation}'
    padding: 9px 34px 9px 12px
  choice-listbox:
    backgroundColor: '{colors.paper}'
    textColor: '{colors.ink}'
    typography: '{typography.choice-option}'
    rounded: '{rounded.compact}'
    padding: 5px
  choice-option:
    rounded: '{rounded.choice-option}'
    padding: 10px 28px 10px 10px
  choice-option-active:
    backgroundColor: '{colors.selected}'
    textColor: '{colors.selected-ink}'
  ink-brand:
    width: 56px
    height: 24px
  ink-workspace:
    width: 56px
    height: 24px
  ink-collapsed:
    width: 36px
    height: 24px
  taiji-waiting:
    width: 14px
    height: 14px
---

# Design System: Myth · 水墨太极工作台

## Overview

**Creative North Star: "艺术机构的工作空间"**

安静、精确、有辨识度。界面用真实中文字体、宽松的工作面与清楚的细线组织内容；标题承担身份，控件承担操作，状态文字承担事实。奶油白与星空黑是固定的两种地色，原纸构首屏已移除。

空间如可展开的装帧：导航、会话、观测具有不同阅读密度，用户可显式折叠或进入专注。静态身份是一笔连贯的水墨太极波浪 M；微型几何太极只表达真实等待。主题与布局只拥有浏览器偏好，Runtime 的执行和验收事实继续由后端投影。

**Key Characteristics:**

- 黑白地色、轻边界、克制的赭色动作与焦点。
- 本地中文字体，标题与操作文字有明确角色。
- 三栏可展开，正文与输入区共用阅读边线。
- 水墨身份保持黑白与透明边缘，运动严格对应真实等待。

本记录于 2026-10-06 按用户已确认的水墨身份和模型设置刷新。依据为 [工作台合同](.impeccable/surfaces/workbench.md)、[最终审查](output/playwright/ink-design-review.md)、当前源码与该审查列明的十二张最终截图，基线为 `origin/main 78487c2`。最终 disposition 为 **ship**；身份小尺寸对比和停用温度遗留值两项问题均 **resolved**。本次文档更新没有修改界面或重新执行 QA；源码与资产哈希见 sidecar。

## Colors

前置 YAML 是颜色的规范值。无后缀键对应浅色 CSS 变量；`-dark` 键对应 `data-theme="dark"` 的同名变量替换。相同字面值的不同键保留源码语义，主题绑定记录在 sidecar。

### Primary

- **赭色动作**（`accent` / `accent-dark`）：主按钮、发送、当前导航图标、选中观测角度与输入焦点。悬停使用对应 `accent-hover`，文字使用 `accent-ink`。
- **焦点**（`focus`）：键盘轮廓、文本光标与原生控件强调，随主题切换。

### Neutral

- **奶油白 / 星空黑地色**（`paper`）：全页背景；双主题中的正文 `ink` 与之互换。
- **操作表面**（`surface`）：输入框、表单面板、代码及 Artifact 容器；`surface-2` 承担次级填充与悬停。
- **侧栏 / 观测栏**（`sidebar-surface` / `inspector-surface`）：区分工作面的密度，不靠装饰纹理。
- **正文 / 次级 / 辅助**（`ink` / `ink-2` / `muted`）：用途分层；辅助文字仍承担可读的信息。浅色 `muted` 保留本轮已修复的规范值。
- **边界**（`line` / `line-soft`）：输入与主要分组使用前者，轻分隔使用后者。
- **选择**（`selected` / `selected-ink`）：文字选区与命令结果选择。
- **微型太极轮廓**（`taiji-outline`）：只属于等待 SVG 外圈。水墨身份的黑白颜料不随主题反相，小尺寸 alpha 轮廓使用主题 `ink-2`。

### State colors

`signal`、`success`、`danger`、`unknown` 及各自 `-soft` 是真实状态的现有表达。UNKNOWN 保留独立的文字与颜色，执行结束与独立验收分开显示；颜色不创造进度或成功事实。

## Typography

**Display Font:** Noto Serif SC，本地别名 `Myth Serif`；静态标题子集未覆盖的字形回退 `Myth Sans`。

**Body Font:** Manrope（`Myth Latin`）与完整字符表 Noto Sans SC（`Myth Sans`），均以本地 WOFF2 提供。

**Code Font:** 源码中的系统等宽栈 `Cascadia Code / SFMono-Regular / Consolas`。

宋体用于首页、页面标题与 Myth 字标；正文、标签、数字和交互使用无衬线。三个本地字体声明覆盖字重（400–650），不开第三方字体请求；出处与 SIL OFL 见 [字体说明](src/myth/webui/fonts/README.md)。

### Hierarchy

- **Display / Headline / Brand**：分别对应首页题句、页面标题与字标；字体、字号、行高和字距按前置令牌应用。
- **Body / Conversation**：界面正文与长回答分开；回答拥有更松的行高，并允许长内容换行。
- **Label / Control / Inspector title**：辅助信息、按钮与表单标签、观测分组的密度角色；不把中文控件强制全大写。
- **Choice option**：统一选择菜单的行文字；活动项使用选择色，禁用项保留辅助文字色。
- **Code**：代码块正文；路径与部分指标使用同一等宽栈，但各自保持源码已有行高。数值事实使用 tabular-nums。

响应值来自现有 CSS：首页标题在（800px）以下为（29px）；页面标题依次为（30px）与（28px）；手机回答为（14px），输入为（16px）。这些是响应替换，不增设虚构字号比例。

## Layout

工作台为全高原生 CSS Grid，三栏默认宽度（224px / minmax(0,1fr) / 304px），导航、正文与观测可独立滚动。左右折叠轨道均为（68px）。桌面专注在进入时保存两栏状态，退出恢复原状态及现有草稿；正文容器由（790px）扩展至（900px）。

会话正文与输入区共同使用 `conversation-width` 和 `conversation-inset`，目录宽度扣除同一双侧内边距。默认边距与手机替换见 spacing 令牌；不要给正文与输入各自另设宽度。

响应组织按实际断点：

- （1380px）及以下调整顶栏密度与设置分栏。
- （1120px）及以下观测转右侧抽屉，专注入口与桌面观测折叠按钮隐藏。
- （800px）及以下导航也转抽屉，顶栏为（58px），正文与输入保持共同边线。
- （520px）及以下输入工具栏分两行，主要图标和发送目标为（44px），表单面板纵向组织。
- 低于（620px）视口高度时，空白会话首屏从顶部开始布局，输入保持可达。

间距令牌是源码中真实的用途值，并非一套推断出的通用等差比例。手机输入区保留 safe-area-inset-bottom；窄屏继续通过明确入口访问完整 Runtime。

## Elevation & Depth

常驻三栏、列表和输入表面以底色、细线与排版区分深度。实际阴影只用于 dialog、命令面板、打开的移动抽屉和 toast；不给静态列表补加悬浮层。浅色与深色 dialog / 抽屉各用源码 `shadow`，toast 有独立小阴影；精确值由 sidecar 的 shadows 记录。

选择列表在原生 Popover 顶层使用 paper 底色、细边界和轻圆角，没有另加阴影。水墨身份四方向（.3px）、零模糊的 `drop-shadow` 从实际 alpha 导出细轮廓，用于双主题可辨识度，不承担浮起或装饰光晕。

dialog 原生 backdrop 使用源码半透明颜色，dialog 进入为（210ms）；抽屉进出为（240ms）。本系统没有另行定义模糊玻璃、装饰渐变或卡片阴影框架；主题选项中的系统预览是已有主题示意。

## Shapes

小圆角服务控件，较大的圆角服务输入与弹窗；对应 action、navigation、field、compact、artifact、composer、dialog 令牌。列表依靠横向分隔，面板与 Artifact 才使用边界容器。发送、停止与真实状态点保持圆形。

静态身份使用内置生成的透明 `ink-taiji.png`（1918×820，RGBA）：左黑、右奶油白，恰好两只相反颜色的鱼眼水平对齐。用户要求原构图旋转（180°），再把中央阴阳分界的两端延展成波浪 M；记录当前可见结果，不把提示词当作精确像素旋转证明。品牌与工作空间为（56×24px），折叠轨道宽度为（36px）；不添加圆形衬底、框或新装饰场景。精确生成提示词同时保存在 PNG `impeccable:prompt` 和同名 JSON sidecar。

等待保持 `taiji.svg` 的（32×32）viewBox 几何，在（14px）下使用；静态身份不再受旧圆形双鱼比例规范约束。

## Components

### Buttons

主按钮、次按钮与文字按钮保持清楚的操作层级。主动作使用赭色；新建对话沿用黑白反转；次按钮使用表面、细边界与次级文字。按钮悬停使用现有色值，按下位移（1px），禁用透明度（.42）。全局键盘轮廓为 focus 色（2px），按钮偏移（3px）。主/次按钮最小高度（40px），手机主要入口按已有命中区扩大。

### Inputs / Fields

标签独立于占位文字。普通字段为 paper 背景、line 边界、field 圆角，最小高度（38px）；键盘焦点轮廓偏移（2px）。子模型新槽位继承主模型提供方，服务地址与上下文窗口仅在 Ollama 出现；远端字段按其真实能力显示，不复制无效的本地参数。

统一选择器保留原 select / input 为值来源，触发器和 Listbox 只负责视图。触发器常规最小高度（42px），菜单选项（38px）；（800px）以下二者均为（44px）。菜单属于原 dialog 或 body，视口边缘留（12px），必要时向上打开。方向键、Home / End、Enter、Tab、Escape 和前缀输入可用；可编辑模型字段保留自由输入与目录建议。Escape 先关菜单，再交还所属 dialog；移除源字段同时清理菜单。

### Model settings / Pricing

主模型与子模型用独立数值边界：步骤分别为（2–32 / 1–8），每步输出 Token 分别为（128–393216 / 128–32768），Ollama 上下文为（2048–262144）；模型能力或目录上限可进一步收紧输出范围。温度说明稳定性与多样性，通常为（0–2），Claude 为（0–1）。普通 OpenAI API 模型传递温度，推理模型与 OAuth 使用默认采样；新 Claude 模型省略已停用的采样参数。控件停用时回到（0），避免切换提供方后保存被不可编辑的超界值阻挡。

Thinking 只提供当前模型声明或发现的原生选项；帮助文字说明增加推理通常更耗时、更耗输出 Token。未知能力保持默认或显示已保存值，不构造跨模型通用的强度数字。

主/子模型按提供方与精确模型 ID 自动查询公开标价，行分隔组织百万 Token 单位、来源、查询时间、过期状态与提供方说明。可折叠的合同覆盖默认关闭，开启后才输入自定义单价。未收录、查询失败、未公布、订阅、本地/自托管渠道各自说明；缺失或目录零占位保持未知，不显示为免费。截图费率是夹具；标价只是估算且未计缓存折扣。查询在业务事务外完成，新 Run 冻结已解析设置，目录更新不改写在途或恢复 Run 的价格快照。

### Navigation

工作、资料、最近对话为可展开的原生 details 分组；当前页面以 paper 底色、较重文字和赭色图标明确标出。折叠后入口留在轨道内；手机变为有焦点边界、可关闭的抽屉。问题目录只引用真实用户消息身份，定位后把焦点移到对应消息，不提交消息或创建 Run。

### Chips / Cards

附件 chip 使用轻边界与 compact 圆角，移除是独立按钮。Artifact 卡以文件图标、名称、格式与下载入口表达已有产物；下载不是验收成功。其他列表保留行分隔，避免每条短文本重复套卡。

### Composer

输入框与回答严格同边线；独立显示附件、项目、Goal 和发送。聚焦时边界转赭色，并在底部增加（1px）线。桌面输入字体与手机替换按 Typography；最大输入高度（240px），超出内部滚动。切换专注或观测角度不改写草稿。

### Observatory

概览、执行、资源是同一组权威事实的三个阅读角度，tab 支持方向键与 Home / End；非活动面板退出焦点顺序。选中标签以（2px）底线表示，证据类别可独立折叠。展开箭头（180ms），视角切换（180ms），空间重分配（260ms），均沿用源码 ease-out。折叠、主题与视角偏好只存 localStorage。

### Ink identity / Waiting

水墨品牌静止，主题不反相资产颜料。在线 Driver 的真实工作、载入会话请求、连接检查与凭据验证在途状态可使用微型等待太极；相邻文字说明具体事实，图标 aria-hidden。等待匀速（2.6s）转一周；prefers-reduced-motion 时静止，其他过渡与动画也关闭。运动不证明 durable progress。

## Do's and Don'ts

### Do:

- **Do** 使用前置令牌的固定双主题地色和源码主题变量。
- **Do** 使用本地中文字体，保持标题、正文、标签的已有角色。
- **Do** 让正文、目录与输入区共用阅读宽度及双侧边距。
- **Do** 保留可撤销的专注布局、草稿与折叠入口。
- **Do** 用真实状态文字区分执行、UNKNOWN、交付与独立验收。
- **Do** 仅让真实等待太极转动，并遵守 reduced motion。
- **Do** 使用实际水墨 PNG、水平双眼和 alpha 细轮廓；生成来源随资产保留。
- **Do** 保留模型原生选项、有效数值边界和有来源及时间的价格状态。

### Don't:

- **Don't** 重新引入已移除的纸构首屏或旧墨紫地色。
- **Don't** 给静态列表补装饰图片、口号墙或新阴影体系。
- **Don't** 把水墨品牌替换回旧几何徽章、添加衬底，或让静止品牌持续旋转。
- **Don't** 用主题、动画或浏览器偏好创建 Run、扩大授权、补造指标。
- **Don't** 翻译未知后端内容；已知标签可中文化，未知值原样保留。
- **Don't** 向远端子模型显示 Ollama 专用地址与上下文窗口字段。
- **Don't** 把未知价格或目录零占位表达为免费，也不要用公共标价改写历史 Run。
