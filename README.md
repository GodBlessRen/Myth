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

当前版本：**v0.19**

## 现在能做什么

- 多轮 Conversation + Agent Loop；
- 长期 Goal 跨 Session / restart 保存进度、下一步与等待项；
- Steer / Pause / Resume / Stop / Compact；
- Ollama，本地上下文窗口与 `num_ctx` 对齐；
- Knowledge / Memory 检索与 provenance；
- project.read / search、diff.preview、git.status / diff；
- Artifact 生成与固定对象下载；
- durable Ticket / Receipt / UNKNOWN / Recovery；
- 固定 EvalSuite、Eval Ledger、Policy Candidate / Promote / Rollback；
- 三栏工作台，第三栏常驻 Runtime Observatory。

当前**没有**任意 shell、通用代码执行、后台自主调度、多用户权限或分布式 worker。

## 产品不变量

1. **Goal continuity**
   - 长期 Goal 的状态必须跨会话持久化。
   - 历史 Turn 的 Goal snapshot 不被未来更新倒写。

2. **Runtime observability**
   - 第三栏不是可删除的 Debug Panel。
   - 每个有意义的 Run 必须可观察：
     Goal / Execution Flow / Trajectory / Tokens / Cache Hit / Context / Tools / Control / Budget。

3. **Authority boundary**
   - Goal / Memory / Prompt / Model output 都不能扩大权限。
   - 外部效果仍受 Capability / Ticket / Receipt / Verification 约束。

4. **UNKNOWN is first-class**
   - 结果不明先 reconcile，不盲目 replay。
   - 已知失败与未知结果必须分开。

5. **Completion needs evidence**
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

一般对话默认使用本机 Ollama；也可选择 OpenAI API Key 或 Myth 自己实现的 **Sign in with ChatGPT**。ChatGPT OAuth 不依赖 Pi/Codex 的认证文件或 CLI，Token 只进入系统安全凭据库，不进入项目 Runtime 数据库。

页面可配置：

- Ollama 地址；
- 模型；
- `num_ctx`；
- temperature；
- max steps；
- max output tokens；
- thinking。

Myth 不自动下载模型。OpenAI API Key 只从环境变量读取；ChatGPT OAuth 凭据使用系统安全凭据库，并支持刷新、撤销和显式退出。

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

1. 10 个真实日常任务 × 重复运行；
2. 根据真实失败补 Tool / Context / Memory；
3. 最小 Timer / Schedule，只负责唤醒 due Goal；
4. 受限 `test.run`，让代码类任务可以验证候选改动；
5. 连续自用，再决定高级架构是否值得深化。

详见 [Roadmap](docs/ROADMAP.md)。

## 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
node --check src/myth/webui/app.js
node --check src/myth/webui/inspector.js
```

自动测试大量使用 deterministic provider / test doubles；不能据此宣称真实模型稳定性。当前验证边界见 [VALIDATION.md](docs/VALIDATION.md)。

## 文档地图

- [docs/README.md](docs/README.md) — 文档导航
- [AGENTS.md](AGENTS.md) — 开发 / Agent 工作规范
- [CHANGELOG.md](CHANGELOG.md) — 版本演进
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — 当前架构事实
- [ARCHITECTURE_CONSTITUTION.md](docs/ARCHITECTURE_CONSTITUTION.md) — 稳定边界
- [OBSERVABILITY.md](docs/OBSERVABILITY.md) — 第三栏观测合同
- [DESIGN.md](docs/DESIGN.md) — 产品视觉与交互原则
- [ROADMAP.md](docs/ROADMAP.md) — 下一步
- [SECURITY.md](SECURITY.md) — 安全边界
