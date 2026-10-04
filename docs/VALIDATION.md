# 验证入口

当前版本结果见 [REFINEMENT_REVIEW](REFINEMENT_REVIEW.md)；历史证据只用于比较，不能充当当前通过记录。完整命令以根目录 [AGENTS.md](../AGENTS.md#验证与交付) 为准。

## 每次提交

1. Python 编译、中文说明覆盖、已知秘钥模式扫描。
2. 全量 `unittest discover -s tests -v`；不能只运行新增测试。
3. 六个前端 JS 语法检查，以及 Observatory / reconnect / statistics / interactions 四组 Node 测试。
4. wheel、sdist、`git archive` 源码包排除 `.trash`、运行库、秘钥和开发缓存。
5. wheel 安装至独立目录，运行 `scripts/validate_package.py --package-dir <目录>`，通过真实 HTTP 核对导入、静态资源与基本 API。

中文检查只证明说明存在，不能证明注释准确。涉及界面的改动再运行真实浏览器交互、桌面/窄屏、双主题、焦点与溢出检查。

## 按变更选择故障窗口

| 边界 | 回归入口 / 检查重点 |
| --- | --- |
| 创建与状态所有权 | `test_state_boundaries.py`：SQL 故障、并发身份、事务回滚 |
| 控制 | `test_control_atomicity.py`：Pause/Resume/Stop 跨聚合回滚、终态竞争、CAS、真实进程退出 |
| 委派 | `test_delegation_boundaries.py`：父额度先于子费用、收据间崩溃、无 Provider 恢复、UNKNOWN 不重发 |
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
