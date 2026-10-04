// Runtime Observatory：只读展示真实执行链、预算、上下文和恢复事实。
// 依赖 app.js 的 DOM/状态助手；本文件没有执行授权，UNKNOWN/N/A 和 planned 均保持显式。
"use strict";

// 业务值仅作中文投影；UNKNOWN 保留协议名，陌生状态原样可见，不能推断为成功。
function inspectorStateText(status) {
  const value = String(status ?? "");
  const labels = {
    IDLE: "待命", ACTIVE: "进行中", READY: "待开始", RUNNING: "运行中",
    WORKING: "进行中", COMPLETED: "已完成", SUCCEEDED: "已成功", DONE: "已完成",
    WAITING_USER: "等待回复", WAITING: "等待中", PAUSED: "已暂停",
    RECOVERING: "恢复中", RECOVERY_REQUIRED: "需要恢复", RECONCILING: "核对中",
    INTERRUPTED: "已中断", FAILED: "已失败", CANCELLED: "已取消",
    BUDGET_EXHAUSTED: "预算已用尽", UNKNOWN: "UNKNOWN · 待核对",
    UNVERIFIED: "未验收", VERIFIED: "已验收", PASSED: "已通过", INVALIDATED: "已失效",
    NONE: "无", RESOLVED: "已核定", PREPARED: "已准备", STARTED: "已启动",
    RESERVED: "已预留", NOT_STARTED: "未启动", STALE: "心跳过期",
    STOPPED: "已停止", BLOCKED: "待处理", CLOSED: "已关闭",
  };
  return labels[value.toUpperCase()] || value || "—";
}

// 缺测保留 N/A；只格式化服务端真实数值，零不与缺失合并。
function inspectorNumber(value, suffix = "") {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value.toLocaleString("zh-CN") + suffix : "N/A";
}

// 观测心跳只更新变化的区块；保留文本选择与折叠状态，不反复替换静态事实。
function inspectorRegion(id, facts) {
  const box = $(id);
  if (!box) return null;
  const signature = JSON.stringify(facts);
  if (box.dataset.signature === signature) return null;
  box.dataset.signature = signature;
  box.replaceChildren();
  return box;
}

// 将业务状态映射为视觉类别；文字和颜色均不修改持久状态。
function inspectorStatus(status) {
  const value = String(status || "IDLE").toUpperCase();
  const label = inspectorStateText(value);
  if (["COMPLETED", "SUCCEEDED"].includes(value)) return [label, "success"];
  if (["RUNNING", "WAITING_USER", "RECOVERING", "PAUSED"].includes(value))
    return [label, "running"];
  if (
    ["INTERRUPTED", "RECOVERY_REQUIRED", "RECONCILING", "UNKNOWN"].includes(
      value,
    )
  )
    return [label, "unknown"];
  if (["FAILED", "CANCELLED", "BUDGET_EXHAUSTED"].includes(value))
    return [label, "danger"];
  return [label, ""];
}

// 构造执行链的一项事实节点；标签/摘要不代替 Ticket 或 Receipt。
function spineStep(label, detail, stateName, stateLabel) {
  const row = el("div", "spine-step " + (stateName || ""));
  row.append(el("span", "spine-node"));
  const copy = el("div", "spine-copy");
  copy.append(el("strong", "", label), el("small", "", detail || ""));
  row.append(copy, el("span", "spine-state", stateLabel || ""));
  return row;
}

// 展示最新决定、授权、效果与回答链；模型提案和真实执行凭证分开展示。
function renderExecutionSpine(turn) {
  const box = inspectorRegion("executionSpine", [turn?.status, turn?.current_step, turn?.max_steps, turn?.activities, turn?.operations, turn?.error]);
  if (!box) return;
  if (!turn) {
    box.append(
      el(
        "div",
        "spine-empty",
        "等待执行",
      ),
    );
    return;
  }
  const latest = (turn.activities || []).at(-1);
  const decision = latest?.decision;
  const operation = (turn.operations || []).at(-1);
  const result = operation?.result || latest?.result;
  const hasDecision = !!decision;
  box.append(
    spineStep(
      "Decision",
      hasDecision
        ? decision.decision_type === "tool_call"
          ? decision.capability_id
          : decision.decision_type
        : "步骤 " + inspectorNumber(turn.current_step) + " / " + inspectorNumber(turn.max_steps),
      hasDecision ? "done" : turn.status === "RUNNING" ? "active" : "",
      hasDecision ? "已绑定" : turn.status === "RUNNING" ? "等待中" : "—",
    ),
  );
  if (operation) {
    const authorityDetail = operation.ticket_id
      ? operation.capability + " · " + operation.ticket_id
      : operation.capability + " · 已记录意图";
    const opState =
      operation.state === "RESOLVED"
        ? "done"
        : operation.state === "UNKNOWN"
          ? "unknown"
          : "active";
    box.append(spineStep("Ticket", authorityDetail, opState, inspectorStateText(operation.state)));
  } else {
    box.append(
      spineStep(
        "Authority",
        decision?.decision_type === "tool_call"
          ? "提案尚未获得持久 Ticket"
          : "本步骤未准入外部工具",
        decision?.decision_type === "tool_call" ? "active" : "",
        decision?.decision_type === "tool_call" ? "待检查" : "—",
      ),
    );
  }
  let resultDetail = "尚无持久工具结果",
    resultState = "",
    resultLabel = "—";
  if (result) {
    if (result.error) {
      resultDetail = result.error;
      resultState = "unknown";
      resultLabel = "待检查";
    } else {
      resultState = "done";
      resultLabel = "已记录";
      if (result.evidence_ref) resultDetail = result.evidence_ref;
      else if (result.artifact?.name)
        resultDetail = "Artifact · " + result.artifact.name;
      else if (result.matches?.length !== undefined)
        resultDetail = result.matches.length + " 个项目匹配";
      else if (result.output !== undefined)
        resultDetail = String(result.output || "无输出").slice(0, 160);
      else if (result.sources?.length)
        resultDetail = result.sources.length + " 个来源已记录";
      else if (result.value !== undefined)
        resultDetail = "结果 · " + result.value;
      else resultDetail = "工具结果已保存";
    }
  }
  box.append(spineStep("Result", resultDetail, resultState, resultLabel));
  let completionDetail = "等待回答",
    completionState = "",
    completionLabel = "—";
  if (turn.status === "COMPLETED") {
    completionDetail =
      "回答已完成，目标验收单独记录";
    completionState = "done";
    completionLabel = "已回答";
  } else if (turn.status === "WAITING_USER") {
    completionDetail = "等待你补充信息";
    completionState = "active";
    completionLabel = "待回复";
  } else if (turn.status === "PAUSED") {
    completionDetail =
      "已在安全点暂停；已有 Ticket 仍有效";
    completionState = "active";
    completionLabel = "已暂停";
  } else if (turn.status === "INTERRUPTED") {
    completionDetail =
      turn.error || "Driver 已停止，可从检查点恢复";
    completionState = "unknown";
    completionLabel = "可恢复";
  } else if (turn.status === "UNKNOWN") {
    completionDetail =
      turn.error || "结果为 UNKNOWN，需先核对外部效果";
    completionState = "unknown";
    completionLabel = "待核对";
  } else if (
    ["FAILED", "CANCELLED", "BUDGET_EXHAUSTED"].includes(turn.status)
  ) {
    completionDetail = turn.error || inspectorStateText(turn.status);
    completionState = "unknown";
    completionLabel = inspectorStateText(turn.status);
  }
  box.append(
    spineStep("Completion", completionDetail, completionState, completionLabel),
  );
}

