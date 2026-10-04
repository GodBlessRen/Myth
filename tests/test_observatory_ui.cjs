// 以轻量 DOM 运行真实渲染器；验证观测语义和重绘边界，不代表真实供应商或浏览器布局验证。
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// 替身维护节点归属与已注册事件；测试控制 toggle 时机，不模拟浏览器布局或原生事件调度。
class Element {
  constructor(tag = "div", className = "", text = "") {
    this.tagName = tag.toUpperCase();
    this.className = className;
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this._text = String(text);
    this.replacements = 0;
    this.value = "";
    this.open = false;
    this.parentElement = null;
    this.listeners = new Map();
    // className 与 classList 使用同一份状态，避免隐藏证据区的分支被替身吞掉。
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      add: (...names) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(" "); },
      remove: (...names) => { this.className = this.className.split(/\s+/).filter(name => name && !names.includes(name)).join(" "); },
    };
  }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
  set textContent(value) { this.replaceChildren(); this._text = String(value); }
  // 父节点所有权随插入/替换更新，让 loading.remove() 真正影响证据区。
  append(...nodes) {
    for (const node of nodes) {
      node.remove();
      node.parentElement = this;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) {
    for (const child of this.children) child.parentElement = null;
    this.children = [];
    this._text = "";
    this.replacements++;
    this.append(...nodes);
  }
  remove() {
    if (!this.parentElement) return;
    this.parentElement.children = this.parentElement.children.filter(child => child !== this);
    this.parentElement = null;
  }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  // 异步处理器由测试等待；事件仍先同步派发，以便断言请求在途时的重复展开。
  dispatch(type) {
    return Promise.all((this.listeners.get(type) || []).map(listener => listener({type, currentTarget: this, target: this})));
  }
  showModal() { this.open = true; }
  close() { this.open = false; }
}

// 每次建立独立全局，避免签名缓存和表单身份从其他用例泄漏。
function controller(ids = [], state = {data: {}}) {
  const nodes = new Map(ids.map(id => [id, new Element()]));
  // 记录真实页面注册的周期及回调；用例推进刷新，不依赖墙钟等待或重写渲染器。
  const intervals = [];
  const context = vm.createContext({
    console, Date, Number, String, Math, JSON, Map,
    state, $: id => nodes.get(id) || null,
    el: (tag, className, value) => new Element(tag, className, value ?? ""),
    window: {addEventListener() {}},
    document: {querySelectorAll: () => [], createElement: tag => new Element(tag)},
    // 会话统计和原生模态焦点属于其他用例；这里只提供装配依赖，不覆盖观测或提交逻辑。
    renderSessionStatistics() {}, openDialog: id => nodes.get(id).showModal(),
    setTimeout() {}, setInterval(callback, delay) { intervals.push({callback, delay}); },
  });
  const load = name => vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/myth/webui", name), "utf8"), context);
  load("statistics.js");
  load("inspector.js");
  return {context, nodes, load, intervals};
}

// 公共投影故意相同，Run 身份仍须隔离原始证据；响应内容由各用例的 API 替身持有。
function providerEvidenceTurn(runId) {
  return {run_id: runId, settings: {provider: "fixture", model: "fixture-model"},
    provider_evidence: {provider: "fixture", response_id: "summary-response", created_at: 123, extra_keys: ["metadata"]}};
}

// 控制网络完成边界，确定性地重现重复展开和跨 Run 响应乱序；不发送真实请求。
function deferredResponse() {
  let resolve;
  const promise = new Promise(complete => { resolve = complete; });
  return {promise, resolve};
}

// 缺测预算不能用伪造零替代；确实记录了零时必须可区分。
test("fixed workspace guidance is Chinese while free text and goal facts remain unchanged", () => {
  const {context, nodes} = controller(["inspectorGoal", "inspectorDelivery"]);
  const goal = {goal_id: "goal-1", title: "长期任务", work: {current_state: "IN_PROGRESS", progress_note: "Conversation answer persisted; semantic acceptance remains explicit.", next_action: "Start or continue the next admitted work item."}};
  const before = JSON.stringify(goal);
  context.renderInspectorGoal({goal_current: goal});
  assert.match(nodes.get("inspectorGoal").textContent, /回答已保存；仍需明确验收/);
  assert.match(nodes.get("inspectorGoal").textContent, /开始或继续下一项获准工作/);
  assert.equal(JSON.stringify(goal), before);
  context.renderInspectorDelivery({status: "COMPLETED", delivery: {work_items: [{ordinal: 1, status: "DONE", progress_note: goal.work.progress_note}]}});
  assert.match(nodes.get("inspectorDelivery").textContent, /回答已保存；仍需明确验收/);
  assert.equal(context.inspectorWorkText("Keep this user-authored English unchanged."), "Keep this user-authored English unchanged.");
});

