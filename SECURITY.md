# 安全与隐私边界

Myth 面向受信本机单用户。模型给出提案，Runtime 按固定身份、作用域、预算和 Ticket 决定是否执行。远端模型会收到实际提交的上下文；需要完全本地处理时使用本地 Ollama。

## 文件与执行

- Exact 入口只处理准入时冻结的 `allowed_files`。Conversation 读取固定项目根，拒绝路径上跳、驱动器/ADS、符号链接逃逸及常见秘钥和缓存目录。目录排除不是通用敏感信息识别器，用户应只关联准备提供给 Agent 的内容。
- 生成和精确替换写入 Myth 受管副本；原项目不被这些文件工具直接覆盖。下载读取已记录摘要的不可变对象。
- `git.status` / `git.diff` 使用固定 argv，不经过 shell。模型不能传入任意命令行。
- `test.run` 已实现：用户明确创建 `trusted_project=true` 的 Python unittest profile，固定项目、测试目录、超时和输出限制。工具 Ticket 先于进程启动，stdout/stderr、退出状态与用量进入收据；缺失收据保持 UNKNOWN。
- **受信测试会执行项目 Python 代码，具有当前 OS 用户权限；profile 不是操作系统沙箱。** 固定 argv 只限制启动方式，测试代码本身仍可能读写文件、联网或创建进程。不要对不信任的项目启用它。
- 不提供任意 shell、浏览器控制或远端 MCP 执行入口。

## 模型、权限与凭据

- 模型、Goal、Memory、检索正文和子任务结果都不能扩大文件范围、预算或工具权限。隐藏工具必须经发现流程进入可见目录，发现本身不授权执行。
- 单层 `agent.delegate` 只收到明确的 task/context/source_refs，不继承父历史，不写入、不调用工具、不递归。父工具预算与 Ticket 先于子模型调用；子结果仍是 Observation，父 Runtime 核对来源与交付。
- API Key 的应用内连接先验证候选，再替换系统安全凭据库中的值。`OPENAI_API_KEY` / `DEEPSEEK_API_KEY` 是显式 CLI/进程环境配置入口，无需为了应用内使用设置它们。
- ChatGPT OAuth 使用 Myth 自己的客户端身份、PKCE S256、一次性 state/nonce、精确 loopback callback，以及 ID token 签名、issuer、audience、expiry、nonce 校验。不读取其他应用的认证文件。
- access/refresh/ID token 只保存到明确选择的系统安全凭据后端；没有明文文件回退。`.runtime/oauth/chatgpt.json` 只含非秘钥注册/用户元数据。
- 刷新轮转串行执行。派发后结果不明不重发旧 refresh token；明确终态拒绝要求重新登录，临时网络失败不销毁已有凭据。退出清除本地凭据，并报告远端撤销是否确认。
- 凭据不得进入 Runtime SQLite、Artifact、Receipt、事件、日志和 Web JSON。Provider Evidence 只保留脱敏元数据，排除凭据、加密推理状态和私有推理正文。

## 控制、恢复与验收

Pause / Resume / Stop 的命令、Turn/Core、Goal checkpoint 与事件在同连接短事务提交；命令序号与 Core 栅栏独立递增。模型设置的网络检查在事务外，提交时核对检查所用 revision。

Stop 停止后续调度，已发出的请求仍记真实晚到结果。Ticket 只证明获准启动；Receipt 记录效果，Verification 验收固定对象，不能互相代替。数据库事务不能包住文件、进程和远端请求；效果不明先核对，不能盲目重放。

Conversation 回答结束不等于 Goal 完成或语义验收通过。Delivery 验收绑定 subject digest；产物改变后旧 PASS 不能继续证明新内容。Exact 入口按创建时固定的完整验收合同检查，合同缺失明确报错。

## Web 与调度

- Web 只绑定 `127.0.0.1` / `localhost` / `::1`；Host/port 检查拒绝 DNS rebinding 名称。修改请求要求 JSON，并校验提供的 Origin；CSP、禁止 framing 和文本 DOM 限制页面输入。
- OAuth callback 校验 Host/state；请求日志移除查询串，避免打印 code/state。服务不开放 CORS、任意文件或凭据读取接口。
- 本机服务没有多用户认证；有权限的本机进程仍能访问。对外部署需要另行实现认证与授权，当前实现不提供该部署模式。
- 显式 Goal 计划可由 Web 内置执行器或独立 `myth worker` 驱动。计划只创造机会，仍需 Goal/session admission、预算和 Ticket。进程停止期间不执行，重启接续持久机会。
- 通用 Trigger 元数据不等于可执行调度；尚无 Webhook/Email 或 OS 服务安装器。

## 仓库与发布

`.runtime/`、数据库、环境文件、私钥与用户项目不提交。垃圾站 `.trash/` 不参与运行，也不进入 wheel、sdist 和 Git 源码包。生产提示、私有文档、真实 token/trace 不能作为测试夹具。若秘钥进入历史，必须轮换；后续删文件不能撤销泄漏。

当前验证入口见 [VALIDATION](docs/VALIDATION.md)，故障与证据见 [审查报告](docs/REFINEMENT_REVIEW.md)。

- Claude OAuth uses a separate `claude_oauth` provider identity and dedicated loopback callback. Myth requires its own configurable public client ID and must not reuse Claude Code / Anthropic CLI client identity; PKCE/state are mandatory, OAuth tokens never enter Runtime SQLite, events, artifacts, logs, or Web JSON.
