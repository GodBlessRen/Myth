# Myth 日常可用性审查与修复

日期：2026-10-19。基线：远端 `main` 的 `2d67edf16c40bc7443c10fa5687a2ccfbf596723`，在独立副本修改，分支 `codex/usability-runtime-20261019`。

## 判断

当前问题来自真实使用路径：普通问题也进入较重的结构化规划协议，发送前有额外网络查询，澄清和经历重复进入上下文，生成中的正文没有展示，有一条“窗口压力”检查还会拒绝正常返回。继续增加规则和提示说明会放大这些成本。

基线 876 项 Python 测试通过，新增的第一组 8 个可用性用例却全部失败或报错。原有测试主要证明状态、收据和固定 Provider 的行为，无法证明模型不会多问、回答充分或首字足够快。后续发布必须同时看实际任务结果和用户等待。

## 已追踪的路径

| 路径 | 核查内容 |
| --- | --- |
| `web_workspace.send → workspace_store.prepare_turn/create_turn` | 消息去重、模型预检、价格查询、历史装载、版本核对、Memory/Knowledge 注入 |
| `conversation_request → compile_conversation_context` | 系统提示、工具参数与 schema、消息顺序、历史/Memory 重复、动态状态对前缀的影响 |
| `ConversationAgent → LocalConversationExecution → DecisionRuntime` | 提问消费、已知长度失败、预算预留、收据与修复之间的崩溃窗口 |
| `providers/openai.py、deepseek.py、ollama.py、messages.py` | SSE/NDJSON、终态、缺失用量、输出上限、缓存读写计量与预览脱敏 |
| `web.py、web_workspace.session/_spawn` | 凭据变更后的目录失效、Driver、临时预览、终态消息提交 |
| `webui/` 与 `frontend/src/` | 正文是否被裁切、等待状态、生成预览、重复样式、实际组件依赖、键盘与窄屏 |
| 其余 Runtime、Goal、委派、权限和恢复路径 | 调用关系、既有合同与全量回归；未据此宣称每个模块均无缺陷 |

初始清点的 Python、原生 JS 与前端 TS/TSX 共 143 个文件、41,788 行，包含两个放在前端 src 中的测试文件，不含 CSS、生成 bundle 和其余测试目录。上表是本轮人工追踪范围；全量测试通过不等同于全仓逐行正确性认证。

## 发现与处置

