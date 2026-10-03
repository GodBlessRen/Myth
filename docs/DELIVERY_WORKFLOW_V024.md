# Myth v0.24 — 0–12 周交付闭环模拟落地

基线：`5650c62`（v0.23.0）。本分支把航海图四阶段按**工程结果**压缩成一个候选实现；不会伪造真实世界需要 2–4 周才能获得的连续自用数据。

## 产品承诺

> 一个人把项目工作交给 Myth，离开后可以回来检查成果；中断可以接续；模型说“完成”不等于成果验收通过；下一次继续时不必重新解释执行事实。

核心时间尺度：Goal（跨天意图）→ Run（一次委托）→ Work item（可检查阶段）→ Action / Attempt（实际执行）。

## 0–2 周：固定真实基线与终态收敛

已实现 Durable Finalization Obligation：回答提交前先落一条收尾义务。若回答已持久化而 Memory / Goal 尚未更新，下一次 Workspace 装配只对 `COMPLETED` 回答补齐派生投影；`RUNNING / UNKNOWN` 不猜测、不重放。

每个 Conversation Run 自动拥有根 Work item，执行完成与语义验收分开。

真实进程退出测试覆盖原蓝图的 `finish_reply → record_episode → Goal checkpoint` 崩溃窗口。

## 2–6 周：交付一个可验收工作流

普通 Conversation 新增 Acceptance Ledger：

- `UNVERIFIED`
- `PASSED`
- `FAILED`
- `INCONCLUSIVE`

验收绑定当前回答 + 产物摘要得到的 `subject_digest`；主体改变，旧验收失效。Evidence 可引用来源、Artifact、Test Receipt。模型完成声明本身永远不是 PASS。

Work item 保存 plan revision、依赖、输入摘要、验收条件、证据和局部预算描述，为“项目简报 → 候选改动 → 验证”保留稳定阶段身份。

## 6–10 周：复杂工作与受限验证

`test.run` 从 planned 升为 executable，但只接受**用户显式创建且 `trusted_project=true` 的 Python unittest profile**。

边界：

- 不接受任意 shell、任意 executable、模型拼接 argv；
- profile 固定项目、test_dir、pattern、timeout、输出上限与可选项目内 PYTHONPATH；
- 子进程环境只继承小型 allowlist，不自动继承 OpenAI / GitHub / AWS 等任意凭据变量；
- 超时会尝试终止进程树；
- Test 必须先获得 Ticket，再产生 Receipt；
- 没有 Receipt 的 test outcome 保持不明，不自动重跑；
- **不宣称 OS 级网络隔离，也不宣称任意仓库代码安全。首版仅用于用户信任的本地项目。**

仍未把现有 Conversation `max_steps=2–32` 粗暴放大。真正的多窗口同 Run 总预算续接仍应单独实现和测量。

## 10–12 周：连续使用验收与发布指标

新增人工关注记录：`setup / clarification / review / rework / recovery` 秒数。

Delivery metrics 汇总：

- 全分母验收状态；
- pass rate；
- `COMPLETED + FAILED acceptance`；
- 待收尾义务；
- 人工关注总时长。

Runtime 第三栏保留原有轨迹、Token、Context、Tool、Budget、Recovery，并新增 Delivery，不用新的漂亮面板替代执行事实。

真实的“2–4 周连续自用”无法靠一次提交生成，仍是发布闸门。

## 新的不变量

1. `Turn.status=COMPLETED` 只说明回答已持久化。
2. `Acceptance.state=PASSED` 才表示 checker 对**当前 subject_digest**通过。
3. Finalization 可以补偿 Memory / Goal 派生投影，但不能重放 UNKNOWN 外部效果。
4. Test profile 执行项目代码，必须显式信任项目；固定命令不等于安全沙箱。
5. Work item 的 `DONE` 与 `acceptance_state` 是两个维度。
6. Runtime Observatory 只投影事实，不创造授权。

## API

- `GET /api/workspace/turns/{run_id}/delivery`
- `POST /api/workspace/turns/{run_id}/acceptance`
- `POST /api/workspace/turns/{run_id}/attention`
- `POST /api/workspace/turns/{run_id}/work-items`
- `GET /api/workspace/delivery/metrics`
- `GET /api/workspace/projects/{project_id}/verification-profiles`
- `POST /api/workspace/projects/{project_id}/verification-profiles`

## 发布闸门

合并前必须满足 Python 全回归、Node UI 回归、终结窗口真实进程退出探针、test.run PASS / FAIL / timeout / receipt 恢复回归，并确保文档不把 fixture 写成真实模型或多周使用成绩。
