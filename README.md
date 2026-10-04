# Myth

**一个可持续推进真实工作的本地 Agent Runtime。**

Myth 的中心不是“聊天 + 一堆 Agent 概念”，而是：

```text
Long-term Goal
  -> Current State
  -> Next Action
  -> admitted Turn
  -> Observe / Act / Verify
  -> durable checkpoint
  -> later Session
  -> continue the same Goal
```

当前版本：**v0.23.0**

登录、密钥边界、逐模块审查和本地性能对照见 [安全与性能审查](docs/SECURITY_PERFORMANCE_AUDIT.md)。

## 现在能做什么

- 多轮 Conversation + Agent Loop；
- 长期 Goal 跨 Session / restart 保存进度、下一步与等待项；
- Goal 一次性 Timer / 固定间隔计划，服务运行时通过正常 admission 唤醒工作；
- 固定日常任务基线与逐次证据报告，支持真实 provider 和简单 Loop 路由对照；
- Steer / Pause / Resume / Stop / Compact；
- Ollama，本地上下文窗口与 `num_ctx` 对齐；
- Knowledge / Memory 检索与 provenance；
- project.read / search、diff.preview、git.status / diff；
- Artifact 生成与固定对象下载；
- durable Ticket / Receipt / UNKNOWN / Recovery；
- durable Execution Cursor + Driver Lease / Heartbeat，页面或 Driver 中断后可从 checkpoint 恢复；
- [断网恢复](docs/NETWORK_RECOVERY.md)：保存同一 Run，按 1、2、4、8、16、32、60 秒重连，之后每分钟一次；已派发而结果不明的调用先核对；
- [会话统计](docs/SESSION_STATISTICS.md)：模型/工具累计用时、平均 TTFT 和端到端 TPS，刷新/重启复用实测计量；
- 固定 EvalSuite、Eval Ledger、Policy Candidate / Promote / Rollback；
- 三栏工作台，第三栏常驻 Runtime Observatory。

当前**没有**任意 shell、通用代码执行、操作系统常驻服务、多用户权限或分布式 worker。

## 产品不变量

1. **Goal continuity**
   - 长期 Goal 的状态必须跨会话持久化。
   - 历史 Turn 的 Goal snapshot 不被未来更新倒写。

2. **Runtime observability**
   - 第三栏不是可删除的 Debug Panel。
   - 每个有意义的 Run 必须可观察：
     Goal / Execution Flow / Recovery / Trajectory / Tokens / Cache Hit / Context / Tools / Control / Budget。

3. **Authority boundary**
   - Goal / Memory / Prompt / Model output 都不能扩大权限。
   - 外部效果仍受 Capability / Ticket / Receipt / Verification 约束。

4. **Interruption is recoverable**
   - Browser / Web request / Driver 生命周期都不能等于 Run 生命周期。
   - 每个有意义的执行阶段必须有 durable cursor / checkpoint。
   - 安全中断进入 INTERRUPTED / RESUME；外部结果不明确才进入 UNKNOWN / RECONCILE。

5. **UNKNOWN is first-class**
   - 结果不明先 reconcile，不盲目 replay。
   - 已知失败与未知结果必须分开。

6. **Completion needs evidence**
   - 模型说“完成”只是 proposal。
   - Artifact / test / receipt / external state 才能支撑完成声明。

## Quick Start

要求 Python 3.12+。核心 Runtime 仍以标准库为主；原生 ChatGPT OAuth 额外使用 PyJWT/cryptography 做 OIDC 验证、keyring 对接系统安全凭据库。无前端构建链、CDN 或外部数据库服务。

```bash
python -m pip install -e .
myth --root . web
```

Windows：

```powershell
.\start-myth.ps1
```

打开：

```text
http://127.0.0.1:8765/
```

