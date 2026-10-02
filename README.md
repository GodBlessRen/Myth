# Myth

**模型提出步骤，Runtime 授权与记录，独立验收决定完成。**

Myth v0.4 是单机、单 Agent 的文件任务工作台。目前可完成有明确规则的 UTF-8 精确替换任务：提交时固定文件基线和期望结果，在受管副本中读取、修改，核对全部允许文件后下载结果。原文件保留。

## 立即体验

Python 3.12+，运行时仅使用标准库，无前端构建或 CDN。

```bash
python -m pip install -e .
myth --root . web
```

访问 `http://127.0.0.1:8765/`，点击「体验一个完整任务」。演示会实际执行读取、替换、核验、交付，使用确定性 `scripted` provider，无需模型或密钥。**演示成功证明本地执行链路，不能证明真实模型能力。**

Windows 也可在仓库目录运行：

```powershell
.\start-myth.ps1
```

无需安装的源码入口：

```powershell
$env:PYTHONPATH = 'src'
python -m myth.cli demo
```

## 自己的文件任务

在页面填入文件路径和替换规则，选择执行方式，再开始任务。多个规则按提交顺序计算期望结果；全部允许文件都参加验收，包括未修改文件。最多 16 个文件，每个不超过 1 MB；当前要求文件名互不重复。

CLI 示例：

```bash
myth --root . agent --provider scripted --model exact-patch-demo --allow-file examples/example.txt --acceptance examples/acceptance.json "Replace foo with bar"
```

验收 JSON 是规则数组：

```json
[
  {"path": "example.txt", "old_text": "foo", "new_text": "bar", "expected_count": 1}
]
```

`old_text` 必须非空，匹配次数必须与 `expected_count` 一致。BOM、CRLF 及无关内容按原始字节保留。自然语言任务描述用于指导模型；**固定规则才是本版本可独立验证的完成标准**。未提供规则的任务可检查、执行，但不会获得 Agent 交付。

## 真实模型入口

保留 Ollama、OpenAI Responses 和 Pi OAuth 三种适配器。先检查可用性：

```bash
myth provider-check --provider ollama --model <model>
myth --root . agent --provider ollama --model <model> --allow-file examples/example.txt --acceptance examples/acceptance.json "Replace foo with bar"
```

OpenAI 使用进程环境变量 `OPENAI_API_KEY`，切换为 `--provider openai`。Pi 适配器要求已经登录的 Pi 能执行 `pi auth print-bearer-token --provider openai --min-expiry 10m`，使用 `--provider pi-openai`；凭据仍由 Pi 管理。

本轮没有实际调用这些真实模型，Pi 的当前 CLI 兼容性也未实测。`provider-check` 只证明就绪检查通过，不能替代完整任务验收。远程 provider 会收到任务、允许文件路径、验收规则和上下文；需要内容留在本地时使用本地演示或本地 Ollama。

## 暂停、续跑与取消

页面支持回答当前问题、停止任务，以及在进程退出后「核对记录并继续」。CLI 等价入口：

```bash
myth agent-status <run_id>
myth continue-agent --provider scripted --model exact-patch-demo <run_id>
myth answer-agent --provider scripted --model exact-patch-demo <run_id> <question_id> "answer"
myth cancel-agent <run_id>
```

操作时使用创建任务的同一个 `--root`。续跑使用持久化的模型与限制，provider 必须匹配；答复必须匹配当前 `question_id`，旧答复不能消费新问题。取消阻止新的启动授权和交付，已经获 Ticket 的调用可能仍完成，其迟到事实需要对账。

模型请求按运行与步骤去重；工具决策绑定一个 Action。已有收据可恢复，发出 Ticket 后结果不明则保留 `UNKNOWN` 与预算占用，不盲目重试。单机 OS 锁防止两个驱动器同时推进同一运行。浏览器刷新只恢复查看状态。

## 架构与完成边界

```text
CLI / Web → AgentRuntime（装配）
                   ↓
            application.AgentDriver
                   ↓ ports
        SQLite Repository / Local Execution
                   ↓
        P1 工具账本 / P2 模型账本 / Provider

acceptance：纯目标验收与上下文投影，无数据库或文件 I/O
```

Agent 用例已分离纯逻辑、端口和适配器，事务级端口拥有状态提交。P1/P2 的底层账本保留原实现，后续逐步迁移；全仓库尚未完成六边形重构。

- `file.read`：受管副本分页读取；快照、计量与内部读取收据一起提交。
- `file.patch_exact`：Action → Attempt → Ticket → 文件效果 → Receipt。
- 独立验收：固定期望完整摘要、未修改文件、运行所属成功证据、无剩余事项同时一致才交付。
- 下载固定摘要对应的不可变对象，后来修改展示副本不会改写已交付内容。
- 上下文：确定性投影、用户更正与证据引用保留，必需内容超预算时在模型调用前停止；当前没有长期记忆或 RAG。

详见 [架构](docs/ARCHITECTURE.md)、[设计](docs/DESIGN.md)、[后续规划](docs/ROADMAP.md)、[验证范围](docs/VALIDATION.md) 和 [安全边界](SECURITY.md)。

## 验证

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

测试覆盖错误结果带成功收据、固定基线、多文件保留、请求冲突、取消/澄清竞态、真实子进程硬退出恢复、HTTP 交付和同源限制。见验证文档中的实测范围。

Myth 当前适合小规模、可精确定义结果的本地文件任务。通用代码编辑、任意 shell、语义测试验收、RAG、长期记忆、分布式执行与生产多用户服务仍在后续规划。