| 问题 | 源码原因 | 本轮改变 |
| --- | --- | --- |
| 普通问题的提示很重 | 默认工具集合列了 28 个工具；无子模型时仍有 23 个。通用系统提示还常驻委派、MCP、语义映射等规则 | 默认保留 13 个读写/发现工具；专门能力按需展示，主提示改为短协作说明；中文也能发现技能、记忆时间线和外部服务 |
| 明明知道工具，还要多走一步 | `_check_tool_admission` 把“没有展示参数”当成拒绝执行的理由 | 删除这层目录门槛。实际 Capability、路径、输入、MCP 发现、Ticket 校验仍执行 |
| 答完澄清还再次问 | 问题已保存在消息中，又被追加成最新“工具处理记录”，位置晚于用户答复 | ask_user 不再重复投影为工具活动，问题和回答只按消息顺序出现 |
| 相同问答反复吃上下文 | 最近原文和该 Run 生成的 episodic Memory 同时被注入 | 按 `provenance_ref` 去重近期同源经历；不删除 Memory，不排除其他会话或更早来源 |
| 截断后整轮直接失败 | Ollama 明确 length、Responses incomplete、Claude/Kimi 长度停止缺少统一恢复路径 | 统一已知长度失败。供应商实际支持输出上限时，可在原整轮预算、剩余步数和窗口内扩大一次生成；仍失败则清楚结束，避免循环 |
| Ollama 正常回复被中断 | `prompt_eval_count >= num_ctx - 16` 直接抛 `ContextTruncated` | 该计数只保留为 `myth_context_pressure`。明确 length / 不完整终态仍拒绝提交为完整回答 |
| 模型正在写，页面却一直空等 | Responses 已读取 SSE，但到终态才返回；Ollama 使用非流式调用 | Web 主对话接入 SSE/NDJSON 回答预览，复用既有轮询。普通正文出现后即可显示，完整决定仍等终态 |
| 缓存使用不完整 | Claude 未启用缓存；Ollama 漏读官方缓存计数；动态数据改写系统指令 | Claude 加自动缓存；Ollama 消费 `prompt_eval_cached_count`；OpenAI 新缓存写入字段也保留。固定指令、历史与动态数据分开排列 |
| 发送前额外等待 | 远端模型目录每次检查；公开价格冷查询超时可达 6 秒 | 成功远端目录缓存 60 秒，显式检查可刷新，认证变更清除缓存。发送只读现有价格，旧报价明确标记过期 |
| 目录能力没有被正确采用 | DeepSeek 目录使用 `source=remote`，窗口冻结却只接受 `provider` | 精确型号且真实目录来源为 provider/remote 时都能冻结；适配器按前缀推测的能力仍不冒充供应商报告 |
| 长会话的准入装载过多 | 为版本核对反复调用完整 session/turn 投影，逐轮加载步骤、账户、游标与重连信息 | 只读取准入所需轮次身份、状态与完整快照；版本核对内容保留 |
| UI 和构建负担 | 两层重复主题覆盖；React 只为一个保存按钮引入 HeroUI/Tailwind | 删除近 200 行重复主题装饰，首页使用简单入口，输入框去浮影；保存按钮改为原生表单，移除 63 个安装依赖包 |
| Windows 构建摘要不稳定 | React staging 按 CRLF 原字节计算摘要，Git checkout 又会统一为 LF | 对三个文本产物先统一 LF 再计算清单，新增跨换行回归 |

保存的 Assistant 正文路径未发现固定字符数裁切；短工具预览、Context Anchor 和 Memory 摘录另有有损投影，不能混作“完整回复”。本轮未把它们全量展开塞回提示。

## 实测

输入与数据集固定，不调用真实模型。原始结果见 [修改前](evidence/usability-20261019-before.json)、[修改后](evidence/usability-20261019-after.json)。

| 指标 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 普通中文问题默认可见工具 | 23 | 13 |
| 固定系统指令 UTF-8 字节 | 6,589 | 1,218 |
| “Python 的列表和元组有啥区别？”消息 UTF-8 字节 | 7,002 | 3,683 |
| 同请求的本地序列化对象字节，含 schema/报告 | 20,599 | 13,128 |
| 40 轮历史：上下文准备 SQL 次数 | 418 | 18 |
| 同一准备中的历史步骤查询 | 80 | 0 |
| 同一准备的本机耗时中位数，3 次 | 11.525 ms | 7.728 ms |
| React 随包 CSS | 455,984 B | 35,964 B |
| React 随包 JS | 588,412 B | 约 509.7 KB |

字节数不是 Token 用量；本地序列化对象还包含不发送给供应商的报告。SQL 优化的实测量级为毫秒，秒级等待的改善仍需在用户实际模型、硬件与网络上测量。React CSS 缩小约 92.1%，JS 缩小约 13.4%；剩余 JS 仍值得做按页面加载。

## 生成、截断和缓存的准确含义

