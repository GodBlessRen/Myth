# Validation

这份文档只说明**当前怎么验证**以及**当前验证不能证明什么**。历史验证记录见 [archive/VALIDATION_HISTORY.md](archive/VALIDATION_HISTORY.md)。

## 自动检查

PR / 本地至少运行：

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
node --check src/myth/webui/app.js
node --check src/myth/webui/inspector.js
node --check src/myth/webui/goals.js
```

根据改动范围增加专项检查：

- Runtime / recovery → crash / UNKNOWN；
- Intent / routing → adversarial cases；
- Provider / Context → window / truncation / usage；
- Auth / OAuth → PKCE/state/nonce、OIDC signature/audience/issuer、secure storage、refresh/revoke、callback log leakage；
- Goal / Personal → cross-session / restart；
- Timer / Schedule → atomic admission、跨连接争抢、commit 后进程退出、断连重试、暂停、UNKNOWN no replay；
- UI → Runtime Observatory surface contract；
- Evaluation / Evolution → complete-suite release evidence。

## 自动测试覆盖的核心边界

- durable Run / Attempt / Ticket / Receipt；
- model / tool UNKNOWN 不盲 replay；
- crash 后恢复与预算结算；
- Control revision / Pause / Resume / Stop；
- scoped Memory；
- Knowledge / project retrieval coverage；
- Intent adversarial routing；
- Ollama context-window semantics；
- Myth-owned ChatGPT OAuth protocol/security invariants；
- Goal checkpoint / cross-session continuation；
- Eval Ledger / paired evidence / policy promote / rollback；
- Runtime Observatory UI identity。

自动测试大量使用 deterministic provider 或 test doubles。

**自动测试通过 ≠ 真实模型任务稳定。**

## 真实模型验证

真实模型验证必须单独记录：

- provider / model；
- prompt / task；
- context window；
- tool set；
- expected outcome；
- actual outcome；
- artifact / receipt；
- failure taxonomy；
- token / latency / tool cost。

当前开发主线要求建立真实任务集，而不是继续用单个 happy-path 证明“可用”。

固定日常任务已提供 `evals/daily-v1.json` 和 `myth task-benchmark`。默认包含 Myth 与 simple-loop 两组，每题重复三次；所有试次、失败、产物字节校验和运行数据库都会保存。使用方法见 [TASK_BENCHMARK.md](TASK_BENCHMARK.md)，本次实测见 [archive/VALIDATION_V021.md](archive/VALIDATION_V021.md)。

## 浏览器验证

至少检查：

- 桌面三栏工作台；
- 第三栏 Runtime Observatory；
- 窄屏折叠行为；
- Goal create / bind / continue；
- Conversation / Tool / Artifact；
- Settings；
- Runtime state transitions；
- 无水平溢出；
- keyboard focus / critical state readability。

## 不能据此宣称

当前验证**不能**证明：

- 任意真实模型长期稳定；
- 多用户权限安全；
- 分布式 exactly-once；
- 任意代码 / shell 安全执行；
- 完整语义验收；
- 脱离 Web 服务的系统常驻调度、Webhook/Email 触发；
- 所有浏览器 / 辅助技术兼容；
- 多周 Personal Agent 可靠性。

这些必须通过真实任务、自用、故障注入和更大评测逐步证明。

## 证据原则

1. 测到什么写什么。
2. 没测到写 `not measured`，不要写“没有问题”。
3. model claim 不等于 verification。
4. UI projection 不等于 durable truth。
5. UNKNOWN 不等于 FAILED。
6. 历史测试数字进入 CHANGELOG / archive，不进入当前架构说明。