// 展示服务端从 durable facts 生成的实验性 Execution Graph；UI 不自行推断缺失边或创建执行真相。
function renderExecutionGraph(turn) {
  const graph = turn?.execution_graph;
  const box = inspectorRegion("inspectorExecutionGraph", graph || null);
  if (!box) return;
  if (!graph?.nodes?.length) {
    box.append(el("div", "inspector-empty", "暂无可投影执行图"));
    return;
  }
  const edgeByTarget = new Map(
    (graph.edges || []).map((edge) => [edge.target, edge]),
  );
  graph.nodes.forEach((node, index) => {
    const row = el("div", "execution-graph-row " + (node.kind || ""));
    row.style["--graph-depth"] = String(Math.max(0, Number(node.depth) || 0));
    const edge = edgeByTarget.get(node.id);
    const lead = el("span", "execution-graph-lead", index === 0 ? "●" : edge?.kind === "delegate" ? "↳" : "↓");
    const copy = el("div", "execution-graph-copy");
    copy.append(
      el("strong", "", node.label || node.kind || "node"),
      el("small", "", node.detail || ""),
    );
    const [, stateClass] = inspectorStatus(node.state || "");
    const state = el("span", "execution-graph-state " + stateClass, inspectorStateText(node.state || "UNKNOWN"));
    row.append(lead, copy, state);
    box.append(row);
  });
  const coverage = graph.coverage || {};
  if (coverage.unmapped_model_calls) {
    box.append(
      el(
        "div",
        "execution-graph-note",
        "投影未覆盖 " + inspectorNumber(coverage.unmapped_model_calls) + " 次模型调用；保留原始 Trajectory 作为完整事实入口。",
      ),
    );
  }
}

// 用安全文本建立一项事实键值；对象只序列化展示，不作为新授权。
function inspectorFact(box, key, value) {
  // 英文键与协议/测试保持一致；阅读层显示简中，专业名词保留既定拼写。
  const labels = {
    State: "状态", Progress: "当前进度", Next: "下一步", Waiting: "等待事项",
    Revision: "修订", Wakeup: "唤醒计划", Due: "计划时间", Answer: "回答",
    Acceptance: "验收", Checker: "检查器", Subject: "证据摘要", Finalization: "收尾",
    "Finalize error": "收尾错误", "Work item": "工作项", "Plan rev": "计划修订",
    "Human attention": "人工处理", "Compared runs": "对比 Run", "Tool calls": "工具调用",
    Steps: "执行步数", "Work time": "工作用时", "Changed lines": "修改行数",
    Drift: "路线偏移", "Compare scope": "比较范围", Phase: "阶段", Cursor: "执行游标",
    Recovery: "恢复状态", Connection: "连接", "Next check": "下次检查",
    "Retry interval": "重试间隔", "Last progress": "最近进展", "Progress watch": "进展观察",
    Detail: "详情", Lease: "租约", Generation: "代数", "Input settled": "输入 Tokens",
    "Output settled": "输出 Tokens", "Cache hit": "Cache 命中", "Model wall": "模型用时",
    "First token": "首个 Token", "Model calls": "模型调用", "Unknown held": "UNKNOWN 占用",
    "Context window": "上下文窗口", "Token window": "Token 窗口",
    Response: "Response ID", Status: "状态", Reasoning: "Reasoning Tokens",
    Created: "创建时间", "Output types": "输出类型", Incomplete: "未完成原因",
    "Reasoning summary": "Reasoning Summary", "Provider-only fields": "Provider 特有字段",
  };
  const row = el("div", "context-fact");
  row.append(el("span", "", labels[key] || key), el("span", "context-value", value ?? "—"));
  box.append(row);
}

// 当前会话统计独立于最新 Turn；只有计量/身份变化才重绘，700ms 观测心跳不反复创建相同 DOM。
function renderSessionStatistics(session) {
  const box = $("sessionStatistics");
  if (!box) return;
  const signature = JSON.stringify([session?.id, session?.statistics]);
  if (box.dataset.signature === signature) return;
  box.dataset.signature = signature;
  box.replaceChildren();
  if (!session) {
    box.append(el("div", "inspector-empty", "选择会话查看统计"));
    return;
  }
  sessionStatisticsRows(session.statistics).forEach(({label, value, title}) => {
    const row = el("div", "context-fact");
    row.title = title;
    row.append(el("span", "", label), el("span", "", value));
    box.append(row);
  });
}

