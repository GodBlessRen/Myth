# Myth Documentation

这组文档按**职责**组织，而不是按版本堆叠。

## 先读什么

| 目标 | 文档 |
| --- | --- |
| 30 秒理解项目 | [README](../README.md) |
| 理解当前架构 | [ARCHITECTURE.md](ARCHITECTURE.md) |
| 理解 Memory evidence / revision / freshness / Delta / Mental Model / Knowledge Page | [MEMORY_LIFECYCLE.md](MEMORY_LIFECYCLE.md) |
| 按协作链读中文源码 | [CODE_GUIDE.md](CODE_GUIDE.md) |
| 理解不可破坏的边界 | [ARCHITECTURE_CONSTITUTION.md](ARCHITECTURE_CONSTITUTION.md) |
| 看 Runtime / 第三栏观测合同 | [OBSERVABILITY.md](OBSERVABILITY.md) |
| 看产品视觉与交互原则 | [DESIGN.md](DESIGN.md) |
| 看逐文件处置、故障修复与性能证据 | [REFINEMENT_REVIEW.md](REFINEMENT_REVIEW.md)、[FILE_REVIEW.md](FILE_REVIEW.md) |
| 看当前下一步 | [ROADMAP.md](ROADMAP.md) |
| 看验证边界 | [VALIDATION.md](VALIDATION.md) |
| 安排 Goal 后续工作 | [GOAL_WAKEUP.md](GOAL_WAKEUP.md) |
| 跑固定真实任务基线 | [TASK_BENCHMARK.md](TASK_BENCHMARK.md) |
| 看版本演进 | [CHANGELOG](../CHANGELOG.md) |
| 开发 / Agent 工作规范 | [AGENTS.md](../AGENTS.md) |

## 文档职责

### ARCHITECTURE.md

只回答：

- 当前 Runtime shape；
- 关键 durable state；
- 主运行链；
- Ports / Adapters 边界；
- 关键 persistence / recovery 语义。

不写版本流水。

### ARCHITECTURE_CONSTITUTION.md

只回答：

- Core / Domain / Strategy 的稳定边界；
- Authority / UNKNOWN / Verification 等不可破坏规则；
- 新抽象进入系统的门槛。

### OBSERVABILITY.md

只回答：

- 第三栏必须显示哪些事实；
- 每个指标来自哪里；
- 哪些 UI 可以折叠，哪些事实不能消失。

### ROADMAP.md

只保留：

- 当前产品主线；
- 下一阶段优先级；
- 明确冻结项；
- 长期方向。

已完成版本历史放 CHANGELOG。

### VALIDATION.md

记录：

- 自动检查方法；
- 当前验证边界；
- 哪些是 mock / deterministic provider；
- 哪些是真实模型 / 浏览器 / 外部系统验证。

## 历史资料

历史诊断、旧评测和一次性画面在仓库 `.trash/<日期>/` 留档，不参与生产代码、检索或发布包。每次更新按 AGENTS 中的垃圾站规则 淘汰无用内容。
