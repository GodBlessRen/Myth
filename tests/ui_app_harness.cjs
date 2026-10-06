// 执行真实 app.js；轻量 DOM 只承载事件，不模拟服务端 Run 或授权结果。
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

function boot(storage = {}, options = {}) {
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
  // 严格模式从真实 HTML 取节点身份；不存在的 id 返回 null，不让替身凭空补齐页面。
  const html = options.html ?? fs.readFileSync(path.join(__dirname, "../src/myth/webui/index.html"), "utf8");
  const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
  document.getElementById = options.strictDOM
    ? id => ids.has(id) ? $(id) : null
    : $;
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


module.exports = {Element, boot, session, deferred, compose};