// 仅翻译仓库固定工作提示；用户、模型和异常的自由文本保持原文，持久事实不被改写。
function inspectorWorkText(value) {
  const copy = {
    "Goal created.": "目标已创建。",
    "Start or continue the next admitted work item.": "开始或继续下一项获准工作。",
    "A new admitted Turn has started for this Goal.": "此目标的新 Turn 已获准并开始。",
    "Let the current Turn reach a durable checkpoint.": "等待当前 Turn 到达持久检查点。",
    "Conversation answer persisted; semantic acceptance remains explicit.": "回答已保存；仍需明确验收。",
    "Conversation answer persisted": "回答已保存。",
    "Reconcile the uncertain attempt before continuing.": "先核对结果未知的 Attempt，再继续。",
    "Reconcile the uncertain attempt before any replay.": "先核对结果未知的 Attempt，再决定是否重放。",
    "Review the unfinished work and admit a new turn.": "检查未完成的工作，再发起新的 Turn。",
    "Waiting for user input.": "等待用户补充。",
    "user input": "用户补充",
    "Resume after the user answers the pending question.": "回答待确认的问题后恢复执行。",
    "Review the result and continue the next unfinished part of this goal.": "检查结果，继续此目标尚未完成的部分。",
    "Wait for the scheduled reconnection check.": "等待下一次连接检查。",
    "Resolve the reported provider or context blocker before a new turn.": "解决已报告的 Provider 或上下文阻碍，再发起新的 Turn。",
    "Start a new admitted turn with an adjusted budget.": "调整预算后发起新的 Turn。",
    "Resume from the last durable checkpoint.": "从最后一个持久检查点恢复。",
  };
  return Object.hasOwn(copy, value) ? copy[value] : value;
}
// 展示当前 Turn 冻结 Goal 及长期进度；回答 COMPLETED 不表示整项 Goal 验收通过。
function renderInspectorGoal(turn) {
  const box = inspectorRegion("inspectorGoal", [turn?.goal_current, turn?.snapshot?.goal, turn?.events]);
  if (!box) return;
  const goal = turn?.goal_current || turn?.snapshot?.goal;
  if (!goal?.goal_id) {
    box.append(el("div", "inspector-empty", "未绑定 Goal"));
    return;
  }
  const work = goal.work || {};
  inspectorFact(box, "Goal", goal.title || goal.goal_id);
  inspectorFact(box, "State", inspectorStateText(work.current_state || goal.state));
  inspectorFact(box, "Progress", inspectorWorkText(work.progress_note) || "—");
  inspectorFact(box, "Next", inspectorWorkText(work.next_action) || "—");
  if (work.waiting_for) inspectorFact(box, "Waiting", inspectorWorkText(work.waiting_for));
  inspectorFact(box, "Revision", work.revision ?? "—");
  const wakeup = (turn?.events || []).find(
    (event) => event.kind === "GoalWakeupAdmitted",
  );
  if (wakeup) {
    const data = wakeup.payload || {};
    inspectorFact(box, "Wakeup", data.schedule_id || "定时唤醒");
    inspectorFact(box, "Due", data.due_at || "—");
  }
}

// 展示回答、语义验收与 Work item；三者分开，避免把“已回复”画成“已验收”。
function renderInspectorDelivery(turn) {
  const box = inspectorRegion("inspectorDelivery", [turn?.status, turn?.delivery]);
  if (!box) return;
  const delivery = turn?.delivery || {};
  const acceptance = delivery.acceptance;
  const finalization = delivery.finalization;
  const items = delivery.work_items || [];
  if (!turn || (!acceptance && !finalization && !items.length)) {
    box.append(el("div", "inspector-empty", "未记录验收"));
    return;
  }
  inspectorFact(box, "Answer", turn.status === "COMPLETED" ? "已保存" : inspectorStateText(turn.status));
  inspectorFact(box, "Acceptance", inspectorStateText(acceptance?.state || "UNVERIFIED"));
  if (acceptance?.checker_id) inspectorFact(box, "Checker", acceptance.checker_id);
  if (acceptance?.subject_digest)
    inspectorFact(box, "Subject", acceptance.subject_digest.slice(0, 12) + "…");
  if (finalization) {
    inspectorFact(box, "Finalization", inspectorStateText(finalization.state));
    if (finalization.last_error)
      inspectorFact(box, "Finalize error", String(finalization.last_error).slice(0, 160));
  }
  const active =
    [...items].reverse().find((item) => !["DONE", "INVALIDATED"].includes(item.status)) ||
    items.at(-1);
  if (active) {
    inspectorFact(box, "Work item", `${active.ordinal} · ${inspectorStateText(active.status)}`);
    inspectorFact(box, "Plan rev", active.plan_revision ?? "—");
    if (active.progress_note)
      inspectorFact(box, "Progress", inspectorWorkText(active.progress_note).slice(0, 160));
  }
  if (delivery.attention?.seconds != null)
    inspectorFact(
      box,
      "Human attention",
      `${delivery.attention.seconds} 秒 · ${delivery.attention.entries} 次`,
    );
}

