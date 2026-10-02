# Myth

**Durable Runtime 打底、Agent Product 向上生长的本地 Agent 平台。**

v0.10 新增 **Intent Pick + Information Resolution / Delta / Gain** 的纯领域合同与 Ports。Intent Pick 用于在昂贵推理前选择 direct / local retrieval / deterministic / agent / ask-user 等路径；Information Resolution 恢复为“信息分辨率”原义：L0 Abstract → L1 Overview → L2 Detail/Evidence；Delta 描述信息状态变化；Gain 描述在已有信息上的边际任务价值。当前这些均只标记为 `exists`，尚未假装已经接管主请求、物化多分辨率视图或拥有校准 Gain estimator。

v0.9 把架构从“阶段/层级栈”重构为 **Core + Domains + Strategies + Ports/Adapters**：Goal / Run / Action / Attempt / Ticket / Receipt / Artifact / Verification 作为稳定 Core；Coordination / Control / Execution / Capability / State / Context / Memory / Personal State / Observability 作为正交 Domain；Decision / Routing / Workflow / Multi-Agent / Managed Agent / Personal Agent 作为可插拔 Strategy。新增 Goal / Trigger / Personal State 持久化入口，为长期 Personal Agent 留出真实边界；产品与新代码统一使用 Stop，旧 `abort` 仅作为升级兼容入口保留，不再作为产品术语。

v0.8 把 Product Control 真正接入主链：Steer / Pause / Resume / Stop / Model Switch / Thinking Switch / Compact 全部持久化并在安全点生效；Memory 变成带 revision 的本地持久层；Agent 新增 project.search / diff.preview / git.status / git.diff 四个受 Capability Registry 约束的只读编码能力。右侧 Runtime Inspector 现在直接显示 Control revision、Tool Ticket、Operation state、Budget、Memory 与 Event 数量。

v0.7 在 breadth-first 平台骨架上重做产品工作台：对话保持中心，Projects / Knowledge 退到上下文层，右侧 Runtime Inspector 用 Decision → Authority → Result → Completion 展示当前轮的真实执行事实。视觉系统改为暖纸张 / 墨色 / 克制橙色，并直接重构 tokens / layout / components，而不是继续追加 CSS override。

v0.6 开始采用 breadth-first 路线：不再只把单一功能磨深，而是先固定完整平台骨架。这一阶段完成了 breadth-first 骨架铺设；v0.9 已把它重构为 Core / Domains / Strategies / Adapters 的可组合结构。

**Runtime** 视图直接展示 Core / Domains / Strategies / Adapters 与当前真正 executable 的 Capability；成熟度只描述实现程度，不授予执行权限。完整地图见 [PLATFORM_MAP](docs/PLATFORM_MAP.md)，命名与边界见 [Architecture Constitution](docs/ARCHITECTURE_CONSTITUTION.md)。

## 启动

Python 3.12+，运行时仅使用标准库，无前端构建、CDN 或数据库服务。

```bash
python -m pip install -e .
myth --root . web
```

Windows 在仓库目录运行：

```powershell
.\start-myth.ps1
```

打开 `http://127.0.0.1:8765/`。先启动本机 Ollama；页面自动检测 `http://127.0.0.1:11434` 并选择一个已安装模型，也可在「模型与设置」改地址、模型和本轮限制。Myth 不自动下载模型，不保存 API 密钥。

源码入口无需安装：

```powershell
$env:PYTHONPATH = 'src'
python -m myth.cli --root . web
```

## 如何使用

| 页面 | 已实现 |
| --- | --- |
| 对话 | 普通问答、多轮上下文、Markdown/代码展示、Steer/Pause/Resume/Stop、当前轮模型/Thinking 热切换、Compact、附加资料、工具记录与文件下载 |
| 会话管理 | 搜索、重命名、置顶、所属项目、归档与恢复、Markdown 导出 |
| 项目 | 创建/编辑、共同指令、关联本地目录、文件树、项目对话与专属资料 |
| 知识库 | 导入 UTF-8 文本或粘贴内容、分块索引、共享/项目范围、关键词搜索、来源预览与移出索引 |
| Runtime | Core / Domains / Strategies / Adapters 成熟度、Capability Registry 与执行边界；右侧 Inspector 展示 Control revision、Ticket、Operation、Budget、Memory、Event facts |
| 模型与设置 | Ollama 连接检查、已安装模型、输出/步数限制、思考开关 |