// 缺测预算不能用伪造零替代；确实记录了零时必须可区分。
test("token observatory keeps missing, zero and unreported cache distinct", () => {
  const {context, nodes} = controller(["inspectorTokens"]);
  context.renderInspectorTokens({settings: {}, budgets: [], model_usage: {}});
  const box = nodes.get("inspectorTokens");
  assert.match(box.textContent, /输入 TokensN\/A/);
  assert.match(box.textContent, /Cache 命中N\/A · 供应商未报告/);
  context.renderInspectorTokens({budgets: [{meter: "input_tokens", settled: 0}], model_usage: {provider_wall_available: true, provider_wall_ms: 0}});
  assert.match(box.textContent, /输入 Tokens0/);
  assert.match(box.textContent, /输出 TokensN\/A/);
  assert.match(box.textContent, /模型用时0毫秒 · 实测/);
});

// Context 区同时展示实时信息控制事实；只读投影不能凭空造 Information Gain 分数。
test("context observatory shows bounded live information control without fake gain", () => {
  const {context, nodes} = controller(["inspectorContext"]);
  context.renderInspectorContext(
    {id: "session-1", project_name: "Myth", messages: []},
    {
      snapshot: {messages: [], knowledge: [], memory: []},
      events: [],
      current_step: 4,
      max_steps: 12,
      information_control: {
        policy: "bounded-live-v1",
        actions: 3,
        total_limit: 8,
        seek: 1,
        seek_limit: 4,
        expand: 2,
        expand_limit: 6,
        denied: 1,
        last_action: "EXPAND",
        result_bytes: 4096,
      },
    },
  );
  const text = nodes.get("inspectorContext").textContent;
  assert.match(text, /Information ControlEXPAND · 3 \/ 8/);
  assert.match(text, /SEEK \/ EXPAND1 \/ 4 · 2 \/ 6/);
  assert.match(text, /信息拒绝1/);
  assert.match(text, /信息返回量4,096 bytes|信息返回量4096 bytes/);
  assert.doesNotMatch(text, /Information Gain/);
});

// 比例分段只消费已记录的三个账户桶；UNKNOWN 既不消失也不计为可用余额。
test("budget segments retain reserved and UNKNOWN without inventing missing limits", () => {
  const {context, nodes} = controller(["inspectorBudgets"]);
  context.renderInspectorBudgets({budgets: [{meter: "tool_calls", settled: 2, reserved: 3, unknown_held: 4, limit_units: 10}]});
  const row = nodes.get("inspectorBudgets").children[0];
  assert.deepEqual(row.children[1].children.map(segment => [segment.className, segment.style.width]), [
    ["budget-used", "20%"], ["budget-reserved", "30%"], ["budget-unknown", "40%"],
  ]);
  assert.match(row.textContent, /预留 3 · UNKNOWN 4/);
  context.renderInspectorBudgets({budgets: [{meter: "tool_calls", settled: null, reserved: 0, unknown_held: 0, limit_units: null}]});
  const missing = nodes.get("inspectorBudgets").children[0];
  assert.match(missing.textContent, /N\/A \/ N\/A/);
  assert.equal(missing.children.some(node => node.className === "budget-track"), false);
});