// 展示 SOTA Route：状态、Reasoning Cost、Reasoning Summary 与 Action Path 分开，隐藏 CoT 永远标记不可见。
function renderInspectorSotaRoute(turn) {
  const box = inspectorRegion("inspectorSotaRoute", [!!turn, turn?.sota_route]);
  if (!box) return;
  const route = turn?.sota_route;
  if (!turn || !route) {
    box.append(el("div", "inspector-empty", "暂无可比路线"));
    return;
  }
  inspectorFact(box, "State", inspectorStateText(route.status || "WORKING"));
  inspectorFact(box, "Compared runs", route.peer_count ?? "N/A");
  const current = route.metrics || {};
  const target = route.champion_costs || {};
  const pair = (label, key, suffix = "") => {
    const now = current[key];
    const old = target[key];
    const left = inspectorNumber(now, suffix);
    const right = inspectorNumber(old, suffix);
    inspectorFact(box, label, left + " / " + right + " Champion");
  };

  pair("Tool calls", "tool_calls");
  pair("Steps", "steps");
  pair("Tokens", "total_tokens");
  pair("Work time", "work_ms", " ms");
  pair("Changed lines", "code_churn_lines");

  inspectorFact(box, "Reasoning Cost", current.reasoning_tokens == null
    ? "N/A · 供应商未报告"
    : inspectorNumber(current.reasoning_tokens, " tokens"));

  const attempts = route.reasoning?.attempts || [];
  const summaries = attempts.flatMap((item) => item.summary || []);
  inspectorFact(
    box,
    "Reasoning Summary",
    summaries.length ? String(summaries.at(-1)).slice(0, 220) : "N/A · 供应商未报告",
  );
  inspectorFact(box, "Hidden CoT", "不可见，不作推断");

  const actionPath = route.action_path || [];
  const actionText = actionPath
    .map((item) =>
      item.kind === "tool"
        ? item.capability || "tool"
        : item.kind === "ask"
          ? "ask_user"
          : "reply",
    )
    .join(" → ");
  inspectorFact(box, "Action Path", actionText ? actionText.slice(0, 220) : "—");

  if (route.drift) {
    inspectorFact(
      box,
      "Drift",
      "偏离 Champion · " + (route.drift_reasons || []).join(" / "),
    );
  } else if (route.peer_count) {
    inspectorFact(box, "Drift", "在已知范围内");
  }

  const hint = route.frozen_hint;
  if (hint?.action_paths?.length) {
    inspectorFact(
      box,
      "Champion Route",
      hint.action_paths[0].join(" → ").slice(0, 180),
    );
  }
  if (hint?.reasoning_summaries?.length) {
    inspectorFact(
      box,
      "Champion Summary",
      String(hint.reasoning_summaries[0]).slice(0, 220),
    );
  }
  if (
    route.environment_scope &&
    route.environment_scope !== "project-state-v1" &&
    route.environment_scope !== "frozen-context-v1"
  ) {
    inspectorFact(box, "Compare scope", "环境未完整冻结 · 不参与 Champion 比较");
  }
}

// 投影持久游标、owner、租约与恢复建议；租约过期不证明外部效果未发生。
function renderInspectorRecovery(turn) {
  const box = inspectorRegion("inspectorRecovery", [turn?.status, turn?.execution_cursor, turn?.driver_lease, turn?.driver_active, turn?.liveness, turn?.network_retry, state.data?.executor, turn ? Math.floor(Date.now() / 1000) : null]);
  if (!box) return;
  if (!turn) {
    box.append(el("div", "inspector-empty", "未开始"));
    return;
  }
  const cursor = turn.execution_cursor || {};
  const lease = turn.driver_lease || null;
  const liveness = turn.liveness || {};
  const executor = state.data?.executor || {};
  inspectorFact(
    box,
    "Executor",
    executor.active
      ? "运行中" + (executor.pid ? " · PID " + executor.pid : "")
      : inspectorStateText(executor.state || "UNKNOWN"),
  );
  if (executor.heartbeat_age_seconds != null)
    inspectorFact(
      box,
      "Executor 心跳",
      inspectorNumber(Math.round(executor.heartbeat_age_seconds), " 秒前"),
    );
  inspectorFact(box, "Phase", cursor.phase || "—");
  inspectorFact(
    box,
    "Cursor",
    "步骤 " + inspectorNumber(cursor.step) +
      " · checkpoint " + inspectorNumber(cursor.checkpoint_step),
  );
  inspectorFact(box, "Recovery", inspectorStateText(cursor.recovery_state));
  const retry = turn.network_retry;
  if (retry) {
    inspectorFact(box, "Connection", (turn.status === "PAUSED" ? "已暂停重连" : "等待重连") + " · 第 " + inspectorNumber(retry.failures) + " 次失败");
    inspectorFact(box, "Next check", typeof retry.retry_at === "number"
      ? inspectorNumber(Math.max(0, Math.ceil(retry.retry_at - Date.now() / 1000)), " 秒后") : "N/A");
    inspectorFact(box, "Retry interval", inspectorNumber(retry.delay_seconds, " 秒") + " · 上限 60 秒");
  }
  if (liveness.seconds_since_progress != null)
    inspectorFact(
      box,
      "Last progress",
      inspectorNumber(Math.round(liveness.seconds_since_progress), " 秒前"),
    );
  if (liveness.suspected_no_progress)
    inspectorFact(
      box,
      "Progress watch",
      "疑似无进展，请先检查再重试",
    );
  if (cursor.detail)
    inspectorFact(box, "Detail", String(cursor.detail).slice(0, 180));
  if (lease) {
    const remaining = typeof lease.lease_until === "number"
      ? Math.max(0, Math.ceil(lease.lease_until - Date.now() / 1000)) : null;
    inspectorFact(
      box,
      "Driver",
      lease.expired ? "租约已过期" : turn.driver_active ? "运行中" : "已脱离",
    );
    inspectorFact(
      box,
      "Lease",
      lease.expired ? "已过期" : inspectorNumber(remaining, " 秒后到期"),
    );
    // Driver 心跳取自自己的租约时间；Executor 存活和 durable progress 不能替代它。
    inspectorFact(box, "Driver 心跳", typeof lease.heartbeat_at === "number"
      ? inspectorNumber(Math.max(0, Math.round(Date.now() / 1000 - lease.heartbeat_at)), " 秒前") : "N/A");
    inspectorFact(box, "Generation", lease.generation ?? "—");
  } else {
    inspectorFact(box, "Driver", turn.driver_active ? "运行中" : "未连接");
  }
}

