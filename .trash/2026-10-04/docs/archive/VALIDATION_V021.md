# v0.21 交付验证 — 2026-10-03

本轮交付 Goal 定时唤醒、固定日常任务基线、真实失败驱动的 Runtime 修复和窄屏观测入口。环境为 Windows / Python 3.13.9 / Node 24.16.0；基础版本为 `586ea57`。

## 自动与安装检查

- 原版全量 171 项通过；最终全量 **199 项通过**。
- Python `compileall`、app.js/inspector.js/goals.js 的 `node --check`、Git diff 空白检查通过。
- 新增回归覆盖两连接竞争、事务回滚、commit 后进程退出、服务重启、入口去重、冻结设置、暂停、断连退避、过期时段合并、UNKNOWN 不重放和迟到 Goal checkpoint。
- 实际构建 `myth_runtime-0.21.0-py3-none-any.whl`，安装到独立 target 后从安装目录导入；真实 HTTP 验证 HTML/CSS/三份 JS、Goal/session、计划持久化及暂停。
- CI 配置扩展为 Windows/Linux × Python 3.12/3.13。远端执行结果以本 PR checks 为准，本地 Windows PASS 不能替代 Linux 验证。

复现命令见 [VALIDATION](../VALIDATION.md)、[Goal Wake-up](../GOAL_WAKEUP.md)、[Task Benchmark](../TASK_BENCHMARK.md)。安装包检查为 `python scripts/validate_package.py --package-dir .runtime/package-release`。

## 真实模型

实际调用本机 Ollama `openbmb/minicpm5-2b:f16`，窗口 8192、输出上限 512、max steps 6、temperature 0、thinking false。固定 daily-v1 全部 10 题，每题 3 次，每组 30 个试次。

| 测量 | 修改前 Myth | 最终 Myth | 最终 simple-loop |
| --- | ---: | ---: | ---: |
| 任务验收通过 | 21/30 | **24/30** | 21/30 |
| COMPLETED 但未通过独立验收 | 0 | 0 | 3 |
| 需要人工接管的状态 | 9 | 6 | 6 |
| 模型调用 | 46 | 45 | 48 |

逐次公开记录：[修改前](../evidence/daily-v1-before.json)、[最终版本](../evidence/daily-v1-v021.json)。记录包含 Runtime source digest；最终报告 digest 与被测源码一致，Ollama 模型 metadata/digest 也已保存。全部数据库、模型请求/响应、收据和产物对象保留在记录所指的本地 `.runtime/benchmarks/`，未把本地数据库放入 Git。

修改前运行器在延续任务的前置轮次未完成时仍尝试下一会话；最终运行器保留前置失败并停止该题后续 admission。两次完整任务的成功判定可比较，但调用量不是严格控制的统计成本实验；表中只记录实际观察，不声称一般性提速。

最终两组均通过的任务：资料事实、项目读取、项目搜索、资料合并、文本生成、JSON 生成、安全中断后生成。Myth 算术 3/3，通过零模型 deterministic route；simple-loop 算术 0/3，模型连续回答 168 而预期为 126。

剩余两类失败完整保留：

- 精确修改副本：该小模型最终转为 WAITING_USER，未交付通过字节验收的副本。
- Goal 延续：该小模型转为 WAITING_USER，未通过预期进度标记验收。

因此当前真实模型结果是 **80% 的固定小任务验收率**，不能声称任意任务可靠、长期自主完成或“完美”。三次固定温度重复不是独立统计样本。

## 真实失败如何转成修复

原模型生成不存在的 `old_text`，`exact_patch` 在 Ticket 前抛出 PatchContractError；通用 RuntimeError 分支却把它标为 UNKNOWN。最终版本将其记为已知工具拒绝，并把反馈交给下一步模型；回归验证“错误参数 → 正确参数 → 字节验收”的恢复链，且只发出一次真正的工具 Ticket。

增加已有 project/read/search/Goal progress 的上下文指引后，原来被无必要询问阻断的项目搜索题恢复为 3/3。没有修改 daily-v1 的题目、预期产物或答案 token 来刷分；不能从这一个模型推导其他模型相同收益。

定时 admission 和 Goal link/checkpoint 原子提交；同一个 Goal 的未完成 Run 阻止新 admission。finish_reply 已提交、Goal checkpoint 尚未完成的窗口内，后一个 Run 可以 admission；旧 Run 的迟到 checkpoint 现在不能覆盖新 Run。

## 浏览器

使用真实本地 HTTP 工作台和真实 Ollama：

- 从页面创建 Goal、工作会话和一次性到期计划。
- 页面未再次发送 Prompt，后台自动启动原正常 Driver，生成 `wakeup.txt`。
- content-addressed 产物为恰好 `WAKEUP-OK` 的 9 字节，无换行。
- Runtime 显示 Goal、计划来源/due time、Ticket/Receipt、COMPLETED checkpoint、Token、Context 和预算。
- 窄屏发现原布局横向溢出；修复后 390px 对话、320px 目标计划页均满足 document scrollWidth = viewport width。
- 窄屏 Runtime 按钮能打开完整观测面板并关闭；桌面仍保留第三栏。
- 浏览器没有捕获到 JavaScript error。截图保留在本地 `.runtime/review-evidence/`。

本轮不包含完整浏览器/辅助技术矩阵、OpenAI/ChatGPT 实际调用、OS 常驻服务、多周连续自用或真实 provider in-flight UNKNOWN 核对成功率。

## 后续工作

继续使用完整固定任务集定位错误参数和进度忽略；再加入一个显式 admitted test profile。`test.run` 仍为 planned，不以语法检查或模拟 PASS 替代真实受限执行。长期验证需 2–4 周自用和中途断连/服务重启/核对后的继续。