// Execution Graph 只展示服务端投影；Sub-Agent 分支保持显式，缺失覆盖不会被 UI 悄悄补全。
test("execution graph renders parent tool and sub-agent branch without inventing coverage", () => {
  const {context, nodes} = controller(["inspectorExecutionGraph"]);
  context.renderExecutionGraph({
    execution_graph: {
      experimental: true,
      nodes: [
        {id: "run:1", kind: "run", label: "Run", detail: "run-1", state: "RUNNING", depth: 0},
        {id: "model:1", kind: "model", label: "Parent model · step 1", detail: "agent.delegate", state: "SETTLED", depth: 0},
        {id: "tool:1", kind: "tool", label: "agent.delegate", detail: "ticket-1", state: "RESOLVED", depth: 1},
        {id: "subagent:1", kind: "subagent", label: "Sub-Agent · isolated_worker", detail: "isolated delegated model call", state: "SETTLED", depth: 2},
      ],
      edges: [
        {source: "run:1", target: "model:1", kind: "next"},
        {source: "model:1", target: "tool:1", kind: "tool"},
        {source: "tool:1", target: "subagent:1", kind: "delegate"},
      ],
      coverage: {model_calls: 3, mapped_model_calls: 2, unmapped_model_calls: 1},
    },
  });
  const box = nodes.get("inspectorExecutionGraph");
  assert.match(box.textContent, /Parent model · step 1/);
  assert.match(box.textContent, /agent\.delegate/);
  assert.match(box.textContent, /Sub-Agent · isolated_worker/);
  assert.match(box.textContent, /投影未覆盖 1 次模型调用/);
  const child = box.children.find(node => node.className.includes("subagent"));
  assert.equal(child.style["--graph-depth"], "2");
});

// 同一观测事实不重建 DOM；下一真实记录到达后才替换该区域。
test("unchanged inspector facts preserve DOM while new facts render", () => {
  const {context, nodes} = controller(["inspectorTools"]);
  const turn = {operations: [{capability: "read_file", state: "UNKNOWN", ticket_id: "ticket-1"}]};
  context.renderInspectorTools(turn);
  const box = nodes.get("inspectorTools"), first = box.children[0];
  context.renderInspectorTools(turn);
  assert.equal(box.children[0], first);
  assert.equal(box.replacements, 1);
  assert.match(box.textContent, /UNKNOWN · 待核对/);
  turn.operations[0].state = "RESOLVED";
  context.renderInspectorTools(turn);
  assert.equal(box.replacements, 2);
  assert.match(box.textContent, /已核定/);
});

// 同一服务端事实在 700ms 刷新后保留两层折叠状态、原始文本及节点身份。
test("700ms inspector refresh preserves open provider evidence and raw DOM", async () => {
  const turn = providerEvidenceTurn("run-1");
  const state = {data: {}, session: {turns: [turn]}};
  const {context, nodes, intervals} = controller(["inspectorModel", "providerEvidenceDetails", "providerEvidenceBody"], state);
  const requests = [];
  const evidence = {response_id: "raw-response", metadata: {note: "保留这段原始证据"}};
  context.api = async url => { requests.push(url); return {evidence}; };
  context.renderInspectorModel(turn);
  const details = nodes.get("providerEvidenceDetails"), body = nodes.get("providerEvidenceBody");
  assert.equal(details.classList.contains("hidden"), false);
  details.open = true;
  await details.dispatch("toggle");
  const raw = body.children.find(node => node.className === "provider-evidence-raw");
  assert.ok(raw, "展开必须实际读取并渲染原始证据");
  const pre = raw.children.find(node => node.tagName === "PRE"), preview = body.children[0];
  raw.open = true;
  const replacements = body.replacements;
  const refresh = intervals.find(timer => timer.delay === 700);
  assert.ok(refresh, "必须使用 inspector.js 注册的 700ms 刷新入口");
  // 每次刷新得到新对象，但事实未变，不能把引用变化误判为新调用。
  for (let tick = 0; tick < 3; tick++) {
    state.session = {turns: [JSON.parse(JSON.stringify(turn))]};
    refresh.callback();
    assert.equal(details.open, true);
    assert.equal(raw.open, true);
    assert.equal(body.children[0], preview);
    assert.equal(body.children.find(node => node.className === "provider-evidence-raw"), raw);
    assert.equal(raw.children.find(node => node.tagName === "PRE"), pre);
    assert.equal(pre.textContent, JSON.stringify(evidence, null, 2));
    assert.equal(body.replacements, replacements);
  }
  assert.deepEqual(requests, ["/turns/run-1/provider-evidence"]);
});