// 展示跨 Provider 的共同模型事实；特有元数据只在用户展开时按需读取完整 Evidence。
function renderInspectorModel(turn) {
  const evidence = turn?.provider_evidence || {};
  const box = inspectorRegion("inspectorModel", [turn?.run_id, turn?.settings, evidence]);
  const details = $("providerEvidenceDetails");
  const body = $("providerEvidenceBody");
  if (!box || !details || !body) return;
  // 新调用或新会话才清理原始证据；700ms 心跳不能把用户展开的内容收起。
  const sameRun = details.dataset.runId === turn?.run_id;
  const wasOpen = sameRun && details.open;
  details.classList.add("hidden");
  details.open = false;
  details.dataset.runId = "";
  details.dataset.loadedFor = "";
  details.dataset.evidenceKey = JSON.stringify([turn?.run_id, evidence]);
  details.dataset.loadingFor = "";
  // 值身份可能出现 A→B→A；递增代数使旧 A 请求永远不再拥有新 A 的节点。
  details._evidenceGeneration = (details._evidenceGeneration || 0) + 1;
  body.replaceChildren(el("div", "inspector-empty", "展开后读取完整脱敏元数据"));
  if (!turn) {
    box.append(el("div", "inspector-empty", "暂无模型证据"));
    return;
  }
  inspectorFact(box, "Provider", evidence.provider_name || evidence.provider || turn.settings?.provider || "N/A");
  inspectorFact(box, "Model", evidence.model || turn.settings?.model || "N/A");
  inspectorFact(box, "Response", evidence.response_id || "N/A · 供应商未报告");
  inspectorFact(box, "Status", evidence.status ? inspectorStateText(evidence.status) : "N/A");
  inspectorFact(
    box,
    "Reasoning",
    evidence.reasoning_tokens == null
      ? "N/A · 供应商未报告"
      : inspectorNumber(evidence.reasoning_tokens),
  );
  const hasProviderDetail =
    evidence.created_at != null ||
    evidence.incomplete_details != null ||
    (evidence.output_types || []).length ||
    (evidence.extra_keys || []).length ||
    evidence.reasoning_summary?.length;
  if (!hasProviderDetail) return;
  details.classList.remove("hidden");
  details.dataset.runId = turn.run_id;
  const preview = el("div", "provider-evidence-preview");
  if (evidence.created_at != null)
    inspectorFact(preview, "Created", String(evidence.created_at));
  if (evidence.output_types?.length)
    inspectorFact(preview, "Output types", evidence.output_types.join(", "));
  if (evidence.incomplete_details != null)
    inspectorFact(
      preview,
      "Incomplete",
      typeof evidence.incomplete_details === "string"
        ? evidence.incomplete_details
        : JSON.stringify(evidence.incomplete_details),
    );
  if (evidence.reasoning_summary?.length)
    inspectorFact(
      preview,
      "Reasoning summary",
      String(evidence.reasoning_summary.at(-1)).slice(0, 280),
    );
  if (evidence.extra_keys?.length)
    inspectorFact(preview, "Provider-only fields", evidence.extra_keys.join(", "));
  body.replaceChildren(preview);
  details.open = wasOpen;
  if (wasOpen) loadProviderEvidence(details);
}

// 证据按当前 Run/投影身份去重读取；迟到响应不能覆写另一个会话或下一次模型调用。
async function loadProviderEvidence(details) {
  const evidenceKey = details.dataset.evidenceKey;
  if (!details.open || details.dataset.loadedFor === evidenceKey || details.dataset.loadingFor === evidenceKey) return;
  const runId = details.dataset.runId;
  if (!runId) return;
  const generation = details._evidenceGeneration;
  details.dataset.loadingFor = evidenceKey;
  const body = $("providerEvidenceBody");
  const current = () => details._evidenceGeneration === generation && details.dataset.evidenceKey === evidenceKey &&
    details.dataset.runId === runId && $("providerEvidenceBody") === body;
  const loading = el("div", "inspector-empty", "正在读取 Provider Evidence…");
  body.append(loading);
  try {
    const value = await api(`/turns/${encodeURIComponent(runId)}/provider-evidence`);
    if (!current()) return;
    loading.remove();
    const raw = document.createElement("details");
    raw.className = "provider-evidence-raw";
    const summary = document.createElement("summary");
    summary.textContent = "完整 Provider Evidence";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(value.evidence || {}, null, 2);
    raw.append(summary, pre);
    body.append(raw);
    details.dataset.loadedFor = evidenceKey;
  } catch (e) {
    if (!current()) return;
    loading.remove();
    body.append(el("div", "inspector-empty", e.message));
  } finally {
    if (current() && details.dataset.loadingFor === evidenceKey) details.dataset.loadingFor = "";
  }
}
$("providerEvidenceDetails")?.addEventListener("toggle", (event) => loadProviderEvidence(event.currentTarget));

