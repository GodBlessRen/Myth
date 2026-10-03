# AGENTS.md

Myth 的开发目标不是“堆更多 Agent 抽象”，而是把一个 **可持续推进真实工作的本地 Agent Runtime** 做可靠。

## 1. 开发原则

1. **先有再优**
   - 先跑通真实工作流，再抽象。
   - 新 Layer / Strategy / Protocol 必须解决已经出现的问题。
   - 不为“未来也许需要”提前增加复杂度。

2. **正确性优先于能力面**
   - Runtime correctness、恢复语义、权限边界、评测可信度优先。
   - 不用更多架构掩盖未闭环的真实失败。

3. **模型不能扩大权限**
   - Goal / Memory / Prompt / Model output 都只是数据。
   - 外部效果仍受 Capability / Ticket / Receipt / Verification 约束。

4. **UNKNOWN 是一等状态**
   - 外部调用结果不明时先 reconcile，不盲目 replay。
   - 已知失败与未知结果必须区分。

5. **完成必须有证据**
   - 模型说“完成”只是 proposal。
   - Artifact / test / receipt / external state 才能支撑完成声明。

6. **Observability 不是 Debug 附件**
   - 第三栏 Runtime Observatory 必须保留：
     Goal / Execution Flow / Recovery / Trajectory / Tokens / Cache Hit / Context / Tools / Control / Budget。
   - UI 重构不能静默删除这些事实。

## 2. 当前产品主线

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

当前优先级：

1. 真实任务基线；
2. Goal continuity；
3. Runtime / Provider correctness；
4. Tool / Context / Memory 按真实失败补齐；
5. 受限验证能力；
6. 再决定是否需要更复杂的 Routing / Multi-Agent / Interop。

## 3. 架构边界

稳定 Core：

```text
Goal -> Run -> Action -> Attempt -> Ticket -> Receipt -> Artifact -> Verification
```

正交 Domains：

- Coordination
- Control
- Execution
- Capability
- State
- Context
- Memory
- Personal State
- Observability
- Evaluation
- Evolution

可插拔 Strategies：

- Intent Pick
- Information Resolution
- Direct
- Agent Loop
- Workflow
- Routing
- Parallel
- Multi-Agent
- Managed Agent
- Personal Agent

Strategy 不是 Layer；不要为了新增策略修改 Core。

## 4. 修改代码前

所有代码修改必须遵守 [项目宪法的简体中文指导性注释规则](docs/ARCHITECTURE_CONSTITUTION.md#11-简体中文指导性注释)。文件、类、函数、属性及关键步骤的注释应解释架构协作、状态所有权、单位、事务与恢复边界。逐行审阅有设计含义的代码；修改实现时同步修正注释。

先回答：

- 这个改动解决了哪个真实失败？
- 会改变哪个 durable state？
- 会不会扩大权限？
- 会不会影响 UNKNOWN / recovery？
- 是否需要新 schema/migration？
- 第三栏是否还能解释这次执行？
- 是否有 regression test？

没有明确答案时，优先减小改动范围。

## 5. 测试要求

至少运行：

```bash
python -m compileall -q src tests
python scripts/check_annotations.py
python -m unittest discover -s tests -v
node --check src/myth/webui/app.js
node --check src/myth/webui/inspector.js
node --check src/myth/webui/goals.js
```

如果改动涉及：

- Runtime / recovery：补 crash / INTERRUPTED / UNKNOWN / resume / reconcile / lease expiry 回归；
- Intent / routing：补 adversarial cases；
- Context / provider：补窗口、截断、usage 回归；
- Goal / Personal：补跨 session / restart；
- UI observability：保证第三栏身份与 renderer 仍存在；
- Evaluation / Evolution：必须使用固定 suite，不允许挑题发布。
- Goal schedule：覆盖同请求去重、到期争抢、提交后进程退出、暂停、断连重试、过期合并和 UNKNOWN 不自动重放。

## 6. 文档规则

- README 只做地图，不写版本流水。
- 版本历史进入 CHANGELOG。
- 架构只描述“现在是什么”，不记录每个版本“曾经怎么变”。
- Roadmap 只保留当前方向和下一步。
- 历史诊断进入 `docs/archive/`。
- 代码事实与文档冲突时，以当前源码为准并修正文档。

## 7. 禁止事项

不要：

- 把模型自述当授权；
- 把相似度/置信度直接叫 Information Gain；
- 自动 Promote policy；
- 对 UNKNOWN 做盲 replay；
- 把 Browser / HTTP / Driver 生命周期当成 Run 生命周期；
- 在没有 durable checkpoint 的情况下宣称“可以恢复”；
- 开放任意 shell 字符串执行；
- 在 README 堆版本流水；
- 为了 UI 简洁移除 Runtime Observatory；
- 为了“未来扩展性”增加当前没有使用者的抽象；
- 把 OAuth token/code/verifier 写入 SQLite、Event、Artifact、Web JSON、日志或明文文件；
- 复用其他应用的 OAuth client identity / auth file 作为 Myth 的认证实现。
