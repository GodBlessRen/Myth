# 当前交付与验证合同

Goal 保存跨会话意图，Run 保存一次执行，Work item 保存可检查阶段；Action / Attempt / Ticket / Receipt 保存真正执行事实。模型回答、本轮结束、长期目标完成与验收通过分别判定。

## 收尾与验收

回答提交前保存 durable finalization 义务。若回答已提交而 Memory/Goal 投影尚未更新，后续装配根据义务幂等补齐；不重放 RUNNING/UNKNOWN 外部效果。

Acceptance 保存 `UNVERIFIED / PASSED / FAILED / INCONCLUSIVE`。验收绑定回答与产物的 `subject_digest`、checker 和 evidence。对象摘要读取、核对与写入在同一短事务，旧摘要拒绝；模型无法通过该入口自批。

Work item 保存 plan revision、依赖、输入摘要、验收条件、证据、局部预算和进度备注。序号/修订分配和省略字段的读改写都在事务内；`DONE` 与验收状态是两个维度。

## 受限 test.run

仅执行用户显式创建且 `trusted_project=true` 的 Python unittest profile：

- 固定项目、test_dir、pattern、timeout、输出上限和项目内 PYTHONPATH；不接受模型拼接 executable/argv/shell。
- 子进程环境使用小型 allowlist，不自动继承供应商/云凭据；超时尝试终止进程树。
- 执行前获取 Ticket，结束后保存 Receipt；无 Receipt 的结果保持不明，不自动重跑。
- 执行的是用户信任的项目代码；当前不提供 OS 网络隔离或任意代码安全沙箱。

## 用户关注与观测

人工关注按 `setup / clarification / review / rework / recovery` 秒数记录。Delivery metrics 汇总完整分母验收状态、通过率、回答完成但验收失败、待收尾义务和人工关注总时长。第三栏保留原执行/恢复/计量事实，同时展示 Delivery。

## API

- `GET /api/workspace/turns/{run_id}/delivery`
- `POST /api/workspace/turns/{run_id}/acceptance`
- `POST /api/workspace/turns/{run_id}/attention`
- `POST /api/workspace/turns/{run_id}/work-items`
- `GET /api/workspace/delivery/metrics`
- `GET|POST /api/workspace/projects/{project_id}/verification-profiles`

## 验证边界

当前回归覆盖真实进程退出后的 finalization 补偿、test.run PASS/FAIL/timeout/Receipt 恢复，以及步骤消费和工作项并发。完整真实模型交付与多周连续自用仍需独立结果，不能由一次工程提交替代。运行方法见 [VALIDATION](VALIDATION.md)，当前改动证据见 [REFINEMENT_REVIEW](REFINEMENT_REVIEW.md)。
