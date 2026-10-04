// 长期 Goal 与显式一次性/间隔计划的浏览器入口。
// 计划请求身份在一次表单生命周期中固定；后端负责原子 admission，页面刷新不重复发出工作。
"use strict";

// 当前表单绑定的 Goal；关闭/重开时显式更换。
let schedulingGoal = null;
// 一次计划表单的稳定请求身份；失败重试沿用，成功后才清除。
let scheduleRequestId = null;
// Goal 页面读取代数；迟到响应不能覆盖新页面。
let goalRefreshGeneration = 0;
// 卡片展示事实的签名；只读轮询与 scheduler 心跳不销毁焦点或 details 阅读位置。
let goalRenderSignature = "";

// 重置明确创建长期意图的表单；显示表单不会创建 Goal。
function openGoalForm() {
  $("goalTitleInput").value = "";
  $("goalDescriptionInput").value = "";
  openDialog("goalDialog", "goalTitleInput");
}

// 目标列表的折叠偏好只存在当前页面；不会写入 Goal、计划或执行状态。
const goalDetailOpen = new Map();

// 以原生 details 提供键盘展开；重绘时沿用同一目标的本地阅读状态。
function goalDisclosure(key, title, className) {
  const details = el("details", className);
  details.open = goalDetailOpen.get(key) ?? false;
  const summary = el("summary", "", title);
  details.append(summary);
  details.addEventListener("toggle", () => goalDetailOpen.set(key, details.open));
  return details;
}

// 目标进度来自持久工作记录；空字段不制造进度或重复空态。
function goalFact(box, label, value, className = "") {
  if (value == null || value === "") return;
  const row = el("div", "goal-fact " + className);
  row.append(el("dt", "", label), el("dd", "", value));
  box.append(row);
}

// 计划时间使用浏览器本地时区；无效日期保持未报告，不展示 Invalid Date。
function goalScheduleTime(value) {
  const date = value == null ? null : new Date(value);
  return date && Number.isFinite(date.getTime())
    ? date.toLocaleString("zh-CN", {month: "long", day: "numeric", hour: "2-digit", minute: "2-digit"})
    : "时间未报告";
}

// 并行读取 Goal/计划并核对 refresh generation；进度、拒绝原因和下一机会分开展示。
async function renderGoals() {
  const generation = ++goalRefreshGeneration;
  const [goalData, scheduleData] = await Promise.all([
    api("/goals"),
    api("/schedules"),
  ]);
  if (state.page !== "goals" || generation !== goalRefreshGeneration) return;
  state.data.goals = goalData.goals;
  const scheduler = scheduleData.scheduler || {};
  $("schedulerStatus").textContent = scheduler.running ? "定时唤醒已运行" : "定时唤醒未运行";
  $("schedulerStatus").title = scheduler.running
    ? "服务每 2 秒检查到期计划；目标与当前 Run 独立管理。"
    : "请启动 Myth 服务后重试。";
  if (scheduler.last_error) $("schedulerStatus").textContent += " · " + scheduler.last_error;
  const cards = $("goalCards");
  const signature = JSON.stringify([goalData.goals, scheduleData.schedules]);
  if (signature === goalRenderSignature) return;
  goalRenderSignature = signature;
  const focusGoal = document.activeElement?.dataset?.goalId;
  const focusAction = document.activeElement?.dataset?.goalAction;
  cards.replaceChildren();
  if (!goalData.goals.length) {
    empty(cards, "还没有长期目标", "保存目标后，可以跨会话继续推进。", "spark", openGoalForm, "新建目标");
    return;
  }
  for (const goal of goalData.goals) {
    const card = el("article", "goal-list-item"), work = goal.work || {};
    const head = el("div", "goal-item-head"), identity = el("div", "goal-item-title");
    const status = el("span", "goal-item-state", inspectorStateText(goal.state));
    status.dataset.state = goal.state;
    identity.append(el("h2", "", goal.title));
    const next = work.next_action === "Start or continue the next admitted work item." ? "" : inspectorWorkText(work.next_action);
    const progressNote = work.progress_note === "Goal created." ? "" : inspectorWorkText(work.progress_note);
    const preview = next || progressNote || goal.description;
    if (preview) identity.append(el("p", "goal-item-preview", preview));
    head.append(identity, status);
    card.append(head);

    const actions = el("div", "button-row goal-item-actions");
    const continueWork = el("button", "primary", "继续工作");
    continueWork.onclick = async () => {
      continueWork.disabled = true;
      try {
        const runs = await api(`/goals/${encodeURIComponent(goal.goal_id)}/runs`);
        const latest = runs.runs?.at(-1);
        if (latest?.session_id) {
          go("chat", latest.session_id);
        } else {
          await newChat();
          fillGoals($("chatGoal"), goal.goal_id);
        }
      } catch (e) {
        toast(e.message);
      } finally {
        continueWork.disabled = false;
      }
    };
    const schedule = el("button", "secondary", "安排工作");
    schedule.disabled = goal.state !== "ACTIVE";
    schedule.onclick = async () => {
      schedule.disabled = true;
      try { await openSchedule(goal); }
      finally { schedule.disabled = goal.state !== "ACTIVE"; }
    };
    const pause = el("button", "secondary", goal.state === "PAUSED" ? "恢复目标" : "暂停目标");
    pause.disabled = !["ACTIVE", "PAUSED"].includes(goal.state);
    pause.onclick = async () => {
      pause.disabled = true;
      try {
        await api(`/goals/${encodeURIComponent(goal.goal_id)}/state`, {
          state: goal.state === "PAUSED" ? "ACTIVE" : "PAUSED",
        });
        await renderGoals();
        toast("目标状态已更新");
      } catch (e) {
        toast(e.message);
        pause.disabled = false;
      }
    };
    // 真正状态变化需要重建时，用 Goal/动作身份恢复焦点，不沿用被删除的旧按钮。
    for (const [button, action] of [[continueWork, "continue"], [schedule, "schedule"], [pause, "pause"]]) {
      button.dataset.goalId = goal.goal_id;
      button.dataset.goalAction = action;
    }
    actions.append(continueWork, schedule, pause);
    card.append(actions);

    const progress = goalDisclosure(goal.goal_id + ":progress", "进度与下一步", "goal-detail");
    const facts = el("dl", "goal-detail-grid");
    goalFact(facts, "目标说明", goal.description);
    goalFact(facts, "工作状态", inspectorStateText(work.current_state || "READY"));
    goalFact(facts, "当前进度", inspectorWorkText(work.progress_note));
    goalFact(facts, "下一步", inspectorWorkText(work.next_action));
    goalFact(facts, "等待事项", inspectorWorkText(work.waiting_for), "schedule-error");
    goalFact(facts, "工作修订", work.revision);
    progress.append(facts);
    card.append(progress);

    const schedules = (scheduleData.schedules || []).filter(item => item.goal_id === goal.goal_id);
    if (schedules.length) {
      const plans = goalDisclosure(goal.goal_id + ":schedules", "工作计划 · " + schedules.length, "goal-schedules");
      for (const item of schedules) {
        const row = el("div", "schedule-row"), info = el("div", "schedule-info");
        const wakeups = item.wakeups || [], wake = wakeups[0];
        const enabled = item.enabled ? "已启用" : !item.interval_seconds && wakeups.length ? "已结束" : "已暂停";
        info.append(el("strong", "", enabled), el("p", "", item.prompt));
        info.append(el("small", "", goalScheduleTime(item.due_at) +
          (item.interval_seconds ? ` · 每 ${item.interval_seconds / 60} 分钟` : " · 仅一次")));
        info.append(el("small", "", [item.settings?.provider, item.settings?.model].filter(Boolean).join(" · ") || "模型未报告"));
        if (item.last_error) info.append(el("p", "schedule-error", item.last_error));
        if (wake) info.append(el("small", "", "最近执行：" + inspectorStateText(wake.status)));
        const buttons = el("div", "button-row"), open = el("button", "secondary", "打开会话");
        const toggle = el("button", "secondary", item.enabled ? "暂停计划" : "启用计划");
        open.onclick = () => go("chat", item.session_id);
        // 一次计划已有机会时不能再次启用；重新安排必须产生新的用户意图。
        const completed = !item.enabled && !item.interval_seconds && wakeups.length > 0;
        toggle.disabled = completed;
        toggle.onclick = async () => {
          toggle.disabled = true;
          try {
            await api(`/schedules/${encodeURIComponent(item.schedule_id)}/enabled`, {enabled: !item.enabled});
            await renderGoals();
          } catch (e) {
            toast(e.message);
            toggle.disabled = completed;
          }
        };
        buttons.append(open, toggle);
        row.append(info, buttons);
        plans.append(row);
      }
      card.append(plans);
    }
    cards.append(card);
  }
  if (focusGoal && focusAction) {
    const target = [...cards.querySelectorAll("[data-goal-action]")]
      .find(node => node.dataset.goalId === focusGoal && node.dataset.goalAction === focusAction);
    if (target && !target.disabled) target.focus();
  }
}

