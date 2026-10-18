# 验证入口

五轮工程治理、精确 CI 链接与未测范围见 [OPTIMIZATION_REPORT](../OPTIMIZATION_REPORT.md)；此前专题见 [REFINEMENT_REVIEW](REFINEMENT_REVIEW.md)。旧版本绿灯不能替代最终发布 SHA 的独立验收。完整命令以根目录 [AGENTS.md](../AGENTS.md#验证与交付) 为准。

## 每次提交

1. Python 编译、中文说明覆盖、已知秘钥模式扫描。
2. 全量 `unittest discover -s tests -v`；不能只运行新增测试。
3. `node scripts/check_web.cjs` 自动发现所有 Legacy Web JS、`tests/test_*_ui.cjs` 语法与行为合同，不再依赖旧的固定数量。
4. wheel、sdist、`git archive` 源码包排除 `.trash`、运行库、秘钥和开发缓存。
5. wheel 安装至独立目录，运行 `scripts/validate_package.py --package-dir <目录>`，通过真实 HTTP 核对导入、静态资源与基本 API。

中文检查只证明说明存在，不能证明注释准确。涉及界面的改动再运行真实浏览器交互、桌面/窄屏、双主题、焦点与溢出检查。

React `/next/` 还必须经 [React Workbench Workflow](https://github.com/GodBlessRen/Myth/actions/workflows/react-workbench.yml) 验证 TypeScript、Vitest、锁定依赖构建、打包预览字节身份和开发/安装后两条 Chromium 路径；它与 Legacy 的 130 场景是**两项不同门禁**。涉及关键后端 Web/API 入口的修改会触发 React 工作流；其他后端变更可用 `workflow_dispatch` 手动重验。整合发布时要求主线 **CI + Browser + React 的 `head_sha` 三者完全相等且全部 success**，否则仅标记 PARTIAL。React 预览不得因此修改生产 `/`。

发布的 Release job 另从 wheel 安装目录与 fresh offline venv 调用 `scripts/validate_package.py`，逐字节核对 `PUBLIC_ASSETS` 并通过实际 loopback HTTP 建立 Session/Goal/Schedule；真实模型、第三方认证与 2–3 小时浸泡未运行时一律标为未测。


## 按变更选择故障窗口

| 边界 | 回归入口 / 检查重点 |
| --- | --- |
| 创建与状态所有权 | `test_state_boundaries.py`：SQL 故障、并发身份、事务回滚 |
| 控制 | `test_control_atomicity.py`：Pause/Resume/Stop 跨聚合回滚、终态竞争、CAS、真实进程退出 |
| 委派 | `test_delegation_boundaries.py`：父额度先于子费用、收据间崩溃、无 Provider 恢复、UNKNOWN 不重发；`test_parallel_delegation.py` 验证并发重叠、乱序汇合、原子批次、预算争抢与兄弟恢复隔离 |
| 交付 | `test_delivery_workflow.py`：回答提交后收尾、对象摘要验收、受信测试进程 |
| 调度与长 Run | schedule / goal / long-run 测试：同机会争抢、同 Run 接续、租约和进度分离 |
| 模型与认证 | provider / context / oauth 测试：请求窗口、用量缺测、轮转、PKCE/OIDC、日志无凭据 |
| Memory/检索 | revision、撤销、作用域、候选覆盖、来源核对、分页与刷新水位 |
| Evaluation/Evolution | 完整分母、固定版本、partial 禁止发布、显式 Promote/Rollback |

## 真实模型与连续使用

`evals/daily-v1.json` 和 `myth task-benchmark` 提供固定任务、两组对照与重复试次。记录 provider/model、任务和上下文、预算、完整分母、产物/收据/验收、失败类别、token/耗时/人工介入。用法见 [TASK_BENCHMARK](TASK_BENCHMARK.md)。

替身通过证明指定合同；真实模型质量、账号登录可用性、在途断网与多周运行需分别留证据。受信 unittest profile 不是任意代码沙箱；本机测试不证明多用户权限或分布式 exactly-once。

## 记录规则

测到什么写什么；缺测标记 `not measured`。Model claim 不等于验收，UI 投影不等于持久事实，UNKNOWN 不等于 FAILED。功能文档不堆积旧测试数字；故障输入和版本化结果集中进入审查/评测证据。


## Candidate-bound Harness verification（2026-10-19，PR candidate）

`test.run` 可选提供 `candidate_decision_ids`（1–32 个），与本 Run 每个路径的最新
`project.patch_exact` 结果**全量精确匹配**后才准入。系统复核内容寻址的候选字节，
将明确受信的项目复制到临时工作树，并在其中叠加候选运行固定 unittest。
`test.run` Receipt 中的 `tested_subject` 保存具体候选版本；原项目测试 PASS
不能证明候选成功。新的候选版本产生后，完成守卫拒绝沿用旧 PASS。

未提供 `candidate_decision_ids` 时，仍执行原项目测试，但若本 Run 存在候选，
该 PASS 不足以支持候选级完成。复制最多 5000 个文件、64 MiB，总体不提供
网络或 OS 隔离；仅允许用户明确受信项目。危险代码不得通过此途径执行。
临时副本不等于安全沙箱；实际安全隔离需要独立容器/沙箱 adapter。

本机制只使“执行结果是否对应交付候选”更可验证，不自动产生
独立 Delivery Acceptance PASSED，不进行自动 Promote。
修改后验证：`python -m unittest discover -s tests -p 'test_verification_completion.py' -v`
及 `python -m unittest discover -s tests -p 'test_completion_guard_rules.py' -v`。
CI 结果与真实 Provider 费用、效率收益应分别记录，不能把静态提交视作实测通过。
