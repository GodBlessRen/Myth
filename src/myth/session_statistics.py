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


# 耗时与 TTFT 只用真实计量；可见输出 TPS 接受明确标记的估计值，但不参与任何结算。
def session_statistics(invocations, operations):
    model_ms = tool_ms = ttft_ms = output_tokens = output_wall_ms = 0
    model_samples = tool_samples = ttft_samples = tps_samples = 0
    tps_estimated_samples = tps_raw_proxy_samples = 0
    model_attempts = tool_calls = 0
    for item in unique_records(invocations, "model_attempt_id"):
        model_attempts += 1
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        wall = measured_integer(usage.get("provider_wall_ms"))
        first = measured_integer(usage.get("time_to_first_token_ms"))
        # 新收据优先：明确可见量 > 上游有界估算 > 旧收据的原始输出代理。
        # 未知 reasoning 绝不能默认为已实测的 0；代理一律标记为估计。
        tokens = measured_integer(usage.get("visible_output_tokens"))
        estimated = False
        raw_proxy = False
        if tokens is None:
            tokens = measured_integer(usage.get("estimated_visible_output_tokens"))
            if tokens is not None:
                estimated = True
            else:
                raw = measured_integer(usage.get("output_tokens"))
                thoughts = measured_integer(usage.get("reasoning_tokens"))
                if raw is not None:
                    # 旧收据没有 total/shape；按 Hindsight 的 Folded 保守读法估计。
                    # reasoning 大于 raw 时可能是 Unfolded，保留 raw 代理而不是伪造 0。
                    tokens = raw - thoughts if thoughts is not None and thoughts <= raw else raw
                    estimated = True
                    raw_proxy = True
        if wall is not None:
            model_samples += 1
            model_ms += wall
        if first is not None and (wall is None or first <= wall):
            ttft_samples += 1
            ttft_ms += first
        # 只配对同一次成功调用自己的耗时；FAILED/UNKNOWN/零耗时不进入分母。
        if item.get("outcome") == "SUCCEEDED" and tokens is not None and wall is not None and wall > 0:
            tps_samples += 1
            tps_estimated_samples += int(estimated)
            tps_raw_proxy_samples += int(raw_proxy)
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
        "tps_estimated_samples": tps_estimated_samples,
        "tps_raw_proxy_samples": tps_raw_proxy_samples,
        "tps_output_tokens": output_tokens,
        "tps_wall_ms": output_wall_ms,
        "tps_basis": "end_to_end",
    }



# 基于同 Run 冻结请求与已结算模型用量形成后验实测校准；本函数不访问对象库或持久化第二份事实。
def context_cost_calibration(events, invocations):
    """按 Provider+模型聚合实际 Context 字节和已报告 Input Token，保留样本覆盖与缺测。

    返回的是可观察的 Context 字节 / Provider 计量比，不是 tokenizer 精确计数；
    schema、传输包装、cache 和历史转换都可能影响 Provider 实际 Token 用量。
    """
    compiled = {}
    for item in events:
        if not isinstance(item, dict) or item.get("kind") != "ConversationContextCompiled":
            continue
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        attempt = payload.get("model_attempt_id")
        if isinstance(attempt, str) and attempt:
            # 一个 Ticket 对应一个冻结请求，重复展示同一事件不能制造更多样本。
            compiled.setdefault(attempt, payload)
    invocations_by_id = {}
    for item in unique_records(invocations, "model_attempt_id"):
        if not isinstance(item, dict):
            continue
        attempt = item.get("model_attempt_id")
        if isinstance(attempt, str) and attempt:
            invocations_by_id[attempt] = item

    grouped = {}
    for attempt, projection in compiled.items():
        invocation = invocations_by_id.get(attempt) or {}
        provider = str(invocation.get("provider_id") or "unknown")
        model = str(invocation.get("model_id") or "unknown")
        key = (provider, model)
        group = grouped.setdefault(key, {
            "provider": provider, "model": model, "attempts": 0,
            "input_token_samples": 0, "context_byte_samples": 0,
            "serialized_byte_samples": 0, "paired_samples": 0,
            "paired_input_tokens": 0, "paired_context_bytes": 0,
            "total_serialized_bytes": 0,
        })
        group["attempts"] += 1
        usage = invocation.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        tokens = measured_integer(usage.get("input_tokens"))
        visible_bytes = measured_integer(projection.get("bytes_used"))
        serialized_bytes = measured_integer(projection.get("serialized_request_bytes"))
        # 每个度量独立计覆盖率；仅同时实测的请求才能计算跨量纲比率。
        if tokens is not None:
            group["input_token_samples"] += 1
        if visible_bytes is not None:
            group["context_byte_samples"] += 1
        if serialized_bytes is not None:
            group["serialized_byte_samples"] += 1
            group["total_serialized_bytes"] += serialized_bytes
        if tokens is not None and visible_bytes is not None:
            group["paired_samples"] += 1
            group["paired_input_tokens"] += tokens
            group["paired_context_bytes"] += visible_bytes

    rows = []
    for key in sorted(grouped):
        group = grouped[key]
        paired_tokens = group["paired_input_tokens"]
        rows.append({
            "provider": group["provider"],
            "model": group["model"],
            "attempts": group["attempts"],
            "input_token_samples": group["input_token_samples"],
            "context_byte_samples": group["context_byte_samples"],
            "serialized_byte_samples": group["serialized_byte_samples"],
            "paired_samples": group["paired_samples"],
            # 仅完整配对才能把聚合值称作该组总量；部分观察只给局部比值及分母。
            "reported_input_tokens": (
                group["paired_input_tokens"]
                if group["paired_samples"] == group["attempts"] else None
            ),
            "context_bytes": (
                group["paired_context_bytes"]
                if group["paired_samples"] == group["attempts"] else None
            ),
            "serialized_request_bytes": (
                group["total_serialized_bytes"]
                if group["serialized_byte_samples"] == group["attempts"] else None
            ),
            "observed_context_bytes_per_reported_input_token": (
                round(group["paired_context_bytes"] / paired_tokens, 4)
                if paired_tokens > 0 else None
            ),
            "measured_pair_coverage": (
                round(group["paired_samples"] / group["attempts"], 4)
            ),
        })
    return {
        "source": "persisted-context-compiler-and-model-usage",
        "semantics": "observed-projection-ratio-not-tokenizer-upper-bound",
        "attempts": len(compiled),
        "groups": rows,
        "safe_to_expand_context_budget": False,
    }