// 固定待计划的 Goal 及新 request_id；datetime-local 显式转带时区 UTC 后提交。
async function openSchedule(goal) {
  schedulingGoal = goal;
  scheduleRequestId = crypto.randomUUID();
  try {
    await refresh();
    let sessions = state.data.sessions || [];
    if (!sessions.length) {
      await api("/sessions", { title: goal.title });
      await refresh();
      sessions = state.data.sessions || [];
    }
    $("scheduleGoalTitle").textContent = goal.title;
    $("scheduleSession").replaceChildren();
    sessions.forEach((session) => {
      const option = el("option", "", session.title);
      option.value = session.id;
      $("scheduleSession").append(option);
    });
    if (state.session) $("scheduleSession").value = state.session.id;
    $("schedulePrompt").value = inspectorWorkText(goal.work?.next_action) || "";
    const start = new Date(Date.now() + 5 * 60 * 1000);
    $("scheduleDue").value = new Date(
      start.getTime() - start.getTimezoneOffset() * 60000,
    )
      .toISOString()
      .slice(0, 16);
    $("scheduleInterval").value = "";
    $("scheduleModel").textContent =
      "本次计划使用：" +
      state.data.settings.provider +
      " · " +
      (state.data.settings.model || "请先选择模型");
    openDialog("scheduleDialog", "schedulePrompt");
  } catch (e) {
    toast(e.message);
  }
}

$("createGoal").onclick = openGoalForm;
// 事件绑定只消费明确用户操作；业务身份、参数和状态仍经服务器校验。
$("scheduleForm").onsubmit = async (event) => {
  event.preventDefault();
  const button = event.submitter;
  if (button) button.disabled = true;
  try {
    const interval = $("scheduleInterval").value;
    await api(
      `/goals/${encodeURIComponent(schedulingGoal.goal_id)}/schedules`,
      {
        session_id: $("scheduleSession").value,
        prompt: $("schedulePrompt").value,
        request_id: scheduleRequestId,
        due_at: new Date($("scheduleDue").value).toISOString(),
        interval_seconds: interval ? Number(interval) : null,
      },
    );
    $("scheduleDialog").close();
    await renderGoals();
    toast("工作计划已保存。");
  } catch (e) {
    toast(e.message);
  } finally {
    if (button) button.disabled = false;
  }
};