// 展示供应商实际报告的输入/输出/缓存计量；未报告缓存保留 N/A。
function renderInspectorTokens(turn) {
  const box = inspectorRegion("inspectorTokens", [!!turn, turn?.settings?.num_ctx, turn?.budgets, turn?.model_usage]);
  if (!box) return;
  if (!turn) {
    box.append(el("div", "inspector-empty", "未记录用量"));
    return;
  }
  const byMeter = Object.fromEntries(
    (turn.budgets || []).map((row) => [row.meter, row]),
  );
  const input = byMeter.input_tokens || {},
    output = byMeter.output_tokens || {},
    calls = byMeter.model_calls || {};
  inspectorFact(
    box,
    "Context window",
    turn.settings?.num_ctx != null
      ? inspectorNumber(turn.settings.num_ctx, " tokens")
      : "供应商管理",
  );
  inspectorFact(
    box,
    "Input settled",
    inspectorNumber(input.settled),
  );
  inspectorFact(
    box,
    "Output settled",
    inspectorNumber(output.settled),
  );
  const modelUsage = turn.model_usage || {};
  if (modelUsage.cache_metrics_available) {
    const inputTotal = modelUsage.input_tokens;
    const cached = modelUsage.cached_input_tokens;
    const rate =
      typeof modelUsage.cache_hit_rate !== "number" || !Number.isFinite(modelUsage.cache_hit_rate)
        ? "N/A"
        : (Number(modelUsage.cache_hit_rate) * 100).toFixed(1) + "%";
    inspectorFact(
      box,
      "Cache hit",
      rate +
        " · " +
        inspectorNumber(cached) +
        " / " +
        inspectorNumber(inputTotal),
    );
  } else {
    // provider not reported：没有供应商计量时，不能按零命中解释。
    inspectorFact(box, "Cache hit", "N/A · 供应商未报告");
  }
  if (modelUsage.provider_wall_available) {
    // runtime measured：服务端实测墙钟毫秒，不是浏览器从心跳估算。
    inspectorFact(
      box,
      "Model wall",
      statisticsDuration(modelUsage.provider_wall_ms) + " · 实测",
    );
  } else {
    inspectorFact(box, "Model wall", "N/A");
  }
  inspectorFact(box, "First token", modelUsage.first_token_ms == null
    ? "N/A · 供应商未报告"
    : inspectorNumber(modelUsage.first_token_ms, " ms") + " · 首个非空增量");
  inspectorFact(
    box,
    "Model calls",
    inspectorNumber(calls.settled) + " / " + inspectorNumber(calls.limit_units),
  );
  if (Number(input.unknown_held || 0) || Number(output.unknown_held || 0))
    inspectorFact(
      box,
      "Unknown held",
      inspectorNumber(input.unknown_held) + " 输入 · " +
        inspectorNumber(output.unknown_held) + " 输出",
    );
}

// 按持久 sequence 展示轨迹；折叠展示不删除历史事件。
function renderInspectorTrajectory(turn) {
  const box = inspectorRegion("inspectorTrajectory", turn?.events || []);
  if (!box) return;
  const events = (turn?.events || []).slice(-14);
  if (!events.length) {
    box.append(el("div", "inspector-empty", "未记录事件"));
    return;
  }
  events.forEach((event) => {
    const row = el("div", "trajectory-row");
    row.append(
      el("span", "trajectory-seq", "#" + event.sequence),
      el("strong", "", event.kind),
    );
    const payload = event.payload || {};
    const detail =
      payload.capability ||
      payload.status ||
      payload.intent_route ||
      payload.model_attempt_id ||
      payload.reason ||
      "";
    if (detail) row.append(el("small", "", String(detail).slice(0, 120)));
    box.append(row);
  });
}

// 显示固定工具参数/结果/机会状态；页面不直接启动工具。
function renderInspectorTools(turn) {
  const box = inspectorRegion("inspectorTools", turn?.operations || []);
  if (!box) return;
  const ops = turn?.operations || [];
  if (!ops.length) {
    box.append(el("div", "inspector-empty", "未调用工具"));
    return;
  }
  ops.slice(-8).forEach((op) => {
    const row = el("div", "observatory-tool");
    const head = el("div", "observatory-tool-head");
    head.append(
      el("strong", "", op.capability || "tool"),
      el("span", "", inspectorStateText(op.state)),
    );
    row.append(head);
    const identity = op.ticket_id || op.decision_id;
    if (identity) row.append(el("small", "", identity));
    if (op.result?.artifact?.name)
      row.append(el("small", "", "Artifact · " + op.result.artifact.name));
    else if (op.result?.error) row.append(el("small", "", op.result.error));
    box.append(row);
  });
}

// 展示 durable committed/reserved/unknown 各资源；未知占用不作为可用余额。
function renderInspectorBudgets(turn) {
  const box = inspectorRegion("inspectorBudgets", turn?.budgets || []);
  if (!box) return;
  const rows = turn?.budgets || [];
  if (!rows.length) {
    box.append(el("div", "inspector-empty", "未分配预算"));
    return;
  }
  rows.forEach((row) => {
    const wrap = el("div", "budget-row"),
      head = el("div", "budget-head");
    const meters = {
      input_tokens: "输入 Tokens", output_tokens: "输出 Tokens", model_calls: "模型调用",
      tool_calls: "工具调用", tool_bytes: "工具字节", wall_ms: "运行毫秒",
    };
    head.append(
      el("strong", "", meters[row.meter] || row.meter),
      el("span", "", inspectorNumber(row.settled) + " / " + inspectorNumber(row.limit_units)),
    );
    wrap.append(head);
    // 只有真实正上限才绘制比例；已结算、预留与 UNKNOWN 分段，未知负债始终保留。
    if (typeof row.limit_units === "number" && Number.isFinite(row.limit_units) && row.limit_units > 0) {
      const track = el("div", "budget-track");
      track.setAttribute("aria-hidden", "true");
      let available = 100;
      for (const [field, className] of [["settled", "budget-used"], ["reserved", "budget-reserved"], ["unknown_held", "budget-unknown"]]) {
        const units = row[field];
        if (typeof units !== "number" || !Number.isFinite(units) || units <= 0) continue;
        const segment = el("div", className);
        const width = Math.min(available, (units / row.limit_units) * 100);
        segment.style.width = width + "%";
        available -= width;
        track.append(segment);
      }
      wrap.append(track);
    }
    wrap.append(el("small", "budget-note", "预留 " + inspectorNumber(row.reserved) +
      " · UNKNOWN " + inspectorNumber(row.unknown_held)));
    box.append(wrap);
  });
}

