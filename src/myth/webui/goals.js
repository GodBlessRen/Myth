// 长期 Goal 与显式一次性/间隔计划的浏览器入口。
// 计划请求身份在一次表单生命周期中固定；后端负责原子 admission，页面刷新不重复发出工作。
"use strict";

// 当前表单绑定的 Goal；关闭/重开时显式更换。
let schedulingGoal = null;
// 一次计划表单的稳定请求身份；失败重试沿用，成功后才清除。
let scheduleRequestId = null;
// Goal 页面读取代数；迟到响应不能覆盖新页面。
let goalRefreshGeneration = 0;

// 重置明确创建长期意图的表单；显示表单不会创建 Goal。
function openGoalForm() {
  $("goalTitleInput").value = "";
  $("goalDescriptionInput").value = "";
  $("goalDialog").showModal();
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
  $("schedulerStatus").textContent = scheduler.running
    ? "定时唤醒服务运行中 · 每 2 秒检查到期计划"
    : "定时唤醒服务未运行，请启动 Myth Web 服务。";
  if (scheduler.last_error)
    $("schedulerStatus").textContent += " · " + scheduler.last_error;
  const cards = $("goalCards");
  cards.replaceChildren();
  if (!goalData.goals.length) {
    empty(
      cards,
      "保存一个长期目标",
      "让每次工作从上一次进度接着开始。",
      "spark",
      openGoalForm,
      "新建目标",
    );
    return;
  }
  for (const goal of goalData.goals) {
    const card = el("article", "panel goal-card"),
      work = goal.work || {};
    card.append(
      el("h2", "", goal.title),
      el("p", "muted", goal.description),
      el("p", "", `状态：${goal.state} · ${work.current_state || "READY"}`),
    );
    if (work.progress_note) card.append(el("p", "", work.progress_note));
    if (work.next_action)
      card.append(el("p", "muted", "下一步：" + work.next_action));
    if (work.waiting_for)
      card.append(el("p", "schedule-error", "等待：" + work.waiting_for));
    const actions = el("div", "button-row");
    const continueWork = el("button", "secondary", "继续工作");
    continueWork.onclick = async () => {
      try {
        const runs = await api(
          `/goals/${encodeURIComponent(goal.goal_id)}/runs`,
        );
        const latest = runs.runs?.at(-1);
        if (latest?.session_id) {
          go("chat", latest.session_id);
        } else {
          await newChat();
          fillGoals($("chatGoal"), goal.goal_id);
        }
      } catch (e) {
        toast(e.message);
      }
    };
    const schedule = el("button", "primary", "安排工作");
    schedule.disabled = goal.state !== "ACTIVE";
    schedule.onclick = () => openSchedule(goal);
    const pause = el(
      "button",
      "secondary",
      goal.state === "PAUSED" ? "恢复目标" : "暂停目标",
    );
    pause.disabled = !["ACTIVE", "PAUSED"].includes(goal.state);
    pause.onclick = async () => {
      try {
        await api(`/goals/${encodeURIComponent(goal.goal_id)}/state`, {
          state: goal.state === "PAUSED" ? "ACTIVE" : "PAUSED",
        });
        await renderGoals();
        toast("已更新目标状态；当前轮次在对话中管理。");
      } catch (e) {
        toast(e.message);
      }
    };
    actions.append(continueWork, schedule, pause);
    card.append(actions);
    for (const item of scheduleData.schedules.filter(
      (s) => s.goal_id === goal.goal_id,
    )) {
      const row = el("div", "schedule-row"),
        info = el("div");
      info.append(
        el("strong", "", item.enabled ? "已启用" : "已暂停 / 已结束"),
        el("p", "", item.prompt),
        el(
          "small",
          "",
          new Date(item.due_at).toLocaleString() +
            (item.interval_seconds
              ? ` · 每 ${item.interval_seconds / 60} 分钟`
              : " · 仅一次"),
        ),
        el("small", "", `${item.settings.provider} · ${item.settings.model}`),
      );
      if (item.last_error)
        info.append(el("p", "schedule-error", item.last_error));
      const wake = item.wakeups[0];
      if (wake) info.append(el("small", "", "最近执行：" + wake.status));
      const buttons = el("div", "button-row"),
        open = el("button", "secondary", "打开会话"),
        toggle = el(
          "button",
          "secondary",
          item.enabled ? "暂停计划" : "启用计划",
        );
      open.onclick = () => go("chat", item.session_id);
      toggle.disabled =
        !item.enabled && !item.interval_seconds && item.wakeups.length > 0;
      toggle.onclick = async () => {
        try {
          await api(
            `/schedules/${encodeURIComponent(item.schedule_id)}/enabled`,
            { enabled: !item.enabled },
          );
          await renderGoals();
        } catch (e) {
          toast(e.message);
        }
      };
      buttons.append(open, toggle);
      row.append(info, buttons);
      card.append(row);
    }
    cards.append(card);
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
    $("schedulePrompt").value = goal.work?.next_action || "";
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
    $("scheduleDialog").showModal();
  } catch (e) {
    toast(e.message);
  }
}

$("createGoal").onclick = openGoalForm;
$("inspectorToggle").onclick = () => {
  const panel = $("runtimeInspector");
  const open = panel.classList.toggle("open");
  $("inspectorToggle").setAttribute("aria-expanded", String(open));
};
$("inspectorClose").onclick = () => {
  $("runtimeInspector").classList.remove("open");
  $("inspectorToggle").setAttribute("aria-expanded", "false");
  $("inspectorToggle").focus();
};
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
