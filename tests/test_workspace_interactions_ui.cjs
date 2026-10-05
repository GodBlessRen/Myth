// 执行真实 app.js；轻量 DOM 只承载事件，不模拟服务端 Run 或授权结果。
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

class Element {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = {};
    this.listeners = {};
    this.value = "";
    this.className = "";
    this.scrollHeight = 52;
    this.scrollTop = 0;
    this.clientHeight = 600;
    this.isConnected = true;
    this.disabled = false;
    this.namespaceURI = "http://www.w3.org/2000/svg";
    this.classList = {
      contains: (name) => this.className.split(/\s+/).includes(name),
      toggle: (name, force) => {
        const classes = new Set(this.className.split(/\s+/).filter(Boolean));
        const enabled = force === undefined ? !classes.has(name) : force;
        enabled ? classes.add(name) : classes.delete(name);
        this.className = [...classes].join(" ");
        return enabled;
      },
      add: (name) => this.classList.toggle(name, true),
      remove: (name) => this.classList.toggle(name, false),
    };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return (this._text || "") + this.children.map((child) => child.textContent ?? String(child)).join(""); }
  get options() { return this.children.filter(child => child.tagName === "OPTION"); }
  append(...children) { this.children.push(...children); }
  prepend(...children) { this.children.unshift(...children); }
  replaceChildren(...children) {
    this.children = children; this._text = "";
    if (this.tagName === "SELECT") this.value = children[0]?.value || "";
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  dispatch(type, event = {}) { for (const listener of this.listeners[type] || []) listener(event); }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  focus() { if (this.document) this.document.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; this.dispatch("close"); }
  scrollIntoView() {}
  scrollTo({ top }) { this.scrollTop = top; }
  getBoundingClientRect() { return { left: 10, top: 10, right: 300, bottom: 300 }; }
}