// 显示已保存控制修订和安全点状态；Stop/Pause 不代表在途调用被撤销。
function renderInspectorControl(turn) {
  const box = inspectorRegion("inspectorControl", [!!turn, turn?.control, turn?.settings]);
  if (!box) return;
  if (!turn) {
    box.append(el("div", "inspector-empty", "未开始"));
    return;
  }
  const control = turn.control || {};
  [
    ["修订", control.revision ?? "—"],
    [
      "状态",
      (control.stopped ?? control.aborted)
        ? "已停止"
        : control.paused
          ? "已暂停"
          : control.paused === false || control.stopped === false || control.aborted === false
            ? "允许继续" : "未报告",
    ],
    ["模型", control.model || turn.settings?.model || "—"],
    [
      "思考",
      control.thinking === true
        ? "已开启"
        : control.thinking === false
          ? "已关闭"
          : control.thinking || "默认",
    ],
    ["引导", control.steering_note || "—"],
  ].forEach(([k, v]) => {
    inspectorFact(box, k, v);
  });
}

// 展示本次请求 selected/folded/dropped 与字节预算；原始历史和真实 Token 另存。
function renderInspectorContext(session, turn) {
  const box = inspectorRegion("inspectorContext", [session?.id, session?.project_name, session?.messages?.length, turn?.snapshot, turn?.events, turn?.current_step, turn?.max_steps]);
  if (!box) return;
  if (!session && !turn) {
    box.append(el("div", "inspector-empty", "未载入上下文"));
    return;
  }
  const snapshot = turn?.snapshot || {},
    project = snapshot.project || null;
  [
    ["项目", project?.name || session?.project_name || "独立会话"],
    [
      "历史消息",
      (snapshot.messages?.length ?? session?.messages?.length ?? 0) +
        " 条",
    ],
    ["知识来源", (snapshot.knowledge?.length ?? 0) + " 个"],
    ["记忆", (snapshot.memory?.length ?? 0) + " 条"],
    ["事件", (turn?.events?.length ?? 0) + " 条"],
    [
      "步骤",
      turn ? inspectorNumber(turn.current_step) + " / " + inspectorNumber(turn.max_steps) : "—",
    ],
  ].forEach(([k, v]) => {
    inspectorFact(box, k, v);
  });
  const compiled = (turn?.events || [])
    .filter((event) => event.kind === "ConversationContextCompiled")
    .at(-1)?.payload;
  if (compiled) {
    const pct = typeof compiled.bytes_used === "number" && compiled.max_bytes > 0
      ? Math.round((compiled.bytes_used / compiled.max_bytes) * 100) + "%" : "N/A";
    [
      [
        "模型上下文",
        inspectorNumber(compiled.bytes_used) +
          " / " +
          inspectorNumber(compiled.max_bytes) +
          " bytes · " +
          pct,
      ],
      [
        "Token window",
        compiled.num_ctx != null ? inspectorNumber(compiled.num_ctx, " tokens") : "供应商管理",
      ],
      ["实际选入", (compiled.selected?.length || 0) + " 项"],
      ["旧记录折叠", (compiled.folded?.length || 0) + " 项"],
      ["未选入", (compiled.dropped?.length || 0) + " 项"],
      [
        "Context Anchor",
        compiled.context_anchor
          ? inspectorNumber(compiled.context_anchor.covered_messages) +
            " 条 · " + inspectorNumber(compiled.context_anchor.bytes, " bytes")
          : "未使用",
      ],
      [
        "Tool visibility",
        inspectorNumber(compiled.visible_tools?.length) +
          " visible · " + inspectorNumber(compiled.deferred_tools?.length) + " deferred",
      ],
    ].forEach(([k, v]) => {
      inspectorFact(box, k, v);
    });
    const contextDecision = compiled.context_decision;
    if (contextDecision) {
      inspectorFact(
        box,
        "Context mode",
        (contextDecision.mode || "normal") + " · " +
          (contextDecision.outcome || "UNKNOWN") + " · " +
          (contextDecision.reason_code || "unspecified") +
          (contextDecision.provider_visible_saving_bytes == null
            ? ""
            : " · save " +
              inspectorNumber(contextDecision.provider_visible_saving_bytes, " bytes/request")),
      );
    }
    const reachability = compiled.capability_reachability || [];
    if (reachability.length) {
      inspectorFact(
        box,
        "Capability reachability",
        reachability
          .map(item => (item.capability_id || "capability") + "=" +
            (item.reachable ? "reachable" : (item.reason_code || "unreachable")))
          .join(" / "),
      );
    }
    if (compiled.compaction_seed) {
      inspectorFact(
        box,
        "Compact seed",
        (compiled.compaction_seed.selected ? "selected" : "not selected") +
          " · " + inspectorNumber(compiled.compaction_seed.observations) +
          " evidence items · " +
          inspectorNumber(compiled.compaction_seed.semantic_boundaries) +
          " semantic boundaries",
      );
    }
  }
  // 实时信息控制只展示 durable activity 派生事实；KEEP 表示当前没有继续取信息，不伪造“增益分数”。
  const info = turn?.information_control;
  if (info) {
    inspectorFact(
      box,
      "Information Control",
      (info.last_action || "KEEP") + " · " +
        inspectorNumber(info.actions) + " / " + inspectorNumber(info.total_limit),
    );
    inspectorFact(
      box,
      "SEEK / EXPAND",
      inspectorNumber(info.seek) + " / " + inspectorNumber(info.seek_limit) +
        " · " + inspectorNumber(info.expand) + " / " + inspectorNumber(info.expand_limit),
    );
    inspectorFact(box, "信息拒绝", inspectorNumber(info.denied));
    inspectorFact(box, "信息返回量", inspectorNumber(info.result_bytes, " bytes"));
  }
}

// 投影当前组合能力及固定策略；成熟度与可执行路径分开。
function renderInspectorPlatform() {
  const box = inspectorRegion("inspectorPlatform", state.data?.platform || {});
  if (!box) return;
  const counts = {
    hardened: 0,
    usable: 0,
    connected: 0,
    exists: 0,
    planned: 0,
  };
  const platform = state.data?.platform || {};
  [
    ...(platform.core || []),
    ...(platform.domains || []),
    ...(platform.strategies || []),
    ...(platform.adapters || []),
  ].forEach((item) => {
    const maturity = item.maturity || item.state;
    if (counts[maturity] !== undefined) counts[maturity]++;
  });
  const maturityLabels = {hardened: "已强化", usable: "可用", connected: "已连接", exists: "已实现", planned: "规划中"};
  ["hardened", "usable", "connected", "exists", "planned"].forEach((key) => {
    const row = el("div", "context-fact platform-fact " + key);
    row.append(el("span", "", maturityLabels[key]), el("span", "context-value", counts[key]));
    box.append(row);
  });
}

