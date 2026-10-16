# MYTH · OPTIMIZATION REPORT

> 2026-10-16 · 五轮工程治理收官记录。此报告描述已合并的改动、独立 PR 证据与待核验项；**不能代替最终 main SHA 的 GitHub Actions 结果**。所有版本、成功率及费用必须与原始试次分母一起解读。

## 1. 基线与边界

- 初始基线：`15441a11a073613e82faef7894d297c35f984182`（2026-10-12）。主 CI 的 Windows Python 3.12/3.13 失败；Legacy Browser **120/130**；React Workbench 当时通过；Release 因门禁失败跳过。
- 已整合 CALL 1–4 的 main：`9b3c5614f49a8be435a640a79829d4bfdbf0a90c`。独立 [CI 38873946537](https://github.com/GodBlessRen/Myth/actions/runs/38873946537) 与 [Browser 38873946618](https://github.com/GodBlessRen/Myth/actions/runs/38873946618) 均通过。
- CALL 5 的发布治理补丁独立提交；**最终合并 SHA 以 main 的 GitHub commit 与三项 Workflow 各自的 `head_sha` 一致为验收条件**，不得用该整合基线、历史 PR 绿灯或文档文本代替。
- 范围：本机 Python/SQLite Runtime；生产主页 `/` 仍由 legacy 静态 UI 拥有，React 19 仍隔离在 `/next/`。不涉及新数据库迁移、真实账号 OAuth、分布式 exactly-once 或 React 切换生产。

## 2. 六个已合并修复 PR：问题、根因、证据

| 轮次 | PR | 根因 → 变化 | 主要验证 |
| --- | --- | --- | --- |
| CALL 1 | [#78](https://github.com/GodBlessRen/Myth/pull/78) | React 资源 LF 被 Windows checkout 改写成 CRLF（450→457 bytes）；固定 `.gitattributes` 的资源换行合同。首页快捷按钮边框对比不足，修改现有语义颜色 token，未降审查阈值。 | Windows/Ubuntu × Python 3.12/3.13、Release；Browser 130/130 |
| CALL 2 | [#79](https://github.com/GodBlessRen/Myth/pull/79) | 已准入 HTTP 消息的重放错误受**当前** Provider/设置预检阻断；改为用持久请求事实先核对旧身份，冲突返回拒绝。 | [CI 38865096213](https://github.com/GodBlessRen/Myth/actions/runs/38865096213)、[Browser 38865096310](https://github.com/GodBlessRen/Myth/actions/runs/38865096310) |
| CALL 2 | [#80](https://github.com/GodBlessRen/Myth/pull/80) | Legacy 刷新丢失内存 `request_id`；同标签页仅保存 SHA-256 指纹与 UUID，正文不落存储。 | [CI 38866728628](https://github.com/GodBlessRen/Myth/actions/runs/38866728628)、[Browser 38866729089](https://github.com/GodBlessRen/Myth/actions/runs/38866729089) |
| CALL 3 | [#81](https://github.com/GodBlessRen/Myth/pull/81) | 定时 Goal 漏掉模型能力校验，却可以创建不合法 Run；Send、Control、Schedule 统一 Model Preflight；保留 Scheduler 的 Ollama 已安装检查。 | 测试先 RED 后 GREEN；[CI 38870300277](https://github.com/GodBlessRen/Myth/actions/runs/38870300277)、[Browser 38870300262](https://github.com/GodBlessRen/Myth/actions/runs/38870300262) |
| CALL 4 | [#82](https://github.com/GodBlessRen/Myth/pull/82) | 会话每次刷新反复读取历史 Turn/Cursor/Lease；同一次已读投影复用持久事实，不跨请求缓存，维持活性观测只读。 | 查询计数 36→6；[CI 38872515528](https://github.com/GodBlessRen/Myth/actions/runs/38872515528)、[Browser 38872515612](https://github.com/GodBlessRen/Myth/actions/runs/38872515612) |
| CALL 4 | [#83](https://github.com/GodBlessRen/Myth/pull/83) | 浏览器把 POST 不明结果、已成功 POST 后刷新失败都显示成普通报错；区分 unknown write / acknowledged write / stale read，绝不自动重试写入。 | Node UI 门禁 76 PASS、0 FAIL；[CI 38872806305](https://github.com/GodBlessRen/Myth/actions/runs/38872806305)、[Browser 38872806265](https://github.com/GodBlessRen/Myth/actions/runs/38872806265) |

**未回退的关键不变量**：每条消息按 `request_id` 准入；已派发而效果不明先核对而不盲发；Stop 不抹去晚到收据；Ticket ≠ Receipt ≠ Verification；模型/Context/工具统计以实际事实为准，未测不是零。

## 3. 量化结果与不可跨越的测量边界

| 指标 | Before → After | 证据等级与解释 |
| --- | --- | --- |
| 最初 Windows Python 3.12/3.13 | FAIL → PASS | Measured：新 CI 全平台单测通过，不等于生产任意 Windows 环境 |
| Legacy Chromium 业务场景 | 120/130 → 130/130 | Measured：5 个宽度 × 2 个主题 × 13 个业务状态；固定 Provider 测试服务 |
| 历史会话游标 SELECT（6 Turns × 5 Polls） | 每 Poll 36 → 6，即 **-83.3%** | Measured：真实 SQLite trace，5 次重复均相同 |
| 同一合成会话 Poll 中位数 | 7.229 → 3.940 ms | Partial：采自**两次不同 CI worker**，不是配对 AB/生产 P95，也不承诺端到端延迟降低 45.5% |
| 固定测试任务 `daily-v1` | 10 案例 × 3 次 × 2 测试路径 = **60 夹具试次** | Measured harness contract：由 `test_task_benchmark.py` 完整分母/独立 artifact oracle 验证；不是新鲜 live provider 的模型质量对照 |
| Provider-visible input/output Tokens、实际缓存命中 | N/A | **NOT MEASURED**；无合法证据证明减少 Token 或供应商费用 |
| 真实供应商端到端时延、商业账单 | N/A | **NOT MEASURED**；本轮不使用真实 OAuth/API 凭据 |
| 长时间 120–180 分钟连续运行、真实断网、跨机器执行 | N/A | **NOT RUN**；CI 的秒级 soak 合同不替代几小时真实时钟 |
| React Workbench 最终主线 SHA | 看第 4 节的最终同 SHA 门禁 | 报告撰写时不借用最初 `15441a11` 的 React 绿灯 |

## 4. CALL 5 · Release 验收合同

发布治理补丁给 React Workbench 增加 `workflow_dispatch` 和关键后端 Web/API 路径触发，并将 checkout 的持久凭据设为禁用；因此最终主线的 React Gate 不再完全依赖 `frontend/**` 是否修改。触发覆盖是**显式选取的相关路径**，不是所有 Python 变更的全局 E2E 保证。若本次触发的主线运行不存在或失败，则这一门槛为 BLOCKED。

同一 `head_sha` **必须**核对如下 GitHub Actions（在 Actions 详情查精确 commit SHA）：

1. [CI](https://github.com/GodBlessRen/Myth/actions/workflows/ci.yml?query=branch%3Amain)：Quality（编译、测试发现、注释、已知秘钥模式、全部 Node UI）、Windows/Ubuntu Python 3.12/3.13、MCP integration、Release。
2. [Browser](https://github.com/GodBlessRen/Myth/actions/workflows/browser.yml?query=branch%3Amain)：真实 Chromium 130 场景、26 类资源身份；仅验证固定 HTTP/SQLite + Provider fixture。
3. [React Workbench](https://github.com/GodBlessRen/Myth/actions/workflows/react-workbench.yml?query=branch%3Amain)：`npm ci`、TypeScript、Vitest、离线 Vite build、**重新生成资源与仓库预览 bundle 逐字节一致**、真实 Chromium 经 Vite 和 wheel 内的 `/next/` 双入口工作流。

CI Release 的完整链路构建 wheel、sdist、`git archive`，校验归档路径/文件类型/当前文件集/SHA256，并在独立安装目录和 fresh offline venv 下经实际 HTTP 验证全部 `PUBLIC_ASSETS`、基本 Session/Goal/Schedule 操作。React 未通过或没有同 SHA 证据，**不得宣布最终发布验收 COMPLETE**。

本地复核：

~~~bash
python -m compileall -q src tests scripts
python scripts/check_test_discovery.py
python scripts/check_annotations.py
python scripts/audit_secret_patterns.py
python -m unittest discover -s tests -v
node scripts/check_web.cjs
python -m build
python scripts/validate_release.py dist
~~~

生产入口 `/` 与隔离预览 `/next/` 必须同时存在；发布包资源只来自 `myth.web_assets.PUBLIC_ASSETS`。

## 5. 安全、许可、回滚与未解决风险

- **验证范围**：依赖声明在 `pyproject.toml` 与 `frontend/package-lock.json`；React `npm ci` 锁定依赖树。CI 已配置已知秘钥模式检测；发布验收禁止 `.trash`、`.runtime`、数据库及私有文件进入 wheel/sdist/zip；HTTP 静态资源是封闭白名单。**未完成第三方依赖的全量漏洞审计、Git 历史所有提交的人工凭据审计或外部红队评估**。
- **许可现状**：核对本次 main Git 树未找到根目录或子目录 `LICENSE/COPYING/NOTICE`。这不是可自动判断的许可选择；如公开授权复用，需要维护者明确确定协议并补全法律审查。本轮不擅加许可证。
- **禁做**：不清空旧 SQLite；不补造认证成功、不重新派发 UNKNOWN、不修改语义阈值、不把 React 迁移预览视为默认生产 UI。
- **回滚顺序**：若 CALL 5 的 CI 触发配置产生开销/错误，仅回滚这次 release/文档 PR；功能回退按依赖从后往前处理：#83 UI 文案、#82 只读 Poll、#81 准入、#80 刷新身份、#79 请求恢复、#78 换行/对比度。每次回退后必须**重新在新的 HEAD**验收，不能回填此前绿色结论。
- **有意不实现**：不引入新 Context 缓存、热路径串行化层、Retry daemon、分布式锁、全栈前端切换或自动 RSI；当前数据不足以证明收益。

## 6. 发布决策与后续

- **CALL 1–4：完成代码交付并合并**，已有各自 PR 及主线联合 CI 证据。
- **CALL 5：以最终 main 的三项 Workflow 结果决定 COMPLETE / PARTIAL**；此 Markdown 是审查与验证规范，不是自签名发布凭证。PR 合并后如有红灯，保留失败原始日志、修复并重跑**全套最新 SHA**，不得仅重试一处后声称完整验收。
- 后续真正值得做而**本轮未加入**：在用户明确授权并具备可用凭据的隔离环境完成真实 Provider、多小时故障注入、稳定的 paired wall-clock/P95/Token 成本对照；在确定许可证前不擅宣称外部复用授权；React 等价完整后另开生产切换专案。

> **工程完成标准**：有可核对的 committed code、不可替代的持久状态事实、最新 SHA 的可复现门禁与准确的未测范围；不是五轮对话全部结束就算发布成功。