function boot(storage = {}) {
  const nodes = new Map();
  const dialogs = ["commandPalette", "projectDialog", "sessionDialog", "goalDialog", "knowledgeDialog", "documentDialog", "controlDialog"];
  const themes = ["light", "dark", "system"].map((value) => {
    const node = new Element("button"); node.dataset.themeChoice = value; return node;
  });
  const document = new Element("document");
  const $ = (id) => {
    if (!nodes.has(id)) {
      const node = new Element(dialogs.includes(id) ? "dialog" : ["reasoningSetting", "turnThinkingInput"].includes(id) ? "select" : "div");
      node.id = id; node.document = document; nodes.set(id, node);
    }
    return nodes.get(id);
  };
  document.getElementById = $;
  document.body = new Element("body");
  document.documentElement = new Element("html");
  document.documentElement.dataset.theme = "light";
  document.activeElement = $("newChat");
  document.createElement = (tag) => { const node = new Element(tag); node.document = document; return node; };
  document.createElementNS = (_, tag) => document.createElement(tag);
  document.createTextNode = (text) => { const node = new Element("text"); node.textContent = text; return node; };
  document.querySelector = (query) => query === "dialog[open]" ? dialogs.map($).find((node) => node.open) || null : null;
  document.querySelectorAll = (query) => query === "[data-theme-choice]" ? themes : query === "dialog" ? dialogs.map($) : [];
  const listeners = {};
  let hash = "#chat";
  const location = { get hash() { return hash; }, set hash(value) { hash = value.startsWith("#") ? value : "#" + value; } };
  let uuid = 0;
  const context = vm.createContext({
    document, location,
    window: { matchMedia: () => ({ matches: false, addEventListener() {} }), addEventListener: (type, callback) => (listeners[type] ||= []).push(callback) },
    localStorage: { getItem: (key) => storage[key] || null, setItem: (key, value) => { storage[key] = value; }, removeItem: (key) => { delete storage[key]; } },
    history: { replaceState: (_, __, value) => { location.hash = value; } },
    crypto: { randomUUID: () => "request-" + ++uuid },
    navigator: { clipboard: { writeText: async () => {} } },
    createReadReconnector: () => ({ start() {} }),
    // 本单元固定对话交互；模型目录与菜单的真实行为另由浏览器回归覆盖。
    poolRefreshPrices: () => {},
    setTimeout: () => 1, clearTimeout() {}, AbortController, TextDecoder,
    fetch: async () => { throw new Error("unexpected network request"); }, console,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/myth/webui/app.js"), "utf8"), context);
  const state = vm.runInContext("state", context);
  state.data = { settings: { model: "test-model", provider: "ollama" }, sessions: [], projects: [], documents: [], goals: [] };
  return { context, state, $, document, themes, storage, listeners };
}

function session(id = "s1", status) {
  return { id, title: id, turns: status ? [{ status }] : [], messages: [], artifacts: [] };
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
function compose(h, id = "s1", text = "测试消息") {
  h.state.id = id;
  h.state.page = "chat";
  h.state.session = session(id);
  h.context.restoreDraft(id || "new");
  h.$("prompt").value = text;
  h.context.saveDraft();
}

test("a live elapsed-time refresh preserves historical message nodes", () => {
  const h = boot();
  const s = session("live");
  s.messages = [{role: "user", content: "保留这一段阅读内容"}];
  s.turns = [{run_id: "run-live", status: "RUNNING", current_step: 0, activities: [], driver_active: true, reply_timing: {elapsed_seconds: 1}}];
  h.context.renderThread(s);
  const message = h.$("thread").children[0];
  s.turns[0].reply_timing.elapsed_seconds = 2;
  h.context.renderThread(s);
  assert.equal(h.$("thread").children[0], message);
  s.turns[0].driver_active = false;
  h.context.renderThread(s);
  assert.match(h.$("thread").textContent, /Driver 已断开，等待恢复/);
  const typing = h.$("thread").children.at(-1);
  assert.equal(typing.children.some(node => node.className === "typing-dot"), false);
});

// 中文投影不能覆盖版本变化或改写成熟度事实；冻结数据同时检查纯展示边界。
test("architecture localization preserves raw state and unrecognized newer backend facts", () => {
  const h = boot();
  const known = Object.freeze({ label: "Ticket", maturity: "usable", responsibility: "Durable authority to start one Attempt; not success proof." });
  const changed = Object.freeze({ label: "constructor", maturity: "experimental", responsibility: "New backend boundary, not the previous description." });
  const cap = Object.freeze({ id: "file.read", state: "executable", family: "file", risk: "read" });
  h.state.data.platform = { core: [known, changed], domains: [], strategies: [], adapters: [], capabilities: [cap], executable_capabilities: ["file.read"] };
  h.context.renderRuntime();
  assert.match(h.$("runtimeCore").textContent, /启动一次 Attempt 的持久授权；不代表操作成功/);
  assert.match(h.$("runtimeCore").textContent, /可使用/);
  assert.match(h.$("runtimeCore").textContent, /constructor/);
  assert.match(h.$("runtimeCore").textContent, /experimental/);
  assert.match(h.$("runtimeCore").textContent, /New backend boundary/);
  assert.match(h.$("platformCapabilities").textContent, /文件 · 读取/);
  assert.match(h.$("platformCapabilities").textContent, /可执行/);
  assert.equal(known.maturity, "usable");
  assert.equal(cap.state, "executable");
});

test("a late connection report cannot repopulate a different provider form", async () => {
  const h = boot(), pending = deferred();
  h.$("provider").value = "ollama";
  h.$("ollamaUrl").value = "http://127.0.0.1:11434";
  h.context.api = async () => pending.promise;
  const checking = h.context.checkConnection(false);
  assert.equal(h.$("checkConnection").disabled, true);
  h.$("provider").value = "deepseek";
  h.$("provider").onchange();
  pending.resolve({ready: true, details: {models: ["old-ollama-model"]}});
  await checking;
  assert.equal(h.state.connection, null);
  assert.equal(h.$("model").value, "");
  assert.equal(h.$("modelOptions").children.length, 0);
  assert.equal(h.$("connectionResult").textContent, "");
  assert.equal(h.$("checkConnection").disabled, false);
});

test("connection capability catalogs belong to the checked endpoint", async () => {
  const h = boot();
  h.$("provider").value = "ollama";
  h.$("ollamaUrl").value = "http://127.0.0.1:11434";
  h.$("model").value = "test-model";
  h.context.api = async () => ({ready: true, details: {models: ["test-model"], model_capabilities: {"test-model": {reasoning: {levels: ["low", "high"]}}}}});
  await h.context.checkConnection(false);
  assert.equal(h.context.modelCapability().reasoning.levels[1], "high");
  h.$("ollamaUrl").value = "http://127.0.0.1:9999";
  h.$("ollamaUrl").dispatch("input");
  assert.equal(h.context.modelCapability(), null);
  assert.equal(h.$("modelOptions").children.length, 0);
});

test("settings saves are single-flight and preserve edits made during the request", async () => {
  const h = boot(), pending = deferred();
  let calls = 0;
  h.$("provider").value = "deepseek";
  h.$("model").value = "deepseek-chat";
  h.context.api = async () => { calls++; return pending.promise; };
  const saving = h.$("saveSettings").onclick();
  await h.$("saveSettings").onclick();
  h.$("model").value = "deepseek-reasoner";
  pending.resolve({provider: "deepseek", model: "deepseek-chat"});
  await saving;
  assert.equal(calls, 1);
  assert.equal(h.state.data.settings.model, "deepseek-chat");
  assert.equal(h.$("model").value, "deepseek-reasoner");
  assert.equal(h.$("settingsSaved").textContent, "当前修改尚未保存");
  assert.equal(h.$("saveSettings").disabled, false);
});

test("saving Thinking keeps a newer unsaved selection on the same model", async () => {
  const h = boot(), pending = deferred();
  h.state.data.settings = {provider: "deepseek", model: "reasoner", thinking: "high"};
  h.$("provider").value = "deepseek";
  h.$("model").value = "reasoner";
  h.state.connectionKey = h.context.connectionConfigKey(h.context.settingsPayload());
  h.state.connection = {ready: true, details: {model_capabilities: {
    reasoner: {reasoning: {levels: ["low", "high"]}},
    plain: {context_window: 8192},
  }}};
  h.context.renderAdaptiveModelSettings({thinking: "high"});
  assert.equal(h.$("reasoningSetting").value, "high");
  h.context.api = async () => pending.promise;
  const saving = h.$("saveSettings").onclick();
  h.$("reasoningSetting").value = "low";
  pending.resolve({provider: "deepseek", model: "reasoner", thinking: "high"});
  await saving;
  assert.equal(h.$("reasoningSetting").value, "low");
  assert.equal(h.state.data.settings.thinking, "high");
  assert.equal(h.context.settingsPayload().thinking, "low");
  assert.equal(h.$("settingsSaved").textContent, "当前修改尚未保存");
  h.$("model").value = "plain";
  h.context.renderAdaptiveModelSettings();
  assert.equal(h.context.settingsPayload().thinking, null);
});

test("equal session projections preserve focused recent links but title changes update", () => {
  const h = boot();
  h.state.id = "s1";
  h.state.data.sessions = [{id: "s1", title: "会话一", pinned: false, updated_at: "first"}];
  h.context.renderSidebar();
  const link = h.$("recentSessions").children[0];
  link.focus();
  h.state.data.sessions = [{id: "s1", title: "会话一", pinned: false, updated_at: "later"}];
  h.context.renderSidebar();
  assert.equal(h.$("recentSessions").children[0], link);
  assert.equal(h.document.activeElement, link);
  h.state.data.sessions[0].title = "改名后的会话";
  h.context.renderSidebar();
  assert.notEqual(h.$("recentSessions").children[0], link);
  assert.equal(h.$("recentSessions").children[0].title, "改名后的会话");
});

test("saved theme overrides initial markup and system choice removes the override", () => {
  const h = boot({ "myth-theme": "dark" });
  assert.equal(h.document.documentElement.dataset.theme, "dark");
  assert.equal(h.themes[1].getAttribute("aria-pressed"), "true");
  h.themes[2].onclick();
  assert.equal(h.storage["myth-theme"], undefined);
  assert.equal(h.document.documentElement.dataset.theme, "light");
  h.storage["myth-theme"] = "dark";
  for (const callback of h.listeners.storage) callback({ key: "myth-theme" });
  assert.equal(h.document.documentElement.dataset.theme, "dark");
});

test("composer blocks empty, composing, busy, loading and unresolved Run submissions", async () => {
  const h = boot();
  let calls = 0;
  h.context.api = async () => { ++calls; };
  compose(h);
  for (const status of ["RUNNING", "UNKNOWN", "INTERRUPTED", "PAUSED"]) {
    h.state.session = session("s1", status);
    h.context.updateComposer();
    assert.equal(h.$("send").disabled, true, status);
    await h.context.sendMessage();
  }
  h.state.session = session("s1", "WAITING_USER");
  assert.equal(h.context.composerCanSend(), true);
  for (const field of ["busy", "composing", "loadingSession"]) {
    h.state[field] = true;
    await h.context.sendMessage();
    h.state[field] = false;
  }
  h.$("prompt").value = "  \n ";
  await h.context.sendMessage();
  assert.equal(calls, 0);
});

test("Chinese IME confirmation never dispatches Enter as a message", () => {
  const h = boot();
  compose(h);
  let sends = 0;
  h.context.sendMessage = () => { ++sends; };
  const key = (values = {}) => ({ key: "Enter", preventDefault() {}, ...values });
  h.$("prompt").dispatch("compositionstart");
  h.$("prompt").onkeydown(key());
  h.$("prompt").dispatch("compositionend");
  h.$("prompt").onkeydown(key({ isComposing: true }));
  h.$("prompt").onkeydown(key({ keyCode: 229 }));
  h.$("prompt").onkeydown(key({ shiftKey: true }));
  assert.equal(sends, 0);
  h.$("prompt").onkeydown(key());
  assert.equal(sends, 1);
});

test("route changes keep text, attachments, Goal and request identity in their own session draft", async () => {
  const h = boot();
  compose(h, "a", "会话 A 草稿");
  h.state.attached = [{ id: "doc-a", title: "资料 A" }];
  h.state.pending = { id: "retry-a", fingerprint: "same" };
  h.$("chatGoal").value = "goal-a";
  h.context.openSession = async (id) => { h.state.session = session(id); h.state.loadingSession = false; };
  h.context.location.hash = "#sessions";
  await h.context.route();
  h.context.location.hash = "#chat/b";
  await h.context.route();
  assert.equal(h.$("prompt").value, "");
  assert.equal(h.state.attached.length, 0);
  assert.equal(h.state.pending, null);
  h.$("prompt").value = "会话 B 草稿";
  h.context.location.hash = "#chat/a";
  await h.context.route();
  assert.equal(h.$("prompt").value, "会话 A 草稿");
  assert.equal(h.state.attached[0].id, "doc-a");
  assert.equal(h.state.pending.id, "retry-a");
  assert.equal(h.$("chatGoal").value, "goal-a");
  assert.equal(h.state.drafts.get("b").text, "会话 B 草稿");
});

test("network failure preserves request_id and successful retry clears only submitted content", async () => {
  const h = boot();
  compose(h);
  const payloads = [];
  h.context.api = async (_, payload) => { payloads.push(payload); if (payloads.length === 1) throw new Error("timeout"); return {}; };
  h.context.refresh = async () => {};
  h.context.openSession = async () => {};
  await h.context.sendMessage();
  assert.equal(h.$("prompt").value, "测试消息");
  assert.equal(h.state.pending.id, "request-1");
  await h.context.sendMessage();
  assert.equal(payloads[0].request_id, payloads[1].request_id);
  assert.equal(h.state.pending, null);
  assert.equal(h.$("prompt").value, "");
  assert.equal(h.$("send").disabled, true);
});

test("late send completion does not clear the next session's draft or change captured Goal", async () => {
  const h = boot();
  compose(h, "a", "发送给 A");
  h.$("chatGoal").value = "goal-a";
  const response = deferred();
  let payload;
  h.context.api = async (_, value) => { payload = value; await response.promise; return {}; };
  h.context.refresh = async () => {};
  h.context.openSession = async () => {};
  const sending = h.context.sendMessage();
  ++h.state.generation;
  h.state.id = "b";
  h.state.session = session("b");
  h.context.restoreDraft("b");
  h.$("prompt").value = "保留 B 草稿";
  h.$("chatGoal").value = "goal-b";
  h.context.saveDraft();
  response.resolve();
  await sending;
  assert.equal(payload.goal_id, "goal-a");
  assert.equal(h.$("prompt").value, "保留 B 草稿");
  assert.equal(h.state.drafts.get("a").text, "");
  assert.equal(h.state.id, "b");
});

test("starting another new chat during session creation cannot hijack its composer", async () => {
  const h = boot();
  compose(h, null, "旧任务");
  const creation = deferred();
  h.context.api = async (url) => url === "/sessions" ? creation.promise : {};
  h.context.refresh = async () => {};
  h.context.openSession = async () => {};
  const sending = h.context.sendMessage();
  await h.context.newChat();
  h.$("prompt").value = "新草稿";
  h.context.saveDraft();
  creation.resolve(session("created-for-old-task"));
  await sending;
  assert.equal(h.state.id, null);
  assert.equal(h.state.composerKey, "new");
  assert.equal(h.$("prompt").value, "新草稿");
  assert.equal(h.context.location.hash, "#chat");
});

test("keyboard command search navigates to matched sessions without interpreting their title as HTML", () => {
  const h = boot();
  h.state.data.sessions = [{ id: "target-session", title: "<img src=x> 中文会话" }];
  h.context.openCommandPalette();
  assert.equal(h.$("commandPalette").open, true);
  h.$("commandSearch").value = "中文会话";
  h.$("commandSearch").oninput();
  assert.equal(h.$("commandResults").children.length, 1);
  assert.match(h.$("commandResults").children[0].textContent, /<img src=x>/);
  h.$("commandSearch").onkeydown({ key: "Enter", preventDefault() {} });
  assert.equal(h.context.location.hash, "#chat/target-session");
  assert.equal(h.$("commandPalette").open, false);
});

test("native dialogs restore focus and backdrop dismissal requires a pointer down outside", () => {
  const h = boot();
  const trigger = h.$("createProject");
  trigger.focus();
  h.context.openDialog("projectDialog", "projectNameInput");
  const dialog = h.$("projectDialog");
  dialog.dispatch("pointerdown", { target: dialog, clientX: 50, clientY: 50 });
  dialog.dispatch("click", { target: dialog, clientX: 0, clientY: 0 });
  assert.equal(dialog.open, true);
  dialog.dispatch("pointerdown", { target: dialog, clientX: 0, clientY: 0 });
  dialog.dispatch("click", { target: dialog, clientX: 0, clientY: 0 });
  assert.equal(dialog.open, false);
  assert.equal(h.document.activeElement, trigger);
});

test("late native dialog releases Runtime drawer before acquiring modal focus", () => {
  const h = boot();
  const dialog = h.$("documentDialog");
  dialog.inert = true;
  h.state.closeRuntimeDrawer = () => { dialog.inert = false; };
  dialog.showModal = () => { assert.equal(dialog.inert, false); dialog.open = true; };
  h.context.openDialog("documentDialog");
  assert.equal(dialog.open, true);
});