- 预览只存在于 Web Driver 的临时展示状态，按顶层 reply/completion 的 `claim` 提取；工具参数不会被当成回答。预览不进入 Context、请求身份、收据或授权。完整 JSON、终态与本地校验通过后才提交真正回答。
- Responses/Ollama 流中断后仍按原有 UNKNOWN 处理。明确长度失败先结算已有收据，再准入一次不同的生成机会，不能重放原 Ticket；崩溃恢复复用同一收据。
- `max_output_tokens` 是初始生成预算，整轮输出预算保持冻结。GPT OAuth 当前 wire 不接受这项输出上限，因此不做“提高本地数字后重发同一请求”的无效恢复。其远端长度限制仍可能导致明确失败。
- 输入接近 Ollama 窗口不能证明被截断。原有字节预算仍为近似，真实长上下文保真度需要模型实验；不以一条计数阈值伪装成已确认错误。字段定义见 [Ollama Chat API](https://docs.ollama.com/api/chat)。
- OpenAI 支持模型的缓存默认启用，共享前缀与供应商实际计量决定命中；新增一个本地缓存对象或随意添加 key 都不证明节省。短提示不为凑缓存门槛填充内容。见 [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)。
- Claude 自动缓存通过请求的 `cache_control` 启用，命中只按返回用量展示。见 [Claude prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)。DeepSeek/OpenAI 原有缓存读数继续按 Usage 接收，未报告的计量保持未知。

## 验证与边界

机器可读记录见 [验证清单](evidence/usability-20261019-validation.json)。真实浏览器画面：[原生桌面](evidence/usability-20261019-desktop.png)、[原生手机](evidence/usability-20261019-mobile.png)、[React 桌面](evidence/usability-20261019-react.png)，均使用固定测试资料。覆盖：

- 897 项 Python 回归，包含新增 20 项可用性回归和 1 项构建换行回归；Windows 不具备符号链接权限的两项另记跳过。可选 MCP 已另装依赖，用真实本地 stdio 服务验证。
- 原生 JS 77 项合同；React TypeScript、6 项 API/草稿测试与生产构建。
- 原生工作台 5 宽度 × 2 主题 × 13 状态；React 随包页面 10 组画面与完整工作流。
- 两个入口都在真实 HTTP/SQLite/Driver 下检查：生成预览出现时没有 Assistant 持久消息、没有 COMPLETED；终态后只有一条完整回答。
- wheel/sdist、封闭静态资源与安装后的真实 HTTP/API 检查。构建产物按当前生成字节核对。

本轮没有取得用户实际的 DeepSeek / Ollama / GPT OAuth 模型配置和在线推理样本。本机 `127.0.0.1:11434` 未能响应；远端实际 TTFT、缓存命中率、账单、任务质量与反复澄清概率均未实测。固定 Provider 的通过只说明对应软件行为。

## 后续建设顺序

1. **把日常任务做成发布门禁。** 固定问候、自由措辞问答、写作、读取项目、一次澄清后继续、长回答、工具错误后修正等任务；保存完整问题、模型 ID、设置、回答、终态、请求数、澄清数、首字与总耗时、实测 Token。评价整份答案，不能只判有没有 JSON 或 COMPLETED。
2. **减少对话对规划协议的依赖。** 目前仍用结构化决定承载普通答案。下一次按供应商原生文本/工具调用设计传输，并用同一任务对照验证；不再在提示中解释每一套 Runtime 术语，也不靠继续扩大正则路由判断所有问题。
3. **收窄会话读取。** 当前会话 API 仍投影历史轮次、事件和执行图。应把当前聊天、累计统计、历史详情分页与按需展开分开测量，避免每次轮询重做完整观测。
4. **先选定产品主路径。** 普通对话、读资料、有限文件任务优先稳定。当前没有任意 shell，修改工具生成受管副本，测试入口受固定 profile 约束；用户遇到这些真实能力边界时，提示词无法让任务自动完成。扩为代码 Agent 应以明确的实际执行场景设计能力。
5. **收敛双 UI 与常驻机制。** 完成真实账号和功能等价验收后选择一个正式界面，归档另一套；Model Pool、语义治理、SOTA/Evolution 等按实际任务启用，避免围绕每个简单问题常驻一整套治理说明。

保留 Run、真实副作用的 Ticket/Receipt、UNKNOWN、取消与凭据边界；以使用证据决定哪些机制应在热路径中运行。评价下一次改动的标准是用户少等、少问、能完成任务，并且花销可核对。