// 同一证据在读取中和读取完成后都只请求一次；关闭再展开也不能追加第二份 raw。
test("repeated provider evidence toggles share pending and loaded requests", async () => {
  const {context, nodes} = controller(["inspectorModel", "providerEvidenceDetails", "providerEvidenceBody"]);
  const response = deferredResponse(), requests = [];
  context.api = url => { requests.push(url); return response.promise; };
  context.renderInspectorModel(providerEvidenceTurn("run-1"));
  const details = nodes.get("providerEvidenceDetails"), body = nodes.get("providerEvidenceBody");
  details.open = true;
  const firstOpen = details.dispatch("toggle");
  const repeatedOpen = details.dispatch("toggle");
  details.open = false;
  const close = details.dispatch("toggle");
  details.open = true;
  const reopen = details.dispatch("toggle");
  assert.equal(requests.length, 1, "在途读取必须按证据身份去重");
  assert.equal(body.children.filter(node => node.textContent === "正在读取 Provider Evidence…").length, 1);
  response.resolve({evidence: {metadata: "single-response"}});
  await Promise.all([firstOpen, repeatedOpen, close, reopen]);
  const raw = body.children.find(node => node.className === "provider-evidence-raw");
  assert.ok(raw);
  assert.equal(body.textContent.includes("正在读取 Provider Evidence…"), false);
  details.open = false;
  await details.dispatch("toggle");
  details.open = true;
  await details.dispatch("toggle");
  await details.dispatch("toggle");
  assert.equal(requests.length, 1, "已载入证据必须复用原始内容");
  assert.deepEqual(body.children.filter(node => node.className === "provider-evidence-raw"), [raw]);
});

// 切换 Run 后旧请求迟到，不得清除新请求的 loading，也不得把旧 raw 挂到新会话。
test("late provider evidence from an old run cannot overwrite the new run", async () => {
  const state = {data: {}, session: {turns: [providerEvidenceTurn("run-old")]}};
  const {context, nodes, intervals} = controller(["inspectorModel", "providerEvidenceDetails", "providerEvidenceBody"], state);
  const oldResponse = deferredResponse(), newResponse = deferredResponse(), requests = [];
  context.api = url => {
    requests.push(url);
    if (url === "/turns/run-old/provider-evidence") return oldResponse.promise;
    if (url === "/turns/run-new/provider-evidence") return newResponse.promise;
    throw new Error("非预期的证据请求：" + url);
  };
  context.renderInspectorModel(state.session.turns[0]);
  const details = nodes.get("providerEvidenceDetails"), body = nodes.get("providerEvidenceBody");
  details.open = true;
  const oldLoad = details.dispatch("toggle");
  state.session = {turns: [providerEvidenceTurn("run-new")]};
  intervals.find(timer => timer.delay === 700).callback();
  assert.equal(details.open, false, "新的 Run 必须重新由用户选择展开");
  details.open = true;
  const newLoad = details.dispatch("toggle");
  const newChildren = body.children.slice(), replacements = body.replacements;
  oldResponse.resolve({evidence: {metadata: "old-run-only"}});
  await oldLoad;
  assert.deepEqual(body.children, newChildren);
  assert.equal(body.replacements, replacements);
  assert.equal(body.textContent.includes("old-run-only"), false);
  assert.match(body.textContent, /正在读取 Provider Evidence/);
  // 旧响应的 finally 也不能撤销新请求的去重身份。
  const repeatedNewOpen = details.dispatch("toggle");
  assert.deepEqual(requests, ["/turns/run-old/provider-evidence", "/turns/run-new/provider-evidence"]);
  newResponse.resolve({evidence: {metadata: "new-run-only"}});
  await Promise.all([newLoad, repeatedNewOpen]);
  assert.equal(details.open, true);
  assert.match(body.textContent, /new-run-only/);
  assert.equal(body.textContent.includes("old-run-only"), false);
  assert.equal(body.textContent.includes("正在读取 Provider Evidence…"), false);
  assert.equal(body.children.filter(node => node.className === "provider-evidence-raw").length, 1);
});

