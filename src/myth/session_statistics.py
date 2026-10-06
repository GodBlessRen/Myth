"""Observability 的会话统计纯投影。
消费已有模型计量和工具收据，按实际调用汇总；不执行 I/O，不结算预算，不从缺失值推断零用量。
"""


# 持久计量只接受非负整数；bool/文本/负数不是实测值，缺测保留 None。
def measured_integer(value):
    return value if type(value) is int and value >= 0 else None


# 会话内每个 Attempt/工具决定只计一次；对象没有稳定身份时按独立样本处理，便于旧投影兼容。
def unique_records(records, identity):
    seen = set()
    for record in records:
        key = record.get(identity)
        key = key if isinstance(key, str) and key else None
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        yield record


def usage_measurements(invocations, fields):
    """按 Attempt 聚合公开用量；完整总量要求每个调用实测，样本数说明覆盖。

    没有调用时总量为 0；有调用但部分缺测时为 None，不能拿已结算预算代替供应商实测。
    Web 与 SOTA 共用这个纯函数，不访问数据库或改变收据。
    """
    records = list(unique_records(invocations, "model_attempt_id"))
    totals = {field: 0 for field in fields}
    samples = {field: 0 for field in fields}
    for item in records:
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        for field in fields:
            value = measured_integer(usage.get(field))
            if value is not None:
                totals[field] += value
                samples[field] += 1
    return {
        "attempts": len(records),
        "samples": samples,
        "totals": {field: totals[field] if samples[field] == len(records) else None for field in fields},
    }


# 累计已报告耗时、按调用平均 TTFT；TPS 仅配对成功调用自己的输出/用时，不能借用其他调用的时间。
def session_statistics(invocations, operations):
    model_ms = tool_ms = ttft_ms = output_tokens = output_wall_ms = 0
    model_samples = tool_samples = ttft_samples = tps_samples = 0
    model_attempts = tool_calls = 0
    for item in unique_records(invocations, "model_attempt_id"):
        model_attempts += 1
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        wall = measured_integer(usage.get("provider_wall_ms"))
        first = measured_integer(usage.get("time_to_first_token_ms"))
        tokens = measured_integer(usage.get("output_tokens"))
        if wall is not None:
            model_samples += 1
            model_ms += wall
        if first is not None and (wall is None or first <= wall):
            ttft_samples += 1
            ttft_ms += first
        # FAILED/UNKNOWN/零派发不参加输出速率；毫秒分辨率为零时没有可靠的除数。
        if item.get("outcome") == "SUCCEEDED" and tokens is not None and wall is not None and wall > 0:
            tps_samples += 1
            output_tokens += tokens
            output_wall_ms += wall
    for item in unique_records(operations, "decision_id"):
        tool_calls += 1
        wall = measured_integer(item.get("tool_wall_ms"))
        if wall is not None and item.get("state") == "RESOLVED":
            tool_samples += 1
            tool_ms += wall
    return {
        "model_wall_ms": model_ms if model_samples or not model_attempts else None,
        "model_timing_samples": model_samples,
        "model_attempts": model_attempts,
        "tool_wall_ms": tool_ms if tool_samples or not tool_calls else None,
        "tool_timing_samples": tool_samples,
        "tool_calls": tool_calls,
        "average_ttft_ms": ttft_ms / ttft_samples if ttft_samples else None,
        "ttft_samples": ttft_samples,
        "output_tps": output_tokens * 1000 / output_wall_ms if output_wall_ms else None,
        "tps_samples": tps_samples,
        "tps_output_tokens": output_tokens,
        "tps_wall_ms": output_wall_ms,
        "tps_basis": "end_to_end",
    }
