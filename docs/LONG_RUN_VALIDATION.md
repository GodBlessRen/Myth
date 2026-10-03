# Long-run Validation / 长任务耐久验证

Myth v0.23 把“能恢复”与“真的跑过 2–3 小时”分开验证。CI 的秒级测试只证明状态机和 no-replay 合同；真实长跑必须显式执行 soak harness。

## 1. 180 分钟健康浸泡

```bash
python scripts/soak_long_run.py --duration-minutes 180 --tool-steps 24 --root .soak/myth-180m
```

该测试只有一个用户输入、一个 `run_id`。本地确定性 Provider 会把总 wall-clock 分摊到 25 次模型机会（24 个 `math.calculate` checkpoint + 1 次最终回复），Durable Executor 在整个过程中持续续租。

验收条件：

- 最终 `status=COMPLETED`；
- `tool_calls_settled=24`；
- `model_calls_settled=25`；
- `model_calls_unknown=0`；
- Execution Cursor 持续推进；
- Executor / Driver heartbeat 与 durable progress 都能在 Runtime Observatory 观察；
- Assistant 回复显示最终“用时”，第三栏另显示 `Model wall`。

## 2. 120 分钟健康浸泡

```bash
python scripts/soak_long_run.py --duration-minutes 120 --tool-steps 24 --root .soak/myth-120m
```

建议 120m 与 180m 至少各跑一次。两次都使用不同 root，避免证据互相覆盖。

## 3. UNKNOWN / no-replay 故障注入

```bash
python scripts/soak_long_run.py --duration-minutes 5 --tool-steps 12 --fault-call 6 --root .soak/myth-unknown
```

第 6 次模型调用在 Ticket 已签发后抛出 ambiguous timeout。正确结果不是“自动重试直到成功”，而是：

```text
UNKNOWN
  ↓
RECONCILE
  ↓
subsequent executor ticks do not call provider again
```

报告中的 `no_replay_after_unknown` 必须为 `true`。

## 4. 时间指标定义

回复旁：

```text
用时 2分 55秒
```

定义为“本轮最近用户输入持久化 → 对应 Assistant 回复持久化”的整体 wall-clock。它包含模型、工具、排队、本地处理和网络等待，因此不能称为纯模型推理时延。

第三栏 `Model wall` 是 Runtime 围绕每次 `provider.invoke` 实测并聚合的 wall-clock，同样包含网络/排队/生成，但排除了本地工具执行和两次模型调用之间的 Runtime 工作。

如果供应商自己报告更细粒度内部时延（例如 Ollama `model_duration_ns`），应继续作为独立 provider metric 保存，不能覆盖上述两种 Runtime 指标。
