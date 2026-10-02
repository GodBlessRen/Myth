# Changelog

## v0.19 — Native Sign in with ChatGPT

- 移除 Myth 对 Pi OAuth / Pi CLI 的认证依赖。
- 按 OpenAI OSS Sign in with ChatGPT 合同实现动态 client registration、PKCE S256、state、OIDC nonce 与 exact loopback callback。
- ID token 验证 signature / issuer / audience / expiry / nonce；返回 client_id 与注册身份绑定。
- access / refresh / ID token 只进入系统安全凭据库；无明文凭据文件 fallback。
- refresh token rotation 跨线程/进程串行；logout 尝试远端 revoke 并始终清除本地凭据。
- ChatGPT plan Responses 使用 `store:false + stream:true`，只在 `response.completed` 后确认成功。
- Web/CLI 新增 login / status / logout；callback query 不进入本地日志。
- 旧 `pi-openai` 设置迁移为 `chatgpt`，旧 durable Run 会收到明确迁移错误。


## v0.18.1 — Cache Observability

- OpenAI Responses 的 provider-reported cached input tokens 写入 durable model usage。
- Runtime Observatory 的 Tokens 区显示 Prompt Cache hit token 与命中率。
- Provider 不提供缓存计量时明确显示 N/A，不从 keep-alive / KV cache / 相似上下文推测。
- cache hit rate 定义为 `cached_input_tokens / input_tokens`。

Myth 只记录已经落地并进入主线的高价值变化。详细提交历史以 Git 为准。

## v0.18 — Goal-first Personal Work Loop

- 长期 Goal 增加 durable work state：
  `current_state / progress_note / next_action / waiting_for / last_run / revision`。
- Conversation 在真实终态写 Goal checkpoint。
- 同一 Goal 可跨 Session / restart 继续，并把 checkpoint 固定进新 Turn Snapshot。
- 第三栏 Runtime Observatory 固定保留：
  Goal / Execution Flow / Trajectory / Tokens / Context / Tools / Control / Budget。
- UI observability identity 加入回归测试。

## v0.17 — Provider Context Hardening

- ModelRequest 增加 `num_ctx` / temperature。
- Ollama 显式传递 `num_ctx` / temperature / keep_alive。
- Ollama 本地 Context budget 从 `num_ctx - output - reserve` 推导。
- provider-confirmed context truncation 记录为 durable FAILED，而非 UNKNOWN。
- ambiguous post-Ticket transport failure 继续保持 UNKNOWN。

## v0.16 — Intent Correctness

- 收紧 deterministic arithmetic grammar。
- 日期 / 版本 / 分数 / 百分比 / 电话形状默认回退 Agent。
- strong / weak knowledge cue 分级。
- calculator rejection 写入 `RouteFallback` 后安全回退。
- foundation-v4 增加 36 条 Intent adversarial cases。

## v0.15 — Evidence-driven Evolution Control Plane

- versioned Cost Model Registry。
- Gain Calibration Matrix。
- durable Policy Candidate Registry。
- complete-suite release evidence。
- explicit Promote / Rollback。
- Active Policy 只影响未来 Turn，历史 Turn 不倒写。

## v0.14 — Paired Evaluation + Information Gain

- Eval Ledger 持久化。
- baseline / candidate paired comparison。
- Information Gain 只从同 case 的 paired Verdict evidence 估计。
- 成本默认保留为向量，显式权重后才计算 gain-per-cost。

## v0.13 — Executable Evaluation + Conservative Routing

- 固定 EvalSuite -> Runner -> Observation -> Report -> Release Gate。
- `myth eval` CLI。
- conservative `local_retrieval` route。
- L0 / L1 / L2 Information Resolution 接入 Turn admission。

## v0.12 — Retrieval Correctness Foundation

- Knowledge 去掉 rank 前 10,000 chunk 静默截断。
- Memory 去掉最近 500 条隐式 recall 上限。
- candidate coverage diagnostics。
- project.search cursor / max_files。
- fixed-digest L0 / L1 / L2 knowledge resolution。
- foundation-v1。

## v0.11 — Runtime Closure

- Control revision 跨 SQLite 连接原子分配。
- Goal admission 与 request identity 绑定。
- scoped Episodic Memory。
- `knowledge.read`。
- bounded deterministic arithmetic fast path。

## v0.10 — Context Continuity

- ContextCompiler 与 bounded projection。
- context selected / folded / dropped evidence。
- Compact / Pause 连续性加强。

## v0.9 — Core / Domains / Strategies

- 从固定“层级栈”重构为：
  Core + Domains + Strategies + Ports / Adapters。
- Goal / Trigger / Personal State 进入持久化边界。
- Stop 成为产品术语。

## v0.8 — Product Control

- Steer / Pause / Resume / Stop。
- Model / Thinking switch。
- Compact。
- durable Memory revision。
- project.search / diff.preview / git.status / git.diff。

## v0.7 — Agent Workbench UI

- 三栏工作台。
- Runtime Inspector / Execution Spine。
- 暖纸张 / 墨色 / 克制橙视觉系统。

## Earlier

v0.1–v0.6 主要完成 Durable Runtime、exact verification、conversation workspace 与 breadth-first platform skeleton。需要逐提交考古时直接查看 Git history。