// A→B→A 会重新建立证据阅读周期；值相同的 Run/key 不能让第一份请求取得新周期所有权。
test("returning to the same run isolates stale evidence requests from the new read", async () => {
  const {context, nodes} = controller(["inspectorModel", "providerEvidenceDetails", "providerEvidenceBody"]);
  const oldResponse = deferredResponse(), currentResponse = deferredResponse(), requests = [];
  context.api = url => {
    requests.push(url);
    assert.equal(url, "/turns/run-a/provider-evidence");
    assert.ok(requests.length <= 2, "旧请求的 finally 不能清除新周期的在途去重身份");
    return requests.length === 1 ? oldResponse.promise : currentResponse.promise;
  };
  const turnA = providerEvidenceTurn("run-a");
  context.renderInspectorModel(turnA);
  const details = nodes.get("providerEvidenceDetails"), body = nodes.get("providerEvidenceBody");
  details.open = true;
  const oldLoad = details.dispatch("toggle");
  context.renderInspectorModel(providerEvidenceTurn("run-b"));
  context.renderInspectorModel(JSON.parse(JSON.stringify(turnA)));
  details.open = true;
  const currentLoad = details.dispatch("toggle");
  const currentChildren = body.children.slice();
  oldResponse.resolve({evidence: {metadata: "obsolete-a-response"}});
  await oldLoad;
  assert.equal(body.children.length, currentChildren.length, "迟到的旧 A 请求不能追加 raw 或移除当前 loading");
  assert.equal(body.children.every((node, index) => node === currentChildren[index]), true, "当前证据区的节点身份必须保留");
  assert.equal(body.textContent.includes("obsolete-a-response"), false);
  assert.match(body.textContent, /正在读取 Provider Evidence/);
  const repeatedOpen = details.dispatch("toggle");
  assert.equal(requests.length, 2);
  currentResponse.resolve({evidence: {metadata: "current-a-response"}});
  await Promise.all([currentLoad, repeatedOpen]);
  assert.equal(details.open, true);
  assert.match(body.textContent, /current-a-response/);
  assert.equal(body.textContent.includes("obsolete-a-response"), false);
  assert.equal(body.textContent.includes("正在读取 Provider Evidence…"), false);
  assert.equal(body.children.filter(node => node.className === "provider-evidence-raw").length, 1);
  await details.dispatch("toggle");
  assert.equal(requests.length, 2, "当前周期已加载后继续复用同一份 raw");
});

// 回答完成仍不能替代 Goal 验收；未知状态保持未知，供应商隐藏 CoT 不会被补写。
test("delivery and route do not turn completed replies into verified goals", () => {
  const {context, nodes} = controller(["inspectorDelivery", "inspectorSotaRoute", "executionSpine"]);
  context.renderInspectorDelivery({status: "COMPLETED", delivery: {finalization: {state: "DONE"}}});
  assert.match(nodes.get("inspectorDelivery").textContent, /回答已保存验收未验收/);
  context.renderInspectorSotaRoute({sota_route: {status: "UNKNOWN", metrics: {}, peer_count: 0}});
  assert.match(nodes.get("inspectorSotaRoute").textContent, /UNKNOWN · 待核对/);
  assert.match(nodes.get("inspectorSotaRoute").textContent, /Hidden CoT不可见，不作推断/);
  context.renderExecutionSpine({status: "UNKNOWN", operations: []});
  assert.match(nodes.get("executionSpine").textContent, /需先核对外部效果/);
});

// 三类存活证据独立展示；租约还活着不能掩盖没有 durable progress。
test("recovery separates Executor heartbeat, Driver heartbeat and durable progress", () => {
  const {context, nodes} = controller(["inspectorRecovery"], {data: {executor: {active: true, heartbeat_age_seconds: 0}}});
  context.renderInspectorRecovery({status: "RUNNING", driver_active: true,
    driver_lease: {lease_until: Date.now() / 1000 + 10, heartbeat_at: Date.now() / 1000, generation: 0},
    execution_cursor: {step: 0, checkpoint_step: 0, recovery_state: "UNKNOWN"},
    liveness: {seconds_since_progress: 200, suspected_no_progress: true}});
  const text = nodes.get("inspectorRecovery").textContent;
  assert.match(text, /Executor 心跳0 秒前/);
  assert.match(text, /Driver 心跳0 秒前/);
  assert.match(text, /最近进展200 秒前/);
  assert.match(text, /疑似无进展/);
  assert.match(text, /恢复状态UNKNOWN · 待核对/);
  assert.match(text, /代数0/);
});