// 统一刷新第三栏所有观测区域；空会话保留结构和事实入口。
function renderRuntimeInspector(session = state.session) {
  const turn = session?.turns?.at(-1) || null,
    [label, cls] = inspectorStatus(turn?.status || "IDLE");
  if ($("inspectorState")) $("inspectorState").textContent = turn ? "Turn " + label : label;
  const acceptance = $("inspectorAcceptance");
  if (acceptance) {
    acceptance.classList.toggle("hidden", !turn);
    acceptance.textContent = turn ? "验收 · " + (turn.delivery?.acceptance?.state ? inspectorStateText(turn.delivery.acceptance.state) : "未报告") : "";
  }
  if ($("inspectorPulse"))
    $("inspectorPulse").className = "inspector-pulse " + cls;
  renderSessionStatistics(session);
  renderInspectorGoal(turn);
  renderInspectorDelivery(turn);
  renderInspectorSotaRoute(turn);
  renderExecutionSpine(turn);
  renderExecutionGraph(turn);
  renderInspectorRecovery(turn);
  renderInspectorTrajectory(turn);
  renderInspectorTokens(turn);
  renderInspectorModel(turn);
  renderInspectorContext(session, turn);
  renderInspectorTools(turn);
  renderInspectorControl(turn);
  renderInspectorBudgets(turn);
  renderInspectorPlatform();
}

// 同步导航 aria-current；支持辅助技术定位当前页面。
function syncNavCurrent() {
  document.querySelectorAll("[data-page]").forEach((link) => {
    if (link.classList.contains("active"))
      link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

// 窄屏观测抽屉只管理本地可访问性；关闭或越过断点必须释放背景 inert 与焦点。
function bindInspectorDrawer() {
  const panel = $("runtimeInspector"), toggle = $("inspectorToggle"), close = $("inspectorClose");
  if (!panel || !toggle || !close || typeof window.matchMedia !== "function") return;
  const compact = window.matchMedia("(max-width: 1120px)");
  const shade = el("button", "inspector-shade");
  shade.type = "button";
  shade.hidden = true;
  shade.tabIndex = -1;
  shade.setAttribute("aria-label", "关闭运行详情");
  panel.parentElement.insertBefore(shade, panel);
  let previousFocus = null;
  const background = new Map();

  // 只记录本抽屉改变的 inert 状态，恢复时不擅自解除其他界面已有的禁用。
  const blockBackground = () => {
    for (const node of document.querySelectorAll("body > *, .shell > *")) {
      if (node === panel || node === shade || node.contains(panel) || node.tagName === "SCRIPT") continue;
      background.set(node, node.inert);
      node.inert = true;
    }
  };
  const releaseBackground = () => {
    // 抽屉展开期间可能越过导航断点，关闭时按当前布局释放导航。
    background.forEach((inert, node) => {
      node.inert = node.id === "sidebar" ? window.matchMedia("(max-width: 800px)").matches : inert;
    });
    background.clear();
  };
  const focusable = () => [...panel.querySelectorAll("a[href], button, input, select, textarea, summary, [tabindex]")]
    .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length > 0);

  // 桌面常驻栏无模态语义；窄屏打开时才成为对话框并固定键盘焦点。
  const setOpen = (requested, restoreFocus = true) => {
    const open = compact.matches && requested;
    const wasOpen = panel.classList.contains("open");
    panel.classList.toggle("open", open);
    shade.hidden = !open;
    document.body.classList.toggle("inspector-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    panel.inert = compact.matches && !open;
    if (open) {
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-modal", "true");
      if (!wasOpen) {
        previousFocus = document.activeElement;
        blockBackground();
        // 下一帧可见性规则生效后交接焦点，避免平板从隐藏面板 focus 到 BODY。
        requestAnimationFrame(() => { if (panel.classList.contains("open")) close.focus(); });
      }
    } else {
      panel.removeAttribute("role");
      panel.removeAttribute("aria-modal");
      releaseBackground();
      if (wasOpen && restoreFocus) {
        const target = previousFocus?.isConnected ? previousFocus : toggle;
        if (!target.inert && target.getClientRects().length) target.focus();
        else $("mainContent")?.focus();
      }
    }
  };
  toggle.onclick = () => setOpen(!panel.classList.contains("open"));
  // 异步资料预览可能晚于抽屉打开；原生 dialog 接管前统一释放 inert 和捕获键盘的状态。
  state.closeRuntimeDrawer = () => setOpen(false);
  close.onclick = () => setOpen(false);
  shade.onclick = () => setOpen(false);
  document.addEventListener("keydown", event => {
    if (!panel.classList.contains("open")) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
      setOpen(false);
    } else if (event.key === "Tab") {
      const targets = focusable(), first = targets[0], last = targets.at(-1);
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    }
  }, true);
  // 跳往完整 Runtime 时交还页面导航；断点切换时去掉所有暂存的模态状态。
  window.addEventListener("hashchange", () => setOpen(false));
  compact.addEventListener("change", () => setOpen(false));
  setOpen(false, false);
}

bindInspectorDrawer();
window.addEventListener("hashchange", () =>
  setTimeout(() => {
    syncNavCurrent();
    renderRuntimeInspector();
  }, 0),
);
setInterval(() => {
  syncNavCurrent();
  renderRuntimeInspector();
}, 700);
setTimeout(() => {
  syncNavCurrent();
  renderRuntimeInspector();
}, 0);
