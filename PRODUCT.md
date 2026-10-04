# Myth 产品事实

<!-- impeccable:product-schema 1 -->

## Platform

web

## 用户与任务

面向在本机推进项目、资料与长期任务的使用者；这是依据当前仓库工作流作出的产品定位，不代表已完成用户研究。核心任务是创建或继续会话，绑定项目、资料或 Goal，观察执行证据，并在等待或中断后作出下一步决定。

## 产品目的

Myth 是本地 Agent Runtime。Goal 可跨 Session 保存状态、下一步与等待项；Run 的持续性不依赖浏览器页面一直打开。完成以 Artifact、Receipt、Verification 等证据为依据，模型自述不构成完成证明。

## 使用环境

- Python 3.12+ 服务提供浏览器工作台；前端使用原生 HTML、CSS、JavaScript，无前端构建链。
- 通过 `myth --root . web` 或 `start-myth.ps1` 启动；默认本地地址为 `http://127.0.0.1:8765/`。
- 支持 Ollama、OpenAI / DeepSeek API Key 与 Myth 自有 ChatGPT OAuth；按供应商目录显示模型与 Thinking 选项，连接状态以实际探测结果为准。
- 当前没有任意 shell、通用代码执行、系统常驻服务、多用户权限或分布式 worker。

## 必须保留的能力

会话与多轮对话、项目、知识检索与来源、长期 Goal 与计划、附件、Artifact 下载、模型与连接设置、Steer / Pause / Resume / Stop / Compact、Runtime 观测与恢复入口。计划由 Executor 检查到期机会并执行正常 admission；打开页面不构成新授权。

Runtime Observatory 是产品主界面的一部分，保留 Goal、Execution Flow、Recovery、Trajectory、Tokens、Cache Hit、Context、Tools、Control、Budget；会话统计、Delivery、SOTA Route 与 Provider Evidence 继续保留。窄屏通过明确入口访问同一批事实。

## 品牌与语言约束

用户于 2026-10-04 明确委托完整前端重新设计：简洁、专业，奶油白与星空黑双主题；整体简体中文，已定义的专业名词保留英语；减少口号与装饰文案。视觉细节由本次设计工作自行决定。具体视觉合同见 [DESIGN.md](docs/DESIGN.md)。

## 产品原则

1. Goal、Prompt、Memory 与模型输出都不能扩大权限。
2. UNKNOWN 与已知失败分开表达；UNKNOWN 先 RECONCILE，INTERRUPTED 按事实提供 RESUME。
3. Executor heartbeat、Driver heartbeat 与 durable progress 分开显示。
4. 缺失计量显示“未报告”或 `N/A`，不补造 Token、缓存命中、进度或交付证据。
5. 视觉简化不删减既有能力；界面重构保留后端事实口径，后端合同修改必须单独验证状态、授权、恢复与计量。

## 证据与开放事项

产品事实来自 [README](README.md)、[AGENTS.md](AGENTS.md)、[观测合同](docs/OBSERVABILITY.md) 与 `src/myth/webui/`；这些描述不等于真实 Provider 稳定性已经验证。设计偏好来自用户明确要求。尚未确认的用户画像、商用承诺和生产规模不在本记录中补写。