先创建一个项目，填入本地目录并添加指令。导入一份资料，再点「开始对话」，例如：

```text
根据学习约定，每天学习多久？
请读取项目文件 README.md，概括主要功能。
把我们的讨论整理成学习计划，生成 study-plan.md 供我下载。
```

普通讨论也可以选择「独立对话」。文件生成成功后，回答下方出现实际下载卡片；每版下载来自固定摘要的不可变对象。任意回答可另外保存为 Markdown。

文本文件上限 1 MB；每条消息最多附加 4 份资料。项目文件仅支持 UTF-8，Agent 输出到受管会话目录，项目原文件保留。Agent 可搜索项目、预览 Diff、读取 Git status/diff；仍没有任意 shell 或代码执行工具。模型的规划能力会影响连续工具调用，较小模型可能提前回答或生成错误参数；错误会显示在执行记录中并消耗本轮步数。

## Loop、上下文与检索

对话循环是「固定入口 → 持久模型请求 → 决策校验 → 工具授权/收据 → 下一步」，可以直接回答或向用户提问。会话消息持久保存；最近 30 条历史作为候选，与召回资料/记忆、旧工具预览共同按 42,000 字节消息预算选入。本轮原始任务、澄清、显式附件片段和最新工具结果优先保留；Compact 只减少旧历史，完整记录仍在本地。Inspector 展示实际字节和取舍数量。必需内容超过预算会在调用前停止。完成的普通对话会写入本地 Episodic Memory；Semantic/Procedural/Working Memory 已有持久 revision API。下一轮会按当前用户问题做关键词召回并固定进 Turn Snapshot。

知识库按 1,800 字符分块、200 字符重叠，英文词与中文双字关键词排序；本轮只检索共享资料和当前项目资料。检索结果保留文档、片段与来源标识，来源可点击查看。当前没有向量检索、重排器或 PDF/Office 解析器；Keyword Retrieval 仍是可复现 baseline。

模型发出执行 Ticket 后结果不明，则保留 UNKNOWN 与预算占用；续跑先对账，不重复未知调用。已持久化的模型收据、文件摘要与工具结果可恢复。SQLite 保证账本事务，不把外部效果宣称为 exactly-once。

## 精确验收模式

原有文件精确替换用例继续保留在 CLI 与 `/api/runs`，要求固定完整目标摘要和独立验收，成功才生成验收交付：

```bash
myth --root . agent --provider scripted --model exact-patch-demo --allow-file examples/example.txt --acceptance examples/acceptance.json "Replace foo with bar"
```

对话轮次 COMPLETED 表示完成一次回答；可下载输出证明文件已实际生成，**不表示自然语言目标已通过独立语义验收**。两种完成边界分别记录，通用聊天不会借用精确替换的验收结论。

OpenAI Responses / Pi OAuth 适配器保留，远端凭据通过进程环境或 Pi 管理。本轮只实测本地 Ollama，未验证这两个远端入口。选择远端模型会向其发送选定的对话与资料。

## 验证与架构

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
node --check src/myth/webui/app.js
```

领域逻辑 → 应用用例 → 事务级端口 → SQLite/本地执行/模型适配器；Workspace 负责装配，HTTP 与页面负责交互。部分早期 Durable Runtime 实现仍在逐步迁移到统一 Ports。详见 [架构](docs/ARCHITECTURE.md)、[设计](docs/DESIGN.md)、[验证](docs/VALIDATION.md)、[规划](docs/ROADMAP.md)、[整体诊断与上下文优化](docs/REVIEW_2026-10-03.md) 与 [安全边界](SECURITY.md)。