一般对话默认使用本机 Ollama；也可选择 OpenAI、DeepSeek 或 Myth 自己实现的 **Sign in with ChatGPT**。远端模型连接都在 Myth 设置页完成：OpenAI / DeepSeek 直接粘贴 API Key，验证成功后只保存到操作系统安全凭据库；ChatGPT 直接走 OAuth。正常用户不需要预先打开 PowerShell 设置环境变量。旧的 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` 仅作为兼容回退。

页面可配置：

- Ollama 地址；
- 模型；
- `num_ctx`；
- temperature；
- max steps；
- max output tokens；
- thinking。

Myth 不自动下载本地模型。OpenAI / DeepSeek API Key 与 ChatGPT OAuth 凭据都通过 Myth 应用内连接，并保存在系统安全凭据库，不写入 Runtime 数据库、事件、Artifact 或日志。API Key 候选值先验证成功再替换旧凭据，粘贴错误不会破坏原有可用连接。

## 工作台

```text
History / Context | Conversation / Task | Runtime Observatory
```

左栏管理会话、项目和上下文；中栏完成工作；第三栏持续显示：

- Goal；
- Execution Flow；
- Trajectory；
- Token Window；
- Prompt Cache Hit；
- Context Window；
- Tool Calls；
- Control；
- Budget。

详见 [Observability Contract](docs/OBSERVABILITY.md)。

在「目标与计划」中创建 Goal、选择工作会话和时间，保存一次性或固定间隔计划。模型设置在保存计划时固定；未完成的会话/Goal 会等待，断连会重试。关闭 Web 服务期间不执行；重启后重复计划的错过时段合并为一次。窄屏可通过顶部 Runtime 按钮打开完整观测面板。

计划用法和验证命令见 [Goal Wake-up](docs/GOAL_WAKEUP.md) 与 [Task Benchmark](docs/TASK_BENCHMARK.md)。

## Runtime shape

稳定 Core：

```text
Goal -> Run -> Action -> Attempt -> Ticket -> Receipt -> Artifact -> Verification
```

正交 Domains：

```text
Coordination / Control / Execution / Capability / State
Context / Memory / Personal State / Observability
Evaluation / Evolution
```

Intent Pick、Information Resolution、Agent Loop、Workflow、Routing、Multi-Agent 等属于可插拔 Strategy，不是固定 Layer。

详细说明见 [Architecture](docs/ARCHITECTURE.md) 与 [Architecture Constitution](docs/ARCHITECTURE_CONSTITUTION.md)。

## 当前开发主线

暂停横向堆 Multi-Agent / A2A / 更多 Evolution 抽象。

接下来优先：

1. 用固定的 10 个日常任务继续积累真实模型失败；
2. 根据证据补 Tool / Context / Memory；
3. 受限 `test.run`，让代码类任务可以验证候选改动；
4. 连续自用与计划故障注入，再决定高级架构是否值得深化。

详见 [Roadmap](docs/ROADMAP.md)。

## 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
node --check src/myth/webui/app.js
node --check src/myth/webui/inspector.js
node --check src/myth/webui/goals.js
```

自动测试大量使用 deterministic provider / test doubles；不能据此宣称真实模型稳定性。当前验证边界见 [VALIDATION.md](docs/VALIDATION.md)。

## 文档地图

- [docs/README.md](docs/README.md) — 文档导航
- [AGENTS.md](AGENTS.md) — 开发 / Agent 工作规范
- [CHANGELOG.md](CHANGELOG.md) — 版本演进
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — 当前架构事实
- [ARCHITECTURE_CONSTITUTION.md](docs/ARCHITECTURE_CONSTITUTION.md) — 稳定边界
- [CODE_GUIDE.md](docs/CODE_GUIDE.md) — 中文源码阅读、状态所有权与原子性边界
- [OBSERVABILITY.md](docs/OBSERVABILITY.md) — 第三栏观测合同
- [DESIGN.md](docs/DESIGN.md) — 产品视觉与交互原则
- [ROADMAP.md](docs/ROADMAP.md) — 下一步
- [SECURITY.md](SECURITY.md) — 安全边界