// 轮询得到等值的新投影时保留交互节点；目标或计划的真实变化才触发重绘。
test("unchanged goal polling preserves cards and disclosure nodes while new facts render", async () => {
  const {context, nodes, load} = controller(["goalCards", "schedulerStatus", "createGoal", "scheduleForm"], {page: "goals", data: {}});
  const goal = {goal_id: "goal-1", state: "ACTIVE", title: "长期目标", description: "持续推进同一项工作",
    work: {current_state: "WORKING", progress_note: "已有持久进展", next_action: "核对下一步", revision: 1}};
  const schedule = {schedule_id: "schedule-1", goal_id: "goal-1", session_id: "session-1", prompt: "检查进展",
    enabled: true, due_at: "2026-10-04T12:00:00Z", interval_seconds: 3600, settings: {provider: "fixture", model: "fixture-model"}, wakeups: []};
  let heartbeat = 0;
  context.api = async url => {
    const value = url === "/goals" ? {goals: [goal]} : {schedules: [schedule], scheduler: {running: true, heartbeat: ++heartbeat}};
    // 模拟每次 HTTP 都产生新对象，并让未展示的心跳变化，避免引用相等掩盖重绘缺陷。
    return JSON.parse(JSON.stringify(value));
  };
  load("goals.js");
  await context.renderGoals();
  const cards = nodes.get("goalCards"), card = cards.children[0];
  const progress = card.children.find(node => node.className === "goal-detail");
  const plans = card.children.find(node => node.className === "goal-schedules");
  assert.ok(progress);
  assert.ok(plans);
  const progressSummary = progress.children[0], planSummary = plans.children[0], actions = card.children[1];
  progress.open = true;
  plans.open = true;
  await Promise.all([progress.dispatch("toggle"), plans.dispatch("toggle")]);
  const replacements = cards.replacements;
  await context.renderGoals();
  await context.renderGoals();
  assert.equal(cards.children[0], card);
  assert.equal(card.children[1], actions, "行内按钮的节点身份必须保留");
  assert.equal(progress.children[0], progressSummary);
  assert.equal(plans.children[0], planSummary);
  assert.equal(progress.open, true);
  assert.equal(plans.open, true);
  assert.equal(cards.replacements, replacements);

  goal.work.progress_note = "第二个已记录进展";
  goal.work.revision = 2;
  await context.renderGoals();
  assert.notEqual(cards.children[0], card);
  assert.match(cards.textContent, /第二个已记录进展/);
  assert.equal(cards.children[0].children.find(node => node.className === "goal-detail").open, true);
  const changedCard = cards.children[0];
  schedule.enabled = false;
  await context.renderGoals();
  assert.notEqual(cards.children[0], changedCard, "计划状态也属于真实展示事实，不能被签名缓存遗漏");
  assert.match(cards.textContent, /已暂停/);
  assert.equal(cards.children[0].children.find(node => node.className === "goal-schedules").open, true);
});

// 请求被网络拒绝后，同一表单必须沿用 request_id；第二次提交不创建第二个意图身份。
test("schedule form retries keep the same request identity and explicit interval", async () => {
  const ids = ["goalTitleInput", "goalDescriptionInput", "goalDialog", "createGoal", "scheduleForm", "scheduleGoalTitle", "scheduleSession", "schedulePrompt", "scheduleDue", "scheduleInterval", "scheduleModel", "scheduleDialog", "schedulerStatus", "goalCards"];
  const {context, nodes, load} = controller(ids, {page: "goals", data: {sessions: [{id: "session-1", title: "工作"}], settings: {provider: "test", model: "fixture"}}});
  const submissions = [];
  context.crypto = {randomUUID: () => "stable-request"};
  context.refresh = async () => {};
  context.toast = () => {};
  context.empty = () => {};
  context.api = async (url, payload) => {
    if (payload) {
      submissions.push(payload);
      if (submissions.length === 1) throw new Error("offline");
      return {};
    }
    return url === "/goals" ? {goals: []} : {schedules: [], scheduler: {}};
  };
  load("goals.js");
  await context.openSchedule({goal_id: "goal-1", title: "长期工作", work: {next_action: "继续"}});
  nodes.get("scheduleSession").value = "session-1";
  nodes.get("scheduleInterval").value = "300";
  const event = {preventDefault() {}, submitter: new Element("button")};
  await nodes.get("scheduleForm").onsubmit(event);
  await nodes.get("scheduleForm").onsubmit(event);
  assert.equal(submissions.length, 2);
  assert.equal(submissions[0].request_id, "stable-request");
  assert.equal(submissions[1].request_id, submissions[0].request_id);
  assert.equal(submissions[1].interval_seconds, 300);
  assert.match(submissions[1].due_at, /Z$/);
  assert.equal(event.submitter.disabled, false);
});
