# 固定日常任务基线

`evals/daily-v1.json` 包含 10 个固定任务：算术、资料事实、文件读取、项目搜索、资料合并、文本/JSON 生成、精确修改副本、安全中断恢复、跨会话 Goal 延续。

每题默认重复三次，两组各 30 次。Myth 使用当前 Intent Pick；simple-loop 强制 Agent route，复用同一个 Runtime、模型、工具、预算与 ContextCompiler。这是路由及其后续上下文决策的消融对照，不是与另一个框架比较。

## 运行

在仓库根目录：

```powershell
$env:PYTHONPATH = 'src'
# 验证运行器和 oracle；不证明真实模型质量
python -m myth.cli task-benchmark --output .runtime/benchmarks/fixture-run

# 真实本地模型；先用 provider-check 确认已安装的准确模型名
python -m myth.cli task-benchmark --provider ollama --model openbmb/minicpm5-2b:f16 --output .runtime/benchmarks/model-run
```

支持 `--provider openai/chatgpt`；沿用 `--root` 的认证配置，API key 仍只从环境变量读取。`--ollama-url` 可选择本地服务；运行器不安装/下载模型。

`--repeats 1..10`、`--arm myth/simple-loop`、`--case CASE_ID` 可用于诊断。筛选题目的报告永远不会声称 complete suite。输出目录必须是新目录，运行器不会覆盖历史证据。只要有失败，CLI 返回 exit code 1；失败仍计入完整分母。

## 证据

每个试次在独立持久 root 运行，保留 SQLite、Ticket、Receipt、Model Request/Response objects 和 Artifact bytes。`report.json` 每题原子写入，进程中断时可读取已完成试次；`suite.json` 固定原任务。

报告记录 suite digest、Runtime version/source digest、provider/model/settings、repeat/arm、Run IDs、status、独立 checks、错误分类、elapsed time、模型/工具调用、provider usage、重复工具调用、Context selected/folded/dropped、证据目录。

Oracle 只检查可明确自动验收的内容：

- 最后轮次是否 COMPLETED；
- 要求的工具是否有结果；
- Artifact content-addressed bytes 是否与预期完全一致；
- 原文件字节是否保持不变；
- 最终回答是否含固定事实 token；
- 延续任务的前置轮次是否完成。

回答 token 检查不是开放式语义评测；它不能识别所有矛盾、冗余或缺失。模型声称“生成成功”但 Artifact bytes 不合格会计入 `completion_without_acceptance`。步数耗尽、UNKNOWN、WAITING_USER 等计入 `human_takeover`，这是需要人工介入的代理指标，不是实际人工操作计时。

`recovery_success` 仅在模型调用前的安全中断题测量。真实 provider UNKNOWN 的核对成功率当前填 null/not measured；不向模型服务盲目重发制造一个虚假 PASS。跨模型中途断电、语义正确率、真实用户耗时、多周连续自用也未由这个小集合证明。

意外 runner exception 保留失败项，分类为 runner，模型调用量为 null/not measured；不能被筛掉或当成模型质量失败。替身报告始终标记 `harness_fixture`；真实调用标记 `real_provider`。

模型 tag 可能更新；Ollama 报告额外读取并保存当时的模型 digest/metadata（不可读取时标明未测量）。请求仍按模型名称调用，不能据此宣称服务在运行期间不可能更新权重。报告也不宣称三次固定温度重复是独立统计样本。

## 发布判断

先查看全部试次和失败，而不是只看通过率。当前 Run COMPLETED 表示对话已结束；只有独立 checks 能支撑对应的任务验收。任务基线不自动 promote policy、扩大工具权限或开启未声明计划。
