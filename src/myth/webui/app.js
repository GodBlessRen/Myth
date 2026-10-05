// 主工作台：会话、项目、知识、设置和路由的浏览器投影。
// state 只拥有展示/请求状态；Run、预算、Goal、收据由服务端所有。超时重试须保留身份，迟到响应须核对 generation。
"use strict";
// 共享 DOM 定位助手；固定 id 的 HTML 必须与三个脚本保持一致。
const $ = (id) => document.getElementById(id);
const state = {
  // bootstrap 公开投影；不包含 token。
  data: null,
  // 当前会话公开快照；不是 Run 状态所有者。
  session: null,
  // 当前 hash 页面的名称。
  page: "chat",
  // 当前页面的业务身份，随路由变化。
  id: null,
  // 页面请求代数；迟到响应必须匹配，防止页面串台。
  generation: 0,
  // 已渲染讨论的签名；仅用于增量展示。
  threadKey: "",
  // 最近一次供应商检查报告；不等于任务结果。
  connection: null,
  // 连接目录只属于被检查的 Provider/端点；编辑后不能沿用旧供应商的能力。
  connectionKey: null,
  // 连接请求代数；晚到检查不能重填已切换的模型表单。
  connectionGeneration: 0,
  // 脱敏账号投影；凭据保存在系统库。
  chatgptAuth: null,
  // Claude OAuth 的脱敏状态；浏览器不保存 token。
  claudeAuth: null,
  // API Key Provider 的脱敏连接状态；浏览器从不保存 secret。
  providerKeys: null,
  // 会话列表的归档筛选。
  archived: false,
  // 当前编辑的会话元数据副本。
  editingSession: null,
  // 当前编辑的项目元数据副本。
  editingProject: null,
  // 正文/附件/设置指纹与稳定 request_id；失败重试保留。
  pending: null,
  // 尚未发送的显式资料选择；发送时冻结快照。
  attached: [],
  // 本地发送互斥标志；不代替服务器准入约束。
  busy: false,
  // 单个只读重连控制器；与业务 Run 生命周期独立。
  poll: null,
  // 首次 bootstrap 失败后继续只读重连；已有内容和 request_id 保留到服务恢复。
  initialized: false,
  // 草稿按会话身份保存在当前标签页；切页不会把正文、附件或重试身份带到另一会话。
  drafts: new Map(),
  // 当前输入归属的会话键；新会话取得持久身份后显式迁移。
  composerKey: "new",
  // 中文输入法组合事件；确认候选字时不能发出消息。
  composing: false,
  // 会话加载仅约束可编辑状态，不是业务运行状态。
  loadingSession: false,
  // 手机导航展示控制器；不保存到浏览器存储或数据库。
  closeNavigationDrawer: null,
  // Runtime 模态抽屉的本地关闭入口；原生弹窗接管焦点前先释放背景，不涉及执行控制。
  closeRuntimeDrawer: null,
  // 最近会话按实际显示事实缓存；轮询不能反复移除正在被键盘聚焦的锚点。
  sidebarKey: null,
};
// 既有图标的固定矢量目录；新增图标沿用此系统。
const iconPaths = {
  plus: "M12 5v14M5 12h14",
  chat: "M21 11.5a8.4 8.4 0 0 1-9 8.4 9.5 9.5 0 0 1-4-.9L3 21l1.8-5A9 9 0 1 1 21 11.5Z",
  history: "M3 11a9 9 0 1 1 2.5 7M3 5v6h6M12 7v5l3 2",
  folder: "M3 6h7l2 3h9v11H3Z",
  book: "M3 4h7l2 2 2-2h7v16h-7l-2 2-2-2H3ZM12 6v16",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1Z",
  menu: "M4 6h16M4 12h16M4 18h16",
  chevron: "m8 10 4 4 4-4",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  spark: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z",
  code: "m8 5-6 7 6 7m8-14 6 7-6 7M14 3l-4 18",
  pen: "m15 4 5 5-12 12H3v-5ZM12 7l5 5",
  clip: "m9 17 8-8a3 3 0 0 0-4-4l-9 9a5 5 0 0 0 7 7l9-9",
  info: "M12 10v7M12 7h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  arrow: "M12 19V5m-6 6 6-6 6 6",
  search: "M17 17l5 5M19 10a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
  upload: "M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6",
  file: "M14 3H5v18h14V8ZM14 3v5h5M8 12h8M8 16h6",
  download: "M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7",
  sun: "M12 2v2M12 20v2M4.93 4.93 6.34 6.34M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z",
  moon: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 9.79 9.79 7 7 0 0 0 21 12.79Z",
  pin: "m8 3 8 0-1 6 4 4H5l4-4ZM12 13v8",
  close: "m6 6 12 12M18 6 6 18",
  down: "M12 5v14m-6-6 6 6 6-6",
  right: "M5 12h14m-6-6 6 6-6 6",
  target: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0ZM13 12a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z",
  activity: "M3 12h4l3-8 4 16 3-8h4",
};
// 创建安全 DOM 节点，正文经 textContent 写入；模型/资料文本不解释为 HTML。
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = String(text);
  return e;
}
// 按固定 SVG 路径目录创建图标；输入只选择名称，不注入任意 SVG。
function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(svg.namespaceURI, "path");
  p.setAttribute("d", iconPaths[name] || iconPaths.file);
  svg.append(p);
  return svg;
}
// 同一太极矢量用于品牌与真实等待；图片无业务语义，状态继续由相邻文字说明。
function taijiMark(waiting = false) {
  const mark = el("img", "taiji-mark" + (waiting ? " taiji-wait" : ""));
  mark.src = "/taiji.svg";
  mark.alt = "";
  mark.setAttribute("aria-hidden", "true");
  mark.width = 16;
  mark.height = 16;
  return mark;
}
document
  .querySelectorAll("[data-icon]")
  .forEach((e) => e.replaceWith(icon(e.dataset.icon)));

// 奶油白 / 星空黑仅改变浏览器投影；主题选择保存在本机，不进入 Runtime 或会话事实。
const THEME_STORAGE_KEY = "myth-theme";
const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
// 读取本机已保存的显式主题；读取失败返回空值并由系统偏好决定，不影响任何 Runtime 状态。
function storedTheme() {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch (_) {
    return null;
  }
}
// 应用纯展示主题并可选持久到 localStorage；不把 UI 外观写入会话、Run 或业务设置。
function applyTheme(theme, persist = false) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  document.documentElement.style.colorScheme = next;
  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.content = next === "dark" ? "#0E100F" : "#F8F4ED";
  const button = $("themeToggle");
  if (button) {
    button.replaceChildren(icon(next === "dark" ? "sun" : "moon"));
    button.setAttribute("aria-pressed", String(next === "dark"));
    button.setAttribute(
      "aria-label",
      next === "dark" ? "切换到奶油白" : "切换到星空黑",
    );
    button.title = next === "dark" ? "奶油白" : "星空黑";
  }
  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch (_) {
      // 主题持久化不可用时仍保留当前页面主题。
    }
  }
  const choice = storedTheme() || "system";
  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    const selected = button.dataset.themeChoice === choice;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}
applyTheme(
  storedTheme() || document.documentElement.dataset.theme ||
    (themeMedia.matches ? "dark" : "light"),
);
themeMedia.addEventListener?.("change", (event) => {
  if (!storedTheme()) applyTheme(event.matches ? "dark" : "light");
});
window.addEventListener("storage", (event) => {
  if (event.key === THEME_STORAGE_KEY)
    applyTheme(storedTheme() || (themeMedia.matches ? "dark" : "light"));
});
// 切换已有节点可见性；只改变展示，不改变 Run 状态。
function show(id, yes) {
  $(id).classList.toggle("hidden", !yes);
}
// 显示一次操作结果并在五秒后隐藏；提示不是持久业务证据。
function toast(text) {
  $("toast").textContent = text;
  show("toast", true);
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => show("toast", false), 5000);
}
// 工作区 JSON 请求最多等待二十秒；超时只停止本地等待，重试准入须复用 request_id。
async function api(path, value) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const r = await fetch("/api/workspace" + path, {
      method: value === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: value === undefined ? undefined : JSON.stringify(value),
      signal: controller.signal,
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  } finally {
    clearTimeout(timer);
  }
}
// 请求脱敏认证投影；浏览器只取得登录入口和状态，不保存 token。
async function authApi(path, value) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const r = await fetch("/api/auth/chatgpt" + path, {
      method: value === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: value === undefined ? undefined : JSON.stringify(value),
      signal: controller.signal,
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  } finally {
    clearTimeout(timer);
  }
}
// Claude OAuth 的独立认证接口；与 ChatGPT OAuth 使用不同 namespace/callback，避免跨提供方 state 混用。
async function claudeAuthApi(path, value) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const r = await fetch("/api/auth/claude" + path, {
      method: value === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: value === undefined ? undefined : JSON.stringify(value),
      signal: controller.signal,
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  } finally {
    clearTimeout(timer);
  }
}
// API Key Provider 的应用内凭据接口；浏览器只在 connect 请求中短暂持有用户刚粘贴的 secret。
async function providerAuthApi(path, value) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const r = await fetch("/api/auth/providers" + path, {
      method: value === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: value === undefined ? undefined : JSON.stringify(value),
      signal: controller.signal,
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  } finally {
    clearTimeout(timer);
  }
}

// 把数据库 UTC 时间投影为本地中文日期；不改写保存时间。
function date(value) {
  return new Date(value.replace(" ", "T") + "Z").toLocaleDateString("zh-CN", {
    month: "short",
    day: "numeric",
  });
}
// 格式化字节数用于展示；KB 按千字节显示，不当成 Token。
function bytes(n) {
  return n > 1000 ? `${(n / 1000).toFixed(1)} KB` : `${n} B`;
}
// 关闭窄屏导航和遮罩，保留当前页面/执行状态。
function closeNavigation() {
  if (state.closeNavigationDrawer) state.closeNavigationDrawer();
  else {
    $("sidebar").classList.remove("open");
    $("menuToggle").setAttribute("aria-expanded", "false");
    show("sidebarShade", false);
  }
}
// 手机导航成为独立模态区域；背景、焦点和断点只属于展示层，关闭时逐项释放。
function bindNavigationDrawer() {
  const panel = $("sidebar"), toggle = $("menuToggle");
  const compact = window.matchMedia("(max-width: 800px)");
  const background = new Map();
  let previousFocus = null;
  const targets = () => [...panel.querySelectorAll("a[href], button, input, [tabindex]")]
    .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
  const setOpen = (requested) => {
    const open = compact.matches && requested;
    const wasOpen = panel.classList.contains("open");
    panel.classList.toggle("open", open);
    panel.inert = compact.matches && !open || $("runtimeInspector")?.classList.contains("open");
    toggle.setAttribute("aria-expanded", String(open));
    show("sidebarShade", open);
    document.body.classList.toggle("navigation-open", open);
    if (open) {
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-modal", "true");
      if (!wasOpen) {
        previousFocus = document.activeElement;
        for (const node of document.querySelectorAll(".shell > *")) {
          if (node === panel || node.id === "sidebarShade") continue;
          background.set(node, node.inert);
          node.inert = true;
        }
        requestAnimationFrame(() => { if (panel.classList.contains("open")) targets()[0]?.focus(); });
      }
    } else {
      panel.removeAttribute("role");
      panel.removeAttribute("aria-modal");
      // 另一抽屉的闭合规则随当前视口计算，不能恢复已过期断点的 inert 快照。
      background.forEach((value, node) => {
        node.inert = node.id === "runtimeInspector" ? window.matchMedia("(max-width: 1120px)").matches : value;
      });
      background.clear();
      if (wasOpen) {
        const target = previousFocus?.isConnected ? previousFocus : toggle;
        if (target.getClientRects().length) target.focus();
        else $("mainContent").focus();
      }
    }
  };
  state.closeNavigationDrawer = () => setOpen(false);
  toggle.onclick = () => setOpen(!panel.classList.contains("open"));
  $("sidebarShade").onclick = closeNavigation;
  document.addEventListener("keydown", event => {
    if (!panel.classList.contains("open")) return;
    if (event.key === "Tab") {
      const items = targets(), first = items[0], last = items.at(-1);
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    }
  });
  compact.addEventListener("change", () => setOpen(false));
  window.addEventListener("hashchange", closeNavigation);
  setOpen(false);
}
// 更新 hash 路由并关闭导航；业务数据由 route 异步取得。
function go(page, id) {
  location.hash = id ? `${page}/${encodeURIComponent(id)}` : page;
  closeNavigation();
}
// 装配空状态与明确操作按钮；不会因空页面自动创建业务工作。
function empty(parent, title, copy, iconName = "chat", action, label) {
  const c = el("div", "empty-card");
  c.append(icon(iconName), el("h3", "", title), el("p", "", copy));
  if (action) {
    const b = el("button", "primary", label);
    b.onclick = action;
    c.append(b);
  }
  parent.append(c);
}
// 重建可见项目选项并恢复显式选择；范围仍由服务端校验。
function fillProjects(select, emptyLabel, selected = "") {
  select.replaceChildren();
  const first = el("option", "", emptyLabel);
  first.value = "";
  select.append(first);
  state.data.projects.forEach((p) => {
    const o = el("option", "", p.name);
    o.value = p.id;
    select.append(o);
  });
  select.value = selected;
}
// 展示未归档 Goal 与进度；选中 Goal 不等于已获新 Run 授权。
function fillGoals(select, selected = "") {
  if (!select) return;
  select.replaceChildren();
  const first = el("option", "", "无 Goal");
  first.value = "";
  select.append(first);
  (state.data.goals || [])
    .filter((g) => g.state !== "ARCHIVED")
    .forEach((g) => {
      const work = g.work || {};
      const label =
        g.title + (work.current_state ? " · " + work.current_state : "");
      const o = el("option", "", label);
      o.value = g.goal_id;
      select.append(o);
    });
  select.value = selected || "";
}
// 从当前 bootstrap 投影最近会话；页面活动标记与 Driver 状态分开。
function renderSidebar() {
  const box = $("recentSessions");
  const sessions = state.data.sessions.slice(0, 9);
  const key = JSON.stringify([state.page, state.id, sessions.map(s => [s.id, s.title, s.pinned])]);
  if (key !== state.sidebarKey) {
    state.sidebarKey = key;
    box.replaceChildren();
    if (!sessions.length)
      box.append(el("p", "recent-empty", "暂无会话"));
    sessions.forEach((s) => {
      const a = el("a", "recent-item" + (state.id === s.id ? " active" : ""));
      a.href = `#chat/${s.id}`;
      if (s.pinned) {
        const pin = el("span", "pin");
        pin.append(icon("pin"));
        pin.setAttribute("aria-label", "已置顶");
        a.append(pin);
      }
      a.append(el("span", "recent-title", s.title));
      a.title = s.title;
      if (state.page === "chat" && state.id === s.id) a.setAttribute("aria-current", "page");
      a.onclick = closeNavigation;
      box.append(a);
    });
  }
  document
    .querySelectorAll("[data-page]")
    .forEach((a) => {
      const active = a.dataset.page === state.page;
      a.classList.toggle("active", active);
      if (active) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
  window.MythStudio?.sync(state.session, state.page, state.id);
}
// 刷新共享产品投影；并发页面请求通过各自 generation 防止迟到覆写。
async function refresh() {
  state.data = await api("");
  renderSidebar();
}
// 读取当前连接目录中某模型的公开能力；目录缺失时返回空，不用品牌猜测补齐。
function modelCapability(modelId = $("model").value.trim()) {
  if (state.connectionKey !== connectionConfigKey(settingsPayload())) return null;
  const profiles = state.connection?.details?.model_capabilities;
  return profiles && typeof profiles === "object" ? profiles[modelId] || null : null;
}
// 将动态 Thinking 选择还原为持久设置；default 表示交给 Provider 使用其模型默认值。
function reasoningSelectionValue(select = $("reasoningSetting")) {
  if (!select || !select.value || select.value === "default") return null;
  if (select.value === "__on__") return true;
  if (select.value === "__off__") return false;
  return select.value;
}
// 按 Provider/model capability 生成原生 reasoning 选项；不制造 Myth 全局 effort 档位。
function fillReasoningSelect(select, profile, current, metaNode = null) {
  select.replaceChildren();
  const reasoning = profile?.reasoning;
  if (!reasoning) return false;
  const add = (value, label) => {
    const option = el("option");
    option.value = value;
    option.textContent = label;
    select.append(option);
  };
  add(
    "default",
    reasoning.default ? `默认 · ${reasoning.default}` : "默认 · Provider 决定",
  );
  const seen = new Set();
  if (reasoning.kind === "toggle") { add("__on__", "开启推理"); seen.add("__on__"); }
  if (reasoning.off !== undefined && reasoning.off !== null) {
    const raw = typeof reasoning.off === "boolean"
      ? (reasoning.off ? "__on__" : "__off__")
      : String(reasoning.off);
    seen.add(raw);
    add(raw, `关闭 · ${String(reasoning.off)}`);
  }
  (reasoning.levels || []).forEach((level) => {
    const raw = String(level);
    if (seen.has(raw)) return;
    seen.add(raw);
    add(raw, raw);
  });
  const currentRaw =
    current === null || current === undefined
      ? "default"
      : current === true
        ? "__on__"
        : current === false
          ? "__off__"
          : String(current);
  if (![...select.options].some((option) => option.value === currentRaw)) {
    add(currentRaw, `${currentRaw} · 已保存`);
    select.lastElementChild.disabled = true;
  }
  select.value = currentRaw;
  if (metaNode) {
    const source = profile.source === "remote" ? "Provider 实时发现" : "Provider 能力声明";
    metaNode.textContent = `${source} · 增加推理通常需要更多时间与输出 Token；档位按该模型定义。`;
  }
  return true;
}
// 根据当前模型能力调整设置表单；只显示当前 Provider 真正声明/发现的控制。
function renderAdaptiveModelSettings(options = {}) {
  const provider = $("provider").value;
  show("ollamaEndpointField", provider === "ollama");
  show("ollamaContextField", provider === "ollama");
  const profile = modelCapability();
  const saved = state.data?.settings || {};
  const select = $("reasoningSetting");
  const modelKey = JSON.stringify([connectionConfigKey(settingsPayload()), $("model").value.trim()]);
  // 同一模型的重绘保留未保存选择；只有加载已保存设置才显式回填，避免保存期间的新编辑被覆盖。
  const currentThinking = Object.hasOwn(options, "thinking") ? options.thinking
    : select.dataset.modelKey === modelKey ? reasoningSelectionValue(select)
    : $("model").value.trim() === saved.model && connectionConfigKey(settingsPayload()) === connectionConfigKey(saved) ? saved.thinking : null;
  select.dataset.modelKey = modelKey;
  const reasoningVisible = fillReasoningSelect(
    $("reasoningSetting"),
    profile,
    currentThinking,
    $("reasoningMeta"),
  );
  show("reasoningField", reasoningVisible);
  const temperature = $("temperature");
  temperature.max = ["anthropic", "claude_oauth"].includes(provider) ? "1" : "2";
  temperature.disabled = provider === "chatgpt" || provider === "openai" && (!profile || !!profile.reasoning) || ["anthropic", "claude_oauth"].includes(provider) && profile?.temperature?.supported !== true;
  // 停用采样控制时恢复可持久化的默认值；供应商切换不会遗留无法编辑的超界配置。
  if (temperature.disabled) temperature.value = "0";
  $("temperatureMeta").textContent = temperature.disabled ? "当前适配器使用模型默认采样。" : `0–${temperature.max} · 越低越稳定，越高越多样。`;
  const facts = [];
  if (profile?.context_window) facts.push(`Context ${Number(profile.context_window).toLocaleString()} tokens`);
  if (profile?.max_output_tokens) {
    facts.push(`Max output ${Number(profile.max_output_tokens).toLocaleString()}`);
    $("maxTokens").max = String(Math.min(393216, profile.max_output_tokens, Number($("maxTokens").dataset.catalogMax) || 393216));
  } else {
    $("maxTokens").max = String(Math.min(393216, Number($("maxTokens").dataset.catalogMax) || 393216));
  }
  if (profile?.input_modalities?.length) facts.push(`Input ${profile.input_modalities.join(" + ")}`);
  const capabilityMeta = $("modelCapabilityMeta");
  capabilityMeta.replaceChildren();
  if (facts.length) capabilityMeta.append(document.createTextNode(facts.join(" · ")));
  const providerMetadata = profile?.provider_metadata;
  if (providerMetadata && Object.keys(providerMetadata).length) {
    const details = document.createElement("details");
    details.className = "model-provider-details";
    const summary = document.createElement("summary");
    summary.textContent = "Provider 模型详情";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(providerMetadata, null, 2);
    details.append(summary, pre);
    capabilityMeta.append(details);
  }
  show(
    "modelCapabilityMeta",
    facts.length > 0 || !!(providerMetadata && Object.keys(providerMetadata).length),
  );
  window.MythChoices?.sync();
}
// Control 面板复用同一 capability 目录，但保持当前 Run 已保存的原生值可见。
function renderTurnReasoning(turn, current) {
  const model = $("turnModelInput").value.trim() || turn?.settings?.model || "";
  const profile = modelCapability(model);
  const visible = fillReasoningSelect(
    $("turnThinkingInput"),
    profile,
    current,
    $("turnThinkingMeta"),
  );
  show("turnThinkingField", visible || current !== null && current !== undefined);
}

// 从表单收集非秘钥模型配置；服务端校验并固定到未来 Turn。
function settingsPayload() {
  return {
    provider: $("provider").value,
    model: $("model").value.trim(),
    ollama_url: $("ollamaUrl").value.trim(),
    max_steps: Number($("maxSteps").value),
    max_output_tokens: Number($("maxTokens").value),
    num_ctx: Number($("numCtx").value),
    temperature: Number($("temperature").value),
    thinking: reasoningSelectionValue(),
    model_pool: typeof modelPoolPayload === "function" ? modelPoolPayload() : {children: []},
  };
}
// 回填保存设置及认证展示；不会改变在途请求的配置。
function loadSettings() {
  const s = state.data.settings;
  $("provider").value = s.provider;
  $("model").value = s.model;
  $("ollamaUrl").value = s.ollama_url;
  $("maxSteps").value = s.max_steps;
  $("maxTokens").value = s.max_output_tokens;
  $("numCtx").value = s.num_ctx ?? 8192;
  $("temperature").value = s.temperature ?? 0;
  if (typeof loadModelPool === "function") loadModelPool(s.model_pool);
  renderChatGPTAuth();
  renderClaudeAuth();
  renderProviderKeyAuth();
  renderAdaptiveModelSettings({thinking: s.thinking});
  poolRefreshPrices();
  window.MythChoices?.sync();
}
// 仅展示公开账号/scope 状态；身份已连接与 plan usage 已授权分开。
function renderChatGPTAuth() {
  const panel = $("chatgptAuthPanel");
  if (!panel) return;
  const enabled = $("provider").value === "chatgpt";
  show("chatgptAuthPanel", enabled);
  if (!enabled) return;
  const s = state.chatgptAuth?.status;
  if (!s) {
    $("chatgptAuthState").textContent = "检查 ChatGPT 连接…";
    $("chatgptAuthMeta").textContent =
      "OAuth 凭据由 Myth 保存到系统安全凭据库。";
    show("chatgptLogout", false);
    return;
  }
  if (s.connected) {
    $("chatgptAuthState").textContent = s.email || s.name || "ChatGPT 已连接";
    $("chatgptAuthMeta").textContent = s.sharing
      ? "ChatGPT plan usage 已授权 · 凭据不进入 Runtime 数据库"
      : "身份已连接，但尚未授权 ChatGPT plan usage";
    show("chatgptLogout", true);
    $("chatgptLogin").textContent = s.sharing
      ? "重新授权"
      : "启用 ChatGPT plan";
  } else {
    $("chatgptAuthState").textContent = "未连接 ChatGPT";
    $("chatgptAuthMeta").textContent =
      s.reason === "not_signed_in"
        ? "使用 ChatGPT 登录，凭据保存在系统安全凭据库。"
        : s.reason || "需要登录";
    show("chatgptLogout", false);
    $("chatgptLogin").textContent = "使用 ChatGPT 登录";
  }
}
// 渲染 OpenAI / DeepSeek 的应用内 API Key 连接；Provider 特有认证不污染通用模型表单。
function renderProviderKeyAuth() {
  const provider = $("provider").value;
  const enabled = ["openai", "deepseek", "anthropic", "kimi"].includes(provider);
  show("providerKeyPanel", enabled);
  if (!enabled) return;
  const status = (state.providerKeys?.providers || []).find(
    (item) => item.provider === provider,
  );
  const label = status?.label || ({openai: "OpenAI", deepseek: "DeepSeek", anthropic: "Claude", kimi: "Kimi"}[provider] || provider);
  if (status?.configured) {
    $("providerKeyState").textContent = `${label} 已连接`;
    $("providerKeyMeta").textContent =
      status.source === "myth"
        ? "凭据保存在操作系统安全凭据库 · 不进入 Runtime 数据库"
        : "检测到旧环境配置 · 可直接使用，也可在 Myth 内重新连接";
    show("providerKeyDisconnect", status.source === "myth");
    $("providerKeyConnect").textContent =
      status.source === "myth" ? "替换 API Key" : "改为 Myth 安全连接";
  } else {
    $("providerKeyState").textContent = `连接 ${label}`;
    $("providerKeyMeta").textContent =
      "粘贴一次 API Key 即可。Myth 会保存到操作系统安全凭据库。";
    show("providerKeyDisconnect", false);
    $("providerKeyConnect").textContent = "连接";
  }
}
// 刷新 API Key Provider 的脱敏状态；失败只影响设置提示，不把未知状态伪装成未连接。
async function refreshProviderKeys() {
  try {
    state.providerKeys = await providerAuthApi("/status");
  } catch (e) {
    state.providerKeys = { providers: [], error: e.message };
  }
  renderProviderKeyAuth();
}
// 读取脱敏认证状态；错误保留为页面提示，不伪造 ready。
async function refreshChatGPTAuth() {
  try {
    state.chatgptAuth = await authApi("/status");
    renderChatGPTAuth();
  } catch (e) {
    state.chatgptAuth = {
      status: { connected: false, sharing: false, reason: e.message },
    };
    renderChatGPTAuth();
  }
}
// 按明确点击创建登录挑战并打开授权入口；轮询只等待完成状态，凭据保存在系统库。
async function beginChatGPTLogin() {
  let popup = null;
  try {
    popup = window.open(
      "about:blank",
      "myth-chatgpt-oauth",
      "width=640,height=760",
    );
    const profileId = state.chatgptAuth?.status?.profile_id || null;
    const attempt = await authApi("/start", { profile_id: profileId });
    if (!popup) throw new Error("浏览器阻止了登录窗口，请允许弹窗后重试。");
    // 授权页来自另一源，先断开 opener，避免其导航/操纵本机工作台。
    popup.opener = null;
    popup.location = attempt.auth_url;
    for (let i = 0; i < 180; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      await refreshChatGPTAuth();
      if (state.chatgptAuth?.status?.login_revision === attempt.login_id) {
        try {
          popup.close();
        } catch {}
        await checkConnection(true);
        toast(
          state.chatgptAuth.status.sharing
            ? "ChatGPT 已连接。"
            : "ChatGPT 身份已连接，但 plan usage 未授权。",
        );
        return;
      }
      if (popup.closed && i > 2) break;
    }
    throw new Error("ChatGPT 登录未完成。");
  } catch (e) {
    try {
      popup?.close();
    } catch {}
    toast(e.message);
  }
}
// Claude OAuth 只在独立 Provider 身份下显示；API Key 的 anthropic 路径保持原样。
function renderClaudeAuth() {
  const panel = $("claudeAuthPanel");
  if (!panel) return;
  const enabled = $("provider").value === "claude_oauth";
  show("claudeAuthPanel", enabled);
  if (!enabled) return;
  const s = state.claudeAuth?.status;
  if (!s) {
    $("claudeAuthState").textContent = "检查 Claude OAuth…";
    $("claudeAuthMeta").textContent = "OAuth token 只保存到系统安全凭据库。";
    show("claudeLogout", false);
    return;
  }
  if (s.connected) {
    $("claudeAuthState").textContent = s.email || "Claude 已连接";
    const scope = (s.scopes || []).join(" · ");
    $("claudeAuthMeta").textContent =
      [s.organization, s.workspace, scope].filter(Boolean).join(" · ") ||
      "Claude OAuth 已连接 · token 不进入 Runtime 数据库";
    show("claudeLogout", true);
    $("claudeLogin").textContent = "重新授权";
  } else {
    $("claudeAuthState").textContent =
      s.client_id_configured ? "Claude OAuth 未登录" : "先配置 Myth OAuth Client ID";
    $("claudeAuthMeta").textContent =
      s.client_id_configured
        ? "使用 Claude/Anthropic 账号授权 user:inference。"
        : "Client ID 是公开配置；不要粘贴 client secret 或其他应用的 token。";
    show("claudeLogout", false);
    $("claudeLogin").textContent = "连接 Claude";
  }
}

async function refreshClaudeAuth() {
  try {
    state.claudeAuth = await claudeAuthApi("/status");
  } catch (e) {
    state.claudeAuth = {status: {connected: false, client_id_configured: false, reason: e.message}};
  }
  renderClaudeAuth();
}

async function beginClaudeLogin() {
  let popup = null;
  try {
    popup = window.open("about:blank", "myth-claude-oauth", "width=640,height=760");
    const attempt = await claudeAuthApi("/start", {});
    if (!popup) throw new Error("浏览器阻止了登录窗口，请允许弹窗后重试。");
    popup.opener = null;
    popup.location = attempt.auth_url;
    for (let i = 0; i < 180; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      await refreshClaudeAuth();
      if (state.claudeAuth?.status?.login_revision === attempt.login_id) {
        try { popup.close(); } catch {}
        await checkConnection(true);
        toast("Claude OAuth 已连接。");
        return;
      }
      if (popup.closed && i > 2) break;
    }
    throw new Error("Claude 登录未完成。");
  } catch (e) {
    try { popup?.close(); } catch {}
    toast(e.message);
  }
}

// 呈现当前检查报告；连接 ready 不能当作某个任务已完成。
function renderConnection() {
  const c = state.connectionKey === connectionConfigKey(settingsPayload()) ? state.connection : null;
  const savedConnection = state.connectionKey === connectionConfigKey(state.data.settings) ? state.connection : null;
  $("connectionDot").className =
    "connection-dot " + (savedConnection ? (savedConnection.ready ? "connected" : "disconnected") : "");
  const activeModel = state.session?.turns?.at(-1)?.settings?.model;
  const provider = state.data.settings.provider;
  $("modelLabel").textContent =
    activeModel ||
    state.data.settings.model ||
    (provider === "ollama"
      ? "连接 Ollama"
      : provider === "chatgpt"
        ? "连接 ChatGPT"
        : provider === "claude_oauth"
          ? "连接 Claude"
          : provider === "deepseek"
            ? "连接 DeepSeek"
            : "连接模型");
  $("modelPill").setAttribute("aria-label", $("modelLabel").textContent + "，打开模型设置或运行控制");
  $("modelPill").title = $("modelLabel").textContent;
  show("welcomeConnection", !state.data.settings.model || (savedConnection && !savedConnection.ready));
  $("connectionResult").textContent = "";
  $("connectionResult").className = "connection-result";
  $("modelOptions").replaceChildren();
  if (c) {
    const fallback =
      $("provider").value === "ollama"
        ? "未连接，请确认 Ollama 正在运行。"
        : $("provider").value === "chatgpt"
          ? "ChatGPT 尚未完成授权或当前计划不可用。"
          : $("provider").value === "claude_oauth"
            ? "Claude OAuth 尚未连接或 user:inference 不可用。"
          : $("provider").value === "deepseek"
            ? "DeepSeek 尚未就绪，请在 Myth 内连接 API Key。"
            : $("provider").value === "openai"
              ? "OpenAI 尚未就绪，请在 Myth 内连接 API Key。"
              : "模型提供方尚未就绪。";
    $("connectionResult").textContent = c.ready
      ? `已连接 · ${c.details.models?.length || 0} 个可用模型`
      : c.details.error || c.details.reason || fallback;
    $("connectionResult").className =
      "connection-result" + (c.ready ? "" : " bad");
    (c.details.models || []).forEach((m) => {
      const o = el("option");
      o.value = m;
      $("modelOptions").append(o);
    });
  }
  renderAdaptiveModelSettings();
}
// 模型目录由供应商和端点定义；模型选择和采样参数不改变目录身份。
function connectionConfigKey(value) {
  return JSON.stringify([value.provider, value.provider === "ollama" ? value.ollama_url : null]);
}
// 表单切换使旧检查失效，清理公开目录；不改写已保存设置或在途 Turn。
function invalidateConnection() {
  ++state.connectionGeneration;
  state.connection = null;
  state.connectionKey = null;
  $("checkConnection").disabled = false;
  $("checkConnection").textContent = "检查连接";
  $("settingsSaved").textContent = "";
  renderConnection();
}
// 提交明确当前配置做连接检查；模型列表只是可用目录，保存设置后影响未来工作。
async function checkConnection(auto = false) {
  const generation = ++state.connectionGeneration;
  const payload = {...(auto ? state.data.settings : settingsPayload())};
  const key = connectionConfigKey(payload);
  $("checkConnection").disabled = true;
  $("checkConnection").textContent = "正在检查…";
  try {
    const result = await api("/connection", payload);
    if (generation !== state.connectionGeneration || connectionConfigKey(settingsPayload()) !== key) return;
    state.connection = result;
    state.connectionKey = key;
    if (
      auto &&
      !payload.model &&
      state.connection.ready &&
      state.connection.details.models?.[0]
    ) {
      payload.model = state.connection.details.models[0];
      state.data.settings = await api("/settings", payload);
      loadSettings();
    } else if (
      !auto &&
      !$("model").value &&
      state.connection.details.models?.[0]
    )
      $("model").value = state.connection.details.models[0];
    renderConnection();
  } catch (e) {
    if (generation === state.connectionGeneration) toast(e.message);
  } finally {
    if (generation === state.connectionGeneration) {
      $("checkConnection").disabled = false;
      $("checkConnection").textContent = "检查连接";
    }
  }
}
// 准备新对话展示并可固定项目；实际会话/Turn 由发送入口创建。
async function newChat(projectId = null) {
  if (!state.data) return;
  if (state.page === "chat") saveDraft();
  ++state.generation;
  // 新建是显式清空独立草稿的操作；已有会话的草稿仍按原身份保留。
  state.drafts.set("new", { text: "", attached: [], projectId: projectId || "", goalId: "", pending: null });
  state.session = null;
  state.loadingSession = false;
  state.id = null;
  state.threadKey = "";
  restoreDraft("new");
  go("chat");
  renderChat(null);
  $("prompt").focus();
}

// 只有编辑器拥有草稿；服务端会话、Run 与收据从不由草稿回写。
function saveDraft() {
  const key = state.composerKey;
  const draft = state.drafts.get(key) || {};
  Object.assign(draft, {
    text: $("prompt").value,
    attached: [...state.attached],
    projectId: $("chatProject").value,
    goalId: $("chatGoal")?.value || "",
    pending: state.pending,
  });
  state.drafts.set(key, draft);
  return draft;
}
// 把输入所有权切到指定会话，连同附件、Goal 和稳定请求身份还原其草稿。
function restoreDraft(key) {
  state.composerKey = key;
  const draft = state.drafts.get(key) || { text: "", attached: [], projectId: "", goalId: "", pending: null };
  state.drafts.set(key, draft);
  $("prompt").value = draft.text;
  state.attached = [...draft.attached];
  state.pending = draft.pending;
  fillProjects($("chatProject"), "独立对话", draft.projectId);
  fillGoals($("chatGoal"), draft.goalId);
  renderAttachments();
  updateComposer();
}
// 判断当前输入是否可发；UNKNOWN 和中断恢复仍由控制入口处理，不准入新 Run。
function composerCanSend() {
  const status = state.session?.turns.at(-1)?.status;
  return state.page === "chat" && !!state.data && !state.busy && !state.loadingSession &&
    !state.composing && !!$("prompt").value.trim() &&
    !["RUNNING", "INTERRUPTED", "UNKNOWN", "PAUSED"].includes(status);
}
// 高度、可发送状态和草稿是同一输入事件的投影，程序回填也调用此入口。
function updateComposer() {
  const prompt = $("prompt");
  prompt.style.height = "auto";
  prompt.style.height = Math.min(Math.max(prompt.scrollHeight, 52), 220) + "px";
  prompt.style.overflowY = prompt.scrollHeight > 220 ? "auto" : "hidden";
  $("send").disabled = !composerCanSend();
  $("composer").setAttribute("aria-busy", String(state.busy));
  $("attachButton").disabled = state.busy;
}

// 原生 dialog 提供焦点圈定；记录打开入口，让关闭后的键盘焦点回到原位置。
function openDialog(id, focusId) {
  closeNavigation();
  state.closeRuntimeDrawer?.();
  const dialog = $(id);
  if (dialog.open) return;
  dialog._returnFocus = document.activeElement;
  dialog.showModal();
  const target = focusId ? $(focusId) : dialog.querySelector("[autofocus], input:not([type=checkbox]), textarea, button");
  target?.focus();
}

// 剪贴板成功才反馈复制完成，权限失败保留正文供用户手动选择。
async function copyText(text, button, success) {
  const previous = button.textContent;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "已复制";
    toast(success);
    setTimeout(() => { if (button.isConnected) button.textContent = previous; }, 1800);
  } catch (_) { toast("浏览器未允许剪贴板访问，请手动选择并复制。"); }
}
// 只在用户离开最新消息时提供定位入口；滚动位置不影响后台执行。
function updateScrollButton() {
  const button = $("scrollToBottom");
  if (!button) return;
  const scroll = $("chatScroll");
  button.classList.toggle("hidden", state.page !== "chat" || !state.session?.messages.length ||
    scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 180);
}

// 命令面板只打开已有功能；执行和授权仍使用原入口。
let commandItems = [];
let selectedCommand = 0;
// 命令目录只引用已有操作和公开对象身份，不从标题解释代码或扩大权限。
function availableCommands() {
  const commands = [
    { label: "新建对话", detail: "开始一个独立会话", icon: "plus", shortcut: "Ctrl Shift O", action: () => newChat() },
    { label: "会话", detail: "查看与管理所有会话", icon: "history", action: () => go("sessions") },
    { label: "项目", detail: "文件、资料与项目会话", icon: "folder", action: () => go("projects") },
    { label: "知识库", detail: "导入与检索资料", icon: "book", action: () => go("knowledge") },
    { label: "目标与计划", detail: "查看 Goal 与执行计划", icon: "spark", action: () => go("goals") },
    { label: "Runtime", detail: "架构与能力", icon: "code", action: () => go("runtime") },
    { label: "模型与设置", detail: "模型连接与界面偏好", icon: "settings", action: () => go("settings") },
  ];
  (state.data?.sessions || []).forEach((session) => commands.push({
    label: session.title, detail: session.project_name ? "会话 · " + session.project_name : "会话", icon: "chat", action: () => go("chat", session.id),
  }));
  (state.data?.projects || []).forEach((project) => commands.push({
    label: project.name, detail: "项目", icon: "folder", action: () => go("projects", project.id),
  }));
  return commands;
}
// 选中位置只属于命令面板，键盘焦点固定在输入框并通过 ARIA 指向结果。
function selectCommand(index) {
  selectedCommand = Math.max(0, Math.min(index, commandItems.length - 1));
  [...$("commandResults").children].forEach((node, i) => {
    node.classList.toggle("selected", i === selectedCommand);
    node.setAttribute("aria-selected", String(i === selectedCommand));
  });
  const selected = $("commandResults").children[selectedCommand];
  if (selected && commandItems.length) {
    $("commandSearch").setAttribute("aria-activedescendant", selected.id);
    selected.scrollIntoView({ block: "nearest" });
  } else $("commandSearch").removeAttribute("aria-activedescendant");
}
// 关闭面板后调用显式选中的已有入口，业务写入仍由对应服务校验。
function runCommand(index) {
  const command = commandItems[index];
  if (!command) return;
  $("commandPalette").close();
  Promise.resolve(command.action()).catch((e) => toast(e.message));
}
// 按安全文本过滤公开名称，有限结果保持键盘可达，空结果不创建占位操作。
function renderCommands() {
  const query = $("commandSearch").value.trim().toLocaleLowerCase();
  commandItems = availableCommands().filter((item) =>
    (item.label + " " + item.detail).toLocaleLowerCase().includes(query),
  ).slice(0, 14);
  const box = $("commandResults");
  box.replaceChildren();
  commandItems.forEach((item, index) => {
    const button = el("button", "command-item");
    button.type = "button";
    button.id = "command-option-" + index;
    button.tabIndex = -1;
    button.setAttribute("role", "option");
    const main = el("span", "command-item-main");
    main.append(el("strong", "", item.label), el("small", "", item.detail));
    button.append(icon(item.icon), main);
    if (item.shortcut) button.append(el("kbd", "command-key", item.shortcut));
    button.onclick = () => runCommand(index);
    button.onpointermove = () => selectCommand(index);
    box.append(button);
  });
  if (!commandItems.length) box.append(el("p", "command-empty", "没有匹配的命令、会话或项目"));
  selectCommand(0);
}
// 快捷搜索不覆盖已打开的业务表单，避免失去当前编辑的保护焦点。
function openCommandPalette() {
  if (!$("commandPalette") || !state.data || document.querySelector("dialog[open]")) return;
  $("commandSearch").value = "";
  renderCommands();
  openDialog("commandPalette", "commandSearch");
}

// 解析有限行内格式并以 DOM 安全输出；禁止资料文本成为任意 HTML。
function inline(parent, text) {
  const pattern = /(\*\*([^*]+)\*\*|`([^`]+)`|\[doc:([^\]]+)\])/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    parent.append(document.createTextNode(text.slice(last, match.index)));
    if (match[2]) parent.append(el("strong", "", match[2]));
    else if (match[3]) parent.append(el("code", "", match[3]));
    else {
      const citation = "doc:" + match[4];
      const allSources =
        state.session?.turns.flatMap((t) => [
          ...t.snapshot.knowledge,
          ...t.activities.flatMap((s) => s.result?.sources || []),
        ]) || [];
      const source = allSources.find((s) => s.citation === citation);
      const b = el("button", "source-chip", source ? source.title : "资料引用");
      b.onclick = () =>
        source
          ? previewDocument(source.document_id)
          : toast("这个引用未匹配到本轮检索来源。");
      parent.append(b);
    }
    last = match.index + match[0].length;
  }
  parent.append(document.createTextNode(text.slice(last)));
}
// 渲染有限 Markdown 子集；代码块/正文均按文本处理，外链按允许协议建立。
function markdown(parent, text) {
  const pieces = text.split(/```/);
  pieces.forEach((part, i) => {
    if (i % 2) {
      const newline = part.indexOf("\n");
      const language = newline >= 0 ? part.slice(0, newline).trim() || "代码" : "代码";
      const code = newline >= 0 ? part.slice(newline + 1) : part;
      const block = el("div", "code-block"),
        head = el("div", "code-head"),
        copy = el("button", "code-copy", "复制");
      copy.type = "button";
      copy.setAttribute("aria-label", "复制代码");
      copy.onclick = () => copyText(code, copy, "已复制代码");
      head.append(el("span", "", language), copy);
      block.append(head, el("pre", "", code));
      parent.append(block);
    } else {
      let paragraph = [];
      function flush() {
        if (paragraph.length) {
          const p = el("p");
          inline(p, paragraph.join("\n"));
          p.style.whiteSpace = "pre-wrap";
          parent.append(p);
          paragraph = [];
        }
      }
      for (const line of part.split("\n")) {
        if (!line.trim()) {
          flush();
          continue;
        }
        const heading = line.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
          flush();
          const h = el(heading[1].length <= 2 ? "h2" : "h3");
          inline(h, heading[2]);
          parent.append(h);
        } else if (/^[-*]\s+/.test(line)) {
          flush();
          const p = el("p");
          inline(p, "• " + line.slice(2));
          parent.append(p);
        } else paragraph.push(line);
      }
      flush();
    }
  });
}
// 能力身份到产品文案的映射；不改变服务器能力合同。
const toolLabels = {
  "knowledge.search": "检索资料",
  "project.list": "浏览项目文件",
  "project.read": "读取项目文件",
  "project.search": "搜索项目",
  "diff.preview": "预览 Diff",
  "git.status": "Git 状态",
  "git.diff": "Git Diff",
  "artifact.write": "生成文件",
  "project.patch_exact": "修改文件副本",
  "math.calculate": "计算",
};
// 将服务端 wall-clock 秒数格式化为回复旁的紧凑“用时”；这是整轮处理时间，不冒充纯模型推理时延。
function workedTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds || 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return `用时 ${hours}小时 ${minutes}分 ${secs}秒`;
  if (minutes) return `用时 ${minutes}分 ${secs}秒`;
  return `用时 ${secs}秒`;
}

// 以持久 activities 投影工具过程；折叠 UI 不删除收据或原始结果。
function toolGroup(turn) {
  const steps = turn.activities.filter(
    (s) => s.decision?.decision_type === "tool_call" || s.result?.error,
  );
  if (!steps.length) return null;
  const details = el("details", "tool-group");
  details.dataset.turn = turn.run_id;
  const summary = el("summary");
  summary.append(
    icon("spark"),
    el("span", "", `已处理 ${steps.length} 个步骤`),
  );
  details.append(summary);
  steps.forEach((s) => {
    const item = el("div", "tool-item");
    const cap = s.decision?.capability_id;
    item.append(
      el(
        "strong",
        "",
        `${s.step.toString().padStart(2, "0")}  ${toolLabels[cap] || "步骤"} · ${s.state === "DONE" ? "已记录" : "处理中"}`,
      ),
    );
    const r = s.result;
    if (r) {
      const text =
        r.error ||
        r.content ||
        r.diff ||
        r.output ||
        r.artifact?.name ||
        (r.value !== undefined
          ? String(r.value)
          : r.sources?.map((x) => x.title).join(" · ")) ||
        r.matches
          ?.map((x) => x.path + ":" + x.line + " " + x.preview)
          .join("\n") ||
        r.files?.map((x) => x.path).join("\n") ||
        "";
      if (text) item.append(el("pre", "", text.slice(0, 3000)));
    }
    details.append(item);
  });
  return details;
}
// 建立固定产物下载卡；实际下载必须由服务器校验对象身份。
function artifactCard(artifact) {
  const a = el("a", "artifact-card");
  a.href = `/api/workspace/artifacts/${encodeURIComponent(artifact.decision_id)}`;
  a.download = artifact.name.split("/").at(-1);
  const mark = el("span", "artifact-icon");
  mark.append(icon("file"));
  const info = el("div");
  info.append(
    el("strong", "", artifact.name),
    el(
      "small",
      "",
      `${bytes(artifact.bytes)} · 文件副本 · 版本 ${artifact.version || 1}`,
    ),
  );
  const download = el("span", "download", "下载");
  download.append(icon("download"));
  a.append(mark, info, download);
  return a;
}
// 持久事实不变时只更新执行中的时钟，不能用心跳重建历史消息打断阅读与选择。
function liveTurnLabel(turn) {
  if (!turn.driver_active) return "Driver 已断开，等待恢复";
  const elapsed = turn.reply_timing?.elapsed_seconds;
  return "正在处理…" + (typeof elapsed === "number" && Number.isFinite(elapsed) && elapsed >= 0 ? " · " + workedTime(elapsed) : "");
}
// 按消息/步骤签名增量重建讨论与工具展示；滚动位置只属于本地视图。
function renderThread(session) {
  const signature = JSON.stringify([
    session.messages,
    session.turns.map((t) => [
      t.run_id,
      t.status,
      t.current_step,
      t.activities,
      t.driver_active,
      t.status === "RUNNING" ? null : t.reply_timing,
    ]),
    session.artifacts,
  ]);
  if (signature === state.threadKey) {
    const label = $("thread").querySelector("[data-live-run]");
    const turn = session.turns.at(-1);
    if (label && label.dataset.liveRun === turn?.run_id) label.textContent = liveTurnLabel(turn);
    return;
  }
  state.threadKey = signature;
  const scroll = $("chatScroll");
  const nearBottom =
    scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 100;
  const expanded = new Set(
    [...$("thread").querySelectorAll("details[open]")].map(
      (d) => d.dataset.turn,
    ),
  );
  $("thread").replaceChildren();
  const groups = new Set(),
    emitted = new Set();
  session.messages.forEach((message) => {
    const turn = session.turns.find((t) => t.run_id === message.run_id);
    if (message.role === "assistant" && turn && !groups.has(turn.run_id)) {
      groups.add(turn.run_id);
      const group = toolGroup(turn);
      if (group) {
        group.open = expanded.has(turn.run_id);
        $("thread").append(group);
      }
    }
    const row = el("article", "message " + message.role);
    row.dataset.messageId = message.id;
    if (message.role === "assistant") {
      const avatar = el("div", "message-avatar");
      avatar.append(icon("spark"));
      row.append(avatar);
    }
    const main = el("div", "message-main"),
      body = el("div", "message-content");
    main.append(el("div", "message-label", message.role === "user" ? "你" : "Myth"));
    if (message.role === "user") body.textContent = message.content;
    else markdown(body, message.content);
    main.append(body);
    if (message.role === "assistant") {
      const actions = el("div", "message-actions"),
        copy = el("button", "", "复制"),
        save = el("a", "", "保存 Markdown");
      copy.type = "button";
      copy.onclick = () => copyText(message.content, copy, "已复制回答");
      save.href = `/api/workspace/messages/${encodeURIComponent(message.id)}/download`;
      save.download = "myth-answer.md";
      const elapsed = message.metadata?.reply_elapsed_seconds;
      if (elapsed !== undefined && elapsed !== null) {
        const worked = el("span", "message-worked", workedTime(elapsed));
        worked.title =
          "从本轮用户输入持久化到这条回复落库的总 wall-clock 时间，不是纯模型推理时延。";
        actions.prepend(worked);
      }
      actions.append(copy, save);
      main.append(actions);
    }
    if (message.role === "assistant" && turn) {
      const sources = [
        ...turn.snapshot.knowledge,
        ...turn.activities.flatMap((s) => s.result?.sources || []),
      ];
      if (sources.length) {
        const list = el("div", "source-list");
        const seen = new Set();
        sources.forEach((source) => {
          if (seen.has(source.document_id)) return;
          seen.add(source.document_id);
          const b = el("button", "", source.title);
          b.prepend(icon("book"));
          b.onclick = () => previewDocument(source.document_id);
          list.append(b);
        });
        main.append(list);
      }
    }
    row.append(main);
    $("thread").append(row);
    if (message.role === "assistant" && turn)
      session.artifacts
        .filter((a) => a.run_id === turn.run_id && !emitted.has(a.decision_id))
        .forEach((a) => {
          emitted.add(a.decision_id);
          $("thread").append(artifactCard(a));
        });
  });
  session.artifacts
    .filter((a) => !emitted.has(a.decision_id))
    .forEach((a) => $("thread").append(artifactCard(a)));
  const last = session.turns.at(-1);
  if (last && last.status === "RUNNING") {
    if (!groups.has(last.run_id)) {
      const group = toolGroup(last);
      if (group) {
        group.open = expanded.has(last.run_id);
        $("thread").append(group);
      }
    }
    const typing = el("div", "typing");
    // 动态点仅对应在线 Driver；断连保持静态说明，不伪装任务继续推进。
    if (last.driver_active) typing.append(taijiMark(true));
    const label = el("span", "", liveTurnLabel(last));
    label.dataset.liveRun = last.run_id;
    typing.append(label);
    $("thread").append(typing);
  }
  if (nearBottom || state.justSent) {
    scroll.scrollTop = scroll.scrollHeight;
    state.justSent = false;
  }
  updateScrollButton();
}
// 按最新 Turn/Control/Lease 决定按钮和恢复说明；UNKNOWN 需核对，Pause 不假装物理取消。
function renderChat(session) {
  show("welcome", !session || !session.messages.length);
  show("thread", !!session?.messages.length);
  show("sessionMenu", !!session);
  $("pageTitle").textContent = session?.title || "对话";
  fillProjects(
    $("chatProject"),
    "独立对话",
    session?.project_id || $("chatProject").value,
  );
  $("chatProject").disabled = !!session;
  const turn = session?.turns.at(-1);
  const status = turn?.status;
  const active =
    turn &&
    ["RUNNING", "INTERRUPTED", "UNKNOWN", "WAITING_USER", "PAUSED"].includes(
      status,
    );
  const boundGoal = turn?.snapshot?.goal?.goal_id || $("chatGoal")?.value || "";
  fillGoals($("chatGoal"), boundGoal);
  if ($("chatGoal")) $("chatGoal").disabled = !!active;
  renderAttachments();
  if (session) renderThread(session);
  window.MythStudio?.sync(session, state.page, state.id);
  // 同一次已读取投影同步中央与观测栏，避免新 Run 已在等待而右栏仍显示上轮空闲。
  if (typeof renderRuntimeInspector === "function") renderRuntimeInspector(session);

  const control = turn?.control || {};
  show(
    "turnControls",
    !!turn &&
      ["RUNNING", "INTERRUPTED", "UNKNOWN", "WAITING_USER", "PAUSED"].includes(
        status,
      ),
  );
  show(
    "pauseTurn",
    !!turn &&
      !control.paused &&
      !control.stopped &&
      ["RUNNING", "INTERRUPTED"].includes(status),
  );
  show("resumeTurn", !!turn && control.paused && status === "PAUSED");
  $("steerTurn").disabled =
    !turn ||
    control.stopped ||
    ["COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"].includes(status);
  $("compactTurn").disabled =
    !turn || control.stopped || status !== "RUNNING";
  $("stopRun").disabled =
    !turn ||
    control.stopped ||
    ["COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"].includes(status);

  show("stopTurn", !!active && !control.stopped);
  show("send", !active || status === "WAITING_USER");
  updateComposer();
  $("prompt").placeholder =
    status === "WAITING_USER"
      ? "回复这个问题…"
      : status === "PAUSED"
        ? "Run 已暂停，恢复后继续"
        : status === "INTERRUPTED"
          ? turn.network_retry ? "连接中断，正在重连；任务已保存" : "Run 已中断，请从断点继续"
          : "输入消息…";

  if (turn?.settings?.model) {
    $("modelLabel").textContent = turn.settings.model;
    $("modelPill").setAttribute("aria-label", turn.settings.model + "，打开模型设置或运行控制");
    $("modelPill").title = turn.settings.model;
  }
  $("turnNotice").replaceChildren();
  show("turnNotice", false);
  if (turn) {
    const detached = status === "RUNNING" && !turn.driver_active;
    const lease = turn.driver_lease;
    const leaseRemaining =
      lease && !lease.expired
        ? Math.max(
            0,
            Math.ceil(Number(lease.lease_until || 0) - Date.now() / 1000),
          )
        : 0;
    const text =
      turn.network_retry && status === "INTERRUPTED"
        ? "连接中断，" + Math.max(0, Math.ceil(turn.network_retry.retry_at - Date.now() / 1000)) + " 秒后自动重试；已完成步骤保留。"
        : status === "UNKNOWN"
        ? turn.error || "存在结果不明确的执行，必须先核对再继续。"
        : status === "INTERRUPTED"
          ? turn.error || "Driver 已中断；断点已保存，可以继续。"
          : status === "PAUSED"
            ? "Run 已暂停；已发出的调用仍会保留真实晚到结果。"
            : detached && leaseRemaining > 0
              ? "执行 Driver 已断开，等待租约过期后进入安全恢复状态（约 " +
                leaseRemaining +
                " 秒）。"
              : detached
                ? "执行 Driver 已断开；正在确认最后一个持久化断点。"
                : status === "WAITING_USER"
                  ? "Agent 需要你的答复，回答后继续这一轮。"
                  : turn.error;
    if (text) {
      show("turnNotice", true);
      $("turnNotice").className =
        "turn-notice" +
        (["FAILED", "UNKNOWN", "BUDGET_EXHAUSTED", "INTERRUPTED"].includes(
          status,
        )
          ? " error"
          : "");
      $("turnNotice").append(el("span", "", text));
      if (
        status === "UNKNOWN" ||
        status === "INTERRUPTED" ||
        (detached && leaseRemaining === 0)
      ) {
        const b = el(
          "button",
          "",
          status === "INTERRUPTED" ? "从断点继续" : "核对并继续",
        );
        b.onclick = () => controlTurn("continue");
        $("turnNotice").append(b);
      }
    }
  }
  renderConnection();
}
// 读取会话后核对 generation、页面和会话身份；迟到响应不能覆盖已切换页面。
async function openSession(sid, generation = state.generation) {
  const session = await api(`/sessions/${sid}`);
  if (
    // 页面已切换时放弃展示这条迟到响应；持久业务结果仍由服务端保存。
    generation !== state.generation ||
    state.page !== "chat" ||
    state.id !== sid
  )
    return;
  state.session = session;
  state.loadingSession = false;
  renderChat(session);
  renderSidebar();
}
// 显示本轮显式附加资料并允许移除；这只是未来发送选择，不倒写历史快照。
function renderAttachments() {
  $("attachmentChips").replaceChildren();
  state.attached.forEach((d, i) => {
    const chip = el("div", "attachment-chip");
    chip.append(icon("file"), el("span", "", d.title));
    const remove = el("button", "attachment-remove");
    remove.type = "button";
    remove.append(icon("close"));
    remove.setAttribute("aria-label", `移除 ${d.title}`);
    remove.onclick = () => {
      state.attached.splice(i, 1);
      saveDraft();
      renderAttachments();
    };
    chip.append(remove);
    $("attachmentChips").append(chip);
  });
}
// 冻结正文/附件/设置指纹并复用稳定 request_id；回答匹配 question_id，成功后才清本轮输入。
async function sendMessage(event) {
  event?.preventDefault();
  if (!composerCanSend()) return;
  const text = $("prompt").value.trim();
  const generation = state.generation,
    projectId = $("chatProject").value || null,
    goalId = $("chatGoal")?.value || null,
    attachments = [...state.attached],
    settings = { ...state.data.settings },
    draft = saveDraft();
  let draftKey = state.composerKey;
  let sid = state.id,
    session = state.session;
  state.busy = true;
  updateComposer();
  try {
    if (!settings.model) {
      go("settings");
      throw new Error("先检查模型连接并选择一个可用模型。");
    }
    if (!sid) {
      session = await api("/sessions", { project_id: projectId });
      sid = session.id;
      // 新会话身份得到服务端确认后迁移草稿；即使用户切页，失败重试仍绑定原会话。
      const ownsDraft = state.drafts.get(draftKey) === draft;
      if (ownsDraft) state.drafts.delete(draftKey);
      state.drafts.set(sid, draft);
      if (ownsDraft && state.composerKey === draftKey) state.composerKey = sid;
      draftKey = sid;
      if (state.generation === generation) {
        state.id = sid;
        state.session = session;
        history.replaceState(null, "", `#chat/${sid}`);
      }
    }
    const turn = session?.turns.at(-1);
    if (turn?.status === "WAITING_USER")
      await api(`/turns/${turn.run_id}/answer`, {
        text,
        question_id: turn.question_id,
      });
    else {
      const message = attachments.length
        ? text +
          "\n\n本轮附加资料：\n" +
          attachments.map((d) => `[doc:${d.id}:0] ${d.title}`).join("\n")
        : text;
      // 入口幂等身份固定到具体内容；同意图重试复用，不把网络超时当作未准入。
      const fingerprint = JSON.stringify([
        sid,
        message,
        attachments.map((d) => d.id),
        settings,
        goalId,
      ]);
      if (draft.pending?.fingerprint !== fingerprint)
        draft.pending = { fingerprint, id: crypto.randomUUID() };
      if (state.composerKey === draftKey) state.pending = draft.pending;
      const requestId = draft.pending.id;
      await api(`/sessions/${sid}/messages`, {
        text: message,
        request_id: requestId,
        document_ids: attachments.map((d) => d.id),
        goal_id: goalId,
      });
      if (draft.pending?.id === requestId) draft.pending = null;
      if (state.composerKey === draftKey) state.pending = draft.pending;
    }
    // 清除已经成功发送的内容；发送期间新增的正文或附件继续保留。
    if (draft.text.trim() === text) draft.text = "";
    const sentIds = new Set(attachments.map((d) => d.id));
    draft.attached = draft.attached.filter((d) => !sentIds.has(d.id));
    if (state.composerKey === draftKey) {
      if ($("prompt").value.trim() === text) $("prompt").value = "";
      state.attached = state.attached.filter((d) => !sentIds.has(d.id));
      saveDraft();
      renderAttachments();
      updateComposer();
    }
    await refresh();
    if (
      state.generation === generation &&
      state.page === "chat" &&
      state.id === sid
    ) {
      state.justSent = true;
      await openSession(sid, generation);
      renderAttachments();
    }
  } catch (e) {
    toast(e.message);
  } finally {
    state.busy = false;
    updateComposer();
  }
}
// 把明确用户控制交给当前 Run；后端按安全点生效，浏览器不直接修改执行事实。
async function controlTurn(action, payload = {}) {
  const turn = state.session?.turns.at(-1);
  if (!turn) return;
  try {
    await api(`/turns/${turn.run_id}/${action}`, payload);
    await openSession(state.id);
  } catch (e) {
    toast(e.message);
  }
}

// 回填当前控制 revision 及未来调用设置；提交不改写已签发模型请求。
function openControlDialog() {
  const turn = state.session?.turns.at(-1);
  if (!turn) return go("settings");
  const control = turn.control || {};
  $("steerInput").value = control.steering_note || "";
  $("turnModelInput").value = control.model || turn.settings?.model || "";
  const thinking =
    control.thinking !== undefined ? control.thinking : turn.settings?.thinking;
  renderTurnReasoning(turn, thinking);
  $("controlRevision").textContent =
    `control revision ${control.revision || 1}`;
  if (!$("controlDialog").open) openDialog("controlDialog", "steerInput");
}

// 渲染会话列表及恢复标记；归档改变导航可见性，执行控制另走 Control。
function renderSessions(list = state.data.sessions) {
  const query = $("sessionSearch").value.trim().toLowerCase();
  $("sessionCards").replaceChildren();
  const matches = (list || []).filter((s) =>
    (s.title + " " + (s.preview || "")).toLowerCase().includes(query),
  );
  if (!matches.length) {
    empty(
      $("sessionCards"),
      query ? "没有匹配的会话" : state.archived ? "暂无归档会话" : "暂无会话",
      query ? "试试其他关键词。" : "新建对话后，会话将自动保存。",
      "chat",
      query ? null : () => newChat(),
      "开始对话",
    );
    return;
  }
  matches.forEach((s) => {
    const card = el("div", "session-card"),
      mark = el("span", "session-icon");
    mark.append(icon("chat"));
    const info = el("a", "session-info");
    info.href = `#chat/${encodeURIComponent(s.id)}`;
    const title = el("strong", "", s.title);
    if (s.pinned) {
      const pin = icon("pin");
      pin.setAttribute("class", "icon pin");
      title.prepend(pin);
    }
    info.append(
      title,
      el("p", "", s.preview || "这个会话还没有消息。"),
    );
    const meta = el("div", "session-meta");
    if (s.project_name) meta.append(el("span", "tag", s.project_name));
    const recovery = (state.data.recoverable_runs || []).find(
      (r) =>
        r.session_id === s.id && ["INTERRUPTED", "UNKNOWN"].includes(r.status),
    );
    if (recovery)
      meta.append(
        el("span", "tag", recovery.status === "UNKNOWN" ? "需核对" : "可恢复"),
      );
    meta.append(el("span", "", date(s.updated_at)));
    const b = el("button", state.archived ? "text-button" : "icon-button");
    if (state.archived) {
      b.textContent = "恢复";
      b.onclick = async () => {
        b.disabled = true;
        try {
          await api(`/sessions/${s.id}`, { archived: false });
          await refresh();
          if (state.page === "sessions") await renderSessionPage();
          toast("会话已恢复");
        } catch (e) { toast(e.message); }
        finally { b.disabled = false; }
      };
    } else {
      b.append(icon("more"));
      b.setAttribute("aria-label", `编辑会话 ${s.title}`);
      b.onclick = () => editSession(s);
    }
    card.append(mark, info, meta, b);
    $("sessionCards").append(card);
  });
}
// 按明确归档筛选读取列表；不会因切换列表重新执行 Run。
async function renderSessionPage() {
  const generation = state.generation;
  const archived = state.archived;
  const list = state.archived
    ? (await api("/sessions?archived=1")).sessions
    : state.data.sessions;
  if (generation !== state.generation || archived !== state.archived) return;
  state.sessionList = list;
  $("activeSessions").classList.toggle("selected", !state.archived);
  $("archivedSessions").classList.toggle("selected", state.archived);
  $("activeSessions").setAttribute("aria-pressed", String(!state.archived));
  $("archivedSessions").setAttribute("aria-pressed", String(state.archived));
  renderSessions(list);
}
// 准备会话元数据和 Markdown 下载入口；提交逻辑仍由 API 校验。
function editSession(s) {
  state.editingSession = s;
  $("sessionExport").href =
    `/api/workspace/sessions/${encodeURIComponent(s.id)}/download`;
  $("sessionTitleInput").value = s.title;
  fillProjects($("sessionProjectInput"), "独立会话", s.project_id || "");
  $("sessionPinned").checked = !!s.pinned;
  $("archiveSession").textContent = s.archived ? "恢复会话" : "归档会话";
  openDialog("sessionDialog", "sessionTitleInput");
}
// 显示保存的项目与统计；项目根访问始终由服务端受限执行器负责。
function renderProjects() {
  $("projectCards").replaceChildren();
  if (!state.data.projects.length) {
    empty($("projectCards"), "暂无项目", "将会话、文件与资料归入同一项目。", "folder", () => projectDialog(), "新建项目");
    return;
  }
  state.data.projects.forEach((p) => {
    const a = el("a", "project-row");
    a.href = `#projects/${encodeURIComponent(p.id)}`;
    const mark = el("span", "project-card-icon");
    mark.append(icon("folder"));
    const main = el("div", "project-row-main");
    main.append(
      el("h2", "", p.name),
      el("p", "", p.description || "未添加描述"),
    );
    const foot = el("div", "project-row-meta");
    foot.append(
      el("span", "", `${p.session_count} 个会话`),
      el("span", "", `${p.document_count} 份资料`),
    );
    a.append(mark, main, foot, icon("right"));
    $("projectCards").append(a);
  });
}
// 回填项目描述/根目录/指令；这些信息由明确用户提交，不是模型自动授权。
function projectDialog(p = null) {
  state.editingProject = p;
  $("projectDialogTitle").textContent = p ? "编辑项目" : "新建项目";
  $("projectNameInput").value = p?.name || "";
  $("projectDescriptionInput").value = p?.description || "";
  $("projectRootInput").value = p?.root || "";
  $("projectRootInput").disabled = false;
  $("projectInstructionsInput").value = p?.instructions || "";
  openDialog("projectDialog", "projectNameInput");
}
// 连接项目详情、知识、会话与文件投影；不存在/归档身份显式失败。
async function renderProject(pid) {
  const project = state.data.projects.find((p) => p.id === pid);
  if (!project) throw new Error("项目不存在或已归档。");
  state.project = project;
  $("pageTitle").textContent = project.name;
  $("projectName").textContent = project.name;
  $("projectDescription").textContent =
    project.description || "未添加描述";
  $("projectInstructions").textContent =
    project.instructions ||
    "尚未添加指令。可以在编辑项目中约定回答风格与工作方式。";
  $("projectRoot").textContent =
    project.root || "未关联本地目录。仍可进行项目对话与知识检索。";
  const sessions = state.data.sessions.filter((s) => s.project_id === pid);
  $("projectSessionCount").textContent = sessions.length;
  $("projectSessions").replaceChildren();
  sessions.forEach((s) => {
    const a = el("a", "compact-row");
    a.href = `#chat/${s.id}`;
    a.append(
      icon("chat"),
      el("span", "", s.title),
      el("small", "", date(s.updated_at)),
    );
    $("projectSessions").append(a);
  });
  if (!sessions.length)
    $("projectSessions").append(
      el("p", "empty-inline", "开始第一段讨论，项目上下文会自动带入。"),
    );
  renderProjectDocuments(pid);
  await projectFiles(".");
}
// 用独立 filesGeneration 防止迟到目录响应串项目；点击文件只准备明确读取任务。
async function projectFiles(path) {
  const pid = state.project?.id;
  if (!pid) return;
  const request = (state.filesGeneration = (state.filesGeneration || 0) + 1);
  const box = $("projectFiles");
  box.replaceChildren();
  if (!state.project.root) {
    box.append(el("p", "empty-inline", "创建项目时可填写本地目录。"));
    return;
  }
  try {
    const data = await api(
      `/projects/${pid}/files?path=${encodeURIComponent(path)}`,
    );
    if (
      request !== state.filesGeneration ||
      state.project?.id !== pid ||
      state.page !== "projects"
    )
      return;
    box.replaceChildren();
    if (path !== ".") {
      const back = el("button", "file-row", "返回上一级");
      const backIcon = icon("arrow");
      back.prepend(backIcon);
      back.onclick = () =>
        projectFiles(
          path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : ".",
        );
      box.append(back);
    }
    data.files.forEach((f) => {
      const row = el("button", "file-row");
      row.append(
        icon(f.type === "directory" ? "folder" : "file"),
        el("span", "", f.path.split("/").at(-1)),
        el("small", "", f.type === "directory" ? "文件夹" : bytes(f.bytes)),
      );
      row.onclick =
        f.type === "directory"
          ? () => projectFiles(f.path)
          : () => {
              newChat(pid);
              $("prompt").value =
                `请读取项目文件 ${f.path}，概括内容并说明关键点。`;
              saveDraft();
              updateComposer();
            };
      box.append(row);
    });
    if (!data.files.length)
      box.append(el("p", "empty-inline", "目录中没有可读取的文件。"));
  } catch (e) {
    if (request === state.filesGeneration)
      box.append(el("p", "empty-inline", e.message));
  }
}
// 投影当前项目资料；展开仍由服务端核对资料身份/作用域。
function renderProjectDocuments(pid) {
  $("projectDocuments").replaceChildren();
  const docs = state.data.documents.filter((d) => d.project_id === pid);
  docs.forEach((d) => {
    const b = el("button", "compact-row");
    b.append(
      icon("file"),
      el("span", "", d.title),
      el("small", "", `${d.chunks} 个片段`),
    );
    b.onclick = () => previewDocument(d.id);
    $("projectDocuments").append(b);
  });
  if (!docs.length)
    $("projectDocuments").append(
      el("p", "empty-inline", "暂无资料"),
    );
}
// 展示可见知识及作用域筛选；资料数量不代表召回质量。
function renderKnowledge() {
  const selected = $("knowledgeProject").value;
  fillProjects($("knowledgeProject"), "共享资料", selected);
  $("knowledgeStats").replaceChildren();
  for (const [label, value, name] of [
    ["知识文档", state.data.documents.length, "file"],
    [
      "可检索片段",
      state.data.documents.reduce((n, d) => n + d.chunks, 0),
      "book",
    ],
    ["项目知识库", state.data.projects.length, "folder"],
  ]) {
    const card = el("div", "stat-card"),
      text = el("div");
    text.append(
      el("small", "", label),
      el("strong", "", value.toString()),
    );
    card.append(text, icon(name));
    $("knowledgeStats").append(card);
  }
  $("documentList").replaceChildren();
  const docs = state.data.documents.filter(
    (d) => (d.project_id || "") === $("knowledgeProject").value,
  );
  if (!docs.length) {
    empty(
      $("documentList"),
      "暂无资料",
      "选择文本文件，或直接粘贴内容。",
      "book",
      () => knowledgeDialog($("knowledgeProject").value),
      "导入资料",
    );
    return;
  }
  docs.forEach((d) => {
    const row = el("div", "document-row");
    row.append(icon("file"));
    const info = el("button", "document-info");
    info.type = "button";
    info.setAttribute("aria-label", `查看资料 ${d.title}`);
    info.append(
      el("strong", "", d.title),
      el(
        "small",
        "",
        `${bytes(d.bytes)} · ${d.chunks} 个片段 · ${date(d.created_at)}`,
      ),
    );
    info.onclick = () => previewDocument(d.id);
    const archive = el("button", "icon-button");
    archive.append(icon("trash"));
    archive.setAttribute("aria-label", `移除资料 ${d.title}`);
    archive.onclick = async () => {
      archive.disabled = true;
      try {
        await api(`/documents/${d.id}/archive`, {});
        await refresh();
        if (state.page === "knowledge") renderKnowledge();
        toast("资料已移出检索索引，历史引用仍保留。");
      } catch (e) { toast(e.message); }
      finally { archive.disabled = false; }
    };
    row.append(info, el("span", "tag", d.project_name || "共享"), archive);
    $("documentList").append(row);
  });
}
// 准备显式资料导入表单；正文不会获得 Runtime 执行权限。
function knowledgeDialog(pid = "") {
  fillProjects($("documentProject"), "共享知识库", pid || "");
  $("documentTitle").value = "";
  $("documentContent").value = "";
  $("knowledgeFile").value = "";
  state.knowledgeFiles = [];
  openDialog("knowledgeDialog", "documentTitle");
}
// 读取用户明确选择的 UTF-8 文件作为资料；支持的扩展/错误由此入口约束。
async function readTextFile(file) {
  if (file.size > 1_000_000) throw new Error(`${file.name} 超过 1 MB。`);
  const buffer = await file.arrayBuffer();
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch {
    throw new Error(`${file.name} 需要是 UTF-8 文本。`);
  }
}
// 逐个导入明确选择的资料，保留项目关联；失败可见，不凭成功一项宣称全部完成。
async function importFiles(files, pid) {
  const results = [];
  for (const f of files) {
    const content = await readTextFile(f);
    results.push(
      await api("/documents", {
        title: f.name,
        content,
        project_id: pid || null,
      }),
    );
  }
  return results;
}
// 读取固定资料正文并按文本预览；不会把文档执行为页面脚本。
async function previewDocument(did) {
  try {
    const d = await api(`/documents/${did}`);
    $("previewTitle").textContent = d.title;
    $("previewMeta").textContent = `${bytes(d.bytes)} · 保存在本机`;
    $("previewContent").textContent = d.content;
    openDialog("documentDialog");
  } catch (e) {
    toast(e.message);
  }
}
// 提交词面查询并显示来源引用/得分；得分不是语义真实性或信息增益。
async function searchKnowledge() {
  const generation = state.generation;
  const request = state.searchGeneration = (state.searchGeneration || 0) + 1;
  try {
    const q = $("knowledgeSearch").value.trim();
    show("searchResults", !!q);
    if (!q) return;
    const pid = $("knowledgeProject").value;
    const data = await api(
      `/search?q=${encodeURIComponent(q)}&project_id=${encodeURIComponent(pid)}`,
    );
    if (request !== state.searchGeneration || generation !== state.generation ||
      q !== $("knowledgeSearch").value.trim() || pid !== $("knowledgeProject").value) return;
    $("searchResults").replaceChildren();
    data.sources.forEach((s) => {
      const c = el("div", "search-result"),
        title = el(
          "button",
          "text-button",
          `${s.title} · 片段 ${s.chunk_index + 1}`,
        );
      title.onclick = () => previewDocument(s.document_id);
      c.append(title, el("p", "", s.content));
      $("searchResults").append(c);
    });
    if (!data.sources.length)
      $("searchResults").append(
        el("p", "empty-inline", "没有找到匹配内容。试试更明确的关键词。"),
      );
  } catch (e) {
    toast(e.message);
  }
}

// 固定产品说明的中文投影：只匹配完整原文；新版本未识别的事实保留原文，避免旧译文覆盖新边界。
const architectureCopy = Object.freeze({
  __proto__: null,
  "Long-lived intent owns durable work state across Runs/Sessions. Explicit local timers and intervals admit bounded work while the Web service runs.": "跨 Run 和会话保存长期目标及工作状态。Web 服务运行期间，按明确的本地时间与间隔准入有界工作。",
  "Durable execution lifetime with execution cursor, checkpoint recovery and driver lease boundary.": "持久执行生命周期，包含执行游标、检查点恢复与 Driver 租约边界。",
  "Stable intent for one atomic effect or read.": "一次原子效果或读取的稳定意图。",
  "One actual execution opportunity for an Action.": "一次 Action 的实际执行机会。",
  "Durable authority to start one Attempt; not success proof.": "启动一次 Attempt 的持久授权；不代表操作成功。",
  "Durable fact about what an issued Attempt actually produced.": "记录已发起 Attempt 实际产生的结果。",
  "Content-addressed immutable output/evidence.": "按内容寻址的不可变产物与证据。",
  "Independent acceptance bound to fixed artifacts/evidence.": "绑定固定产物与证据的独立验收。",
  "Choose how work is organized; conservative Intent Pick supports deterministic arithmetic and local-retrieval routing, while unmatched work falls back safely.": "组织工作方式。保守的 Intent Pick 支持确定性计算和本地检索路由，未匹配任务安全回退。",
  "Steer, pause, resume, stop, model/thinking switch and context compact at safe points.": "在安全点调整、暂停、继续、停止，切换模型与 Thinking，或压缩上下文。",
  "Dispatch admitted work to model/tool/file/git executors and reconcile outcomes.": "把已准入工作分派给模型、工具、文件与 Git 执行器，并核对结果。",
  "Discover/version/admit capabilities without turning discovery into authority.": "发现、版本化和准入能力；发现能力不代表获得执行授权。",
  "Own durable Runs, budgets, commands, events and product records.": "管理持久 Run、预算、命令、事件与产品记录。",
  "Build bounded provenance-aware projections. Knowledge resolves one fixed source/digest across L0 metadata, L1 chunk navigation and L2 detailed evidence.": "构建有界、保留来源的上下文。知识在 L0 元信息、L1 片段导航和 L2 详细证据中绑定同一来源与摘要。",
  "Versioned working/episodic/semantic/procedural records with provenance/revoke. Recall scans the full visible active candidate set with project/session scope and fact level; Information Delta is not yet a lifecycle engine.": "管理可追溯、可撤销的工作、经历、语义与过程记忆。召回扫描项目与会话范围内的全部可见候选，保留事实层级；Information Delta 尚不是生命周期引擎。",
  "Explicit Goals, Triggers, preferences and permissions for long-lived personal agents.": "用明确的 Goal、触发条件、偏好与权限支撑长期个人任务。",
  "Persistent third-column observatory projects Goal, execution flow, recovery cursor/driver lease, trajectory, token/context windows, tool calls, control and budgets without owning truth.": "常驻第三栏投影 Goal、执行流程、恢复游标与 Driver 租约、轨迹、Token 与上下文、工具、控制和预算；不拥有业务事实。",
  "Versioned executable suites plus a durable local Eval Ledger, paired policy comparisons and release gate; no automatic policy promotion.": "版本化可执行评测集、本地持久评测账本、配对策略比较与发布门槛；不自动提升策略。",
  "Durable candidate registry, full-suite release evidence, explicit promote/rollback and future-Turn active policy pointer; never auto-publishes into a live Turn.": "持久候选登记、完整评测发布证据、明确提升与回滚，以及后续 Turn 的活动策略指针；不自动发布到正在执行的 Turn。",
  "Model chooses the next StepDecision and may repeat tool/model steps.": "模型选择下一步 StepDecision，可继续执行工具或模型步骤。",
  "Answer or complete without delegating through a workflow.": "直接回答或完成任务，无需通过工作流委派。",
  "Bounded live SEEK/EXPAND admission rejects exact repeats, stalled pagination and runaway information acquisition before Tool Ticket; KEEP is implicit when the model continues without another information tool.": "有界 SEEK / EXPAND 在签发工具 Ticket 前拒绝重复请求、停滞分页和失控的信息获取。模型不再调用信息工具而继续时，隐式采用 KEEP。",
  "Paired fixed-case eval plus cross-case calibration can estimate observed quality delta and explicit-cost gain-per-cost; evidence gates policy release but never auto-promotes.": "固定用例配对评测与跨用例校准估计质量变化及明确成本下的收益；证据约束策略发布，不自动提升策略。",
  "Turn admission resolves a durable active rule/fixed policy into L0/L1/L2 and freezes the policy identity; explicit promotion/rollback affects future Turns only.": "Turn 准入时，将持久活动规则或固定策略解析为 L0 / L1 / L2 并冻结身份；明确提升与回滚只影响后续 Turn。",
  "Conservative cascade routes strict arithmetic locally and explicit/strong admitted knowledge through local retrieval; unmatched input falls back to the Agent Loop.": "保守级联将严格算术交给本地计算，将明确或强匹配且已准入的知识交给本地检索；未匹配输入回退 Agent Loop。",
  "Parent LLM may use agent.delegate or up to three concurrent isolated workers via agent.parallel; children only read fixed inputs, cannot write or recursively delegate, and return reviewed handoffs.": "父模型可使用 agent.delegate，或通过 agent.parallel 同时委派最多三个隔离 Worker。子任务只读取固定输入，不能写入或递归委派，交接结果由主模型审核。",
  "Explicit Goal schedules admit durable Runs across sessions; the background executor drives the same admitted work.": "明确的 Goal 计划跨会话准入持久 Run，由后台执行器继续同一项已准入工作。",
  "Conversation is an inbound product/channel adapter, not the Runtime core.": "对话是产品与渠道的入站适配器，与 Runtime 核心分离。",
  "Local durable state adapter.": "本地持久状态适配器。",
  "Scoped UTF-8/project/output execution adapter.": "在明确范围内读取 UTF-8、项目内容和执行输出操作。",
  "Optional derived vector-index adapter; SQLite/object storage stays authoritative and lexical retrieval remains the safe fallback.": "可选的派生向量索引。SQLite 与对象存储保留事实权威，词面检索作为安全回退。",
  "Local model provider adapter.": "本地模型提供方适配器。",
  "Remote Responses provider; API key uses secure OS credentials or explicit environment configuration.": "远端 Responses 提供方。API Key 使用系统安全凭据库或明确的环境配置。",
  "Myth-owned OSS OAuth with PKCE/OIDC, secure OS credential storage, refresh rotation and revoke/logout.": "Myth 自有开源 OAuth：PKCE / OIDC、系统安全凭据库、刷新轮换及撤销与退出。",
  "Explicit one-shot/interval schedules commit wakeup and Turn together. Webhook/email remain planned.": "明确的一次性或间隔计划，原子提交唤醒与 Turn。Webhook 与邮件仍处于规划阶段。",
  "Chat / Web UI": "对话界面", "Local Files": "本地文件", "Milvus Vector DB": "Milvus 向量索引",
  "Sign in with ChatGPT": "ChatGPT OAuth", "Local Goal Timer": "本地 Goal 计划",
});
// 状态原值仍用于 CSS/API 身份；固定中文只负责读者可见标签，未知枚举保持原文。
const platformLabels = Object.freeze({ __proto__: null, hardened: "已强化", usable: "可使用", connected: "已接通", exists: "已存在", planned: "仅规划", executable: "可执行", compute: "计算", read: "读取", write: "写入", execute: "执行", agent: "代理", evidence: "证据", execution: "执行", file: "文件", knowledge: "知识", memory: "记忆", tooling: "工具" });

// 展示服务端成熟度目录；planned 项保持规划状态，不造可执行按钮。
function renderArchitectureItems(parent, items) {
  parent.replaceChildren();
  (items || []).forEach((item) => {
    const maturity = item.maturity || item.state || "exists";
    const card = el("article", "platform-card " + maturity);
    const head = el("div", "platform-card-head");
    head.append(
      el("span", "platform-phase", item.kind || "component"),
      el("span", "platform-state " + maturity, platformLabels[maturity] || maturity),
    );
    card.append(
      head,
      el("h2", "", architectureCopy[item.label] || item.label),
      el("p", "", architectureCopy[item.responsibility] || item.responsibility),
    );
    if (item.depends_on?.length)
      card.append(el("small", "", "依赖 · " + item.depends_on.join(" / ")));
    parent.append(card);
  });
}

// 刷新架构/能力/记忆统计视图；只投影事实，不触发发布或执行。
function renderRuntime() {
  const platform = state.data.platform;
  const core = $("runtimeCore"),
    domains = $("platformLayers"),
    strategies = $("runtimeStrategies"),
    adapters = $("runtimeAdapters"),
    caps = $("platformCapabilities");
  [core, domains, strategies, adapters, caps].forEach((node) =>
    node.replaceChildren(),
  );
  if (!platform) {
    empty(
      domains,
      "架构信息暂不可用",
      "重新加载工作区后再试。",
      "spark",
    );
    return;
  }
  renderArchitectureItems(core, platform.core || []);
  renderArchitectureItems(domains, platform.domains || []);
  renderArchitectureItems(strategies, platform.strategies || []);
  renderArchitectureItems(adapters, platform.adapters || []);
  platform.capabilities.forEach((cap) => {
    const row = el("div", "capability-row");
    const left = el("div");
    left.append(
      el("strong", "", cap.id),
      el("small", "", (platformLabels[cap.family] || cap.family) + " · " + (platformLabels[cap.risk] || cap.risk)),
    );
    row.append(left, el("span", "platform-state " + cap.state, platformLabels[cap.state] || cap.state));
    caps.append(row);
  });
  $("capabilityCount").textContent =
    (platform.executable_capabilities?.length || 0) + " 项可执行能力";
}

// 按 hash 装配页面并推进 generation；异步响应只有仍匹配当前页面时才展示。
async function route() {
  if (!state.data) return;
  if (state.page === "chat") saveDraft();
  const generation = ++state.generation;
  const [page = "chat", id] = location.hash.slice(1).split("/");
  state.page = [
    "chat",
    "goals",
    "runtime",
    "sessions",
    "projects",
    "knowledge",
    "settings",
  ].includes(page)
    ? page
    : "chat";
  try { state.id = id ? decodeURIComponent(id) : null; }
  catch (_) { state.id = null; }
  state.threadKey = "";
  state.session = null;
  state.loadingSession = state.page === "chat" && !!state.id;
  if (state.page === "chat") restoreDraft(state.id || "new");
  const view = state.page === "projects" && id ? "project" : state.page;
  [
    "chat",
    "goals",
    "runtime",
    "sessions",
    "projects",
    "project",
    "knowledge",
    "settings",
  ].forEach((p) => show(p + "Page", p === view));
  $("pageTitle").textContent = {
    chat: "对话",
    goals: "目标与计划",
    runtime: "Runtime",
    sessions: "会话",
    projects: "项目",
    knowledge: "知识库",
    settings: "设置",
  }[state.page];
  show("sessionMenu", false);
  renderSidebar();
  try {
    if (state.page === "chat") {
      if (state.id) {
        show("welcome", false);
        show("thread", true);
        const loading = el("p", "thread-loading", "正在载入会话…");
        loading.prepend(taijiMark(true));
        $("thread").replaceChildren(loading);
        await openSession(state.id, generation);
      }
      else {
        fillProjects($("chatProject"), "独立对话", $("chatProject").value);
        renderChat(null);
      }
    } else if (state.page === "goals") await renderGoals();
    else if (state.page === "runtime") renderRuntime();
    else if (state.page === "sessions") await renderSessionPage();
    else if (state.page === "projects")
      state.id ? await renderProject(state.id) : renderProjects();
    else if (state.page === "knowledge") renderKnowledge();
    else {
      loadSettings();
      renderConnection();
    }
  } catch (e) {
    if (generation === state.generation && state.page === "chat" && state.loadingSession) {
      $("thread").replaceChildren();
      empty($("thread"), "无法载入会话", e.message, "chat", () => route(), "重试");
    }
    toast(e.message);
  }
  updateComposer();
  updateScrollButton();
}
// 恢复 bootstrap 或读取当前会话；不重发任务/控制/登录提交，迟到页面仍受 generation 约束。
async function readWorkspace() {
  if (!state.initialized) {
    await refresh();
    loadSettings();
    await refreshChatGPTAuth();
    await refreshClaudeAuth();
    await refreshProviderKeys();
    fillGoals($("chatGoal"), "");
    await route();
    await checkConnection(true);
    state.initialized = true;
  } else if (state.page === "chat" && state.id) {
    await openSession(state.id, state.generation);
  } else if (state.page === "goals") {
    await renderGoals();
  } else {
    // 没有选中会话也须能观察服务断开/重启；只读取共享产品投影。
    await refresh();
  }
}
// 只启动一个可恢复读循环；失败按 1/2/4/8/16/32/60 秒等待，成功恢复原会话视图。
function poll() {
  if (!state.poll) state.poll = createReadReconnector({
    read: readWorkspace,
    normalDelay: () => document.hidden ? 6000 : state.session?.turns.at(-1)?.driver_active ? 1000 : 3000,
    onWaiting: ({failures, delayMs}) => {
      if (failures === 1) toast("工作区连接中断，保留当前内容并自动重连。");
      $("connectionDot").className = "connection-dot disconnected";
      $("modelLabel").textContent = "工作区断连 · " + delayMs / 1000 + " 秒后重试";
    },
    onRestored: () => { renderConnection(); toast("工作区连接已恢复。"); },
  });
  return state.poll.start();
}

// 事件绑定只消费明确用户操作；业务身份、参数和状态仍经服务器校验。
$("newChat").onclick = () => newChat();
$("newSession").onclick = () => newChat();
$("composer").onsubmit = sendMessage;
$("quickGoal").onclick = () => {
  $("goalTitleInput").value = "";
  $("goalDescriptionInput").value = "";
  openDialog("goalDialog", "goalTitleInput");
};
// 事件绑定只消费明确用户操作；业务身份、参数和状态仍经服务器校验。
$("goalForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const goal = await api("/goals", {
      title: $("goalTitleInput").value,
      description: $("goalDescriptionInput").value,
    });
    $("goalDialog").close();
    await refresh();
    fillGoals($("chatGoal"), goal.goal_id);
    if (state.page === "goals") await renderGoals();
    toast("长期 Goal 已创建并绑定到下一轮。");
  } catch (err) {
    toast(err.message);
  }
};
$("prompt").onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && !state.composing && e.keyCode !== 229) {
    e.preventDefault();
    sendMessage();
  }
};
$("prompt").addEventListener("compositionstart", () => { state.composing = true; updateComposer(); });
$("prompt").addEventListener("compositionend", () => { state.composing = false; saveDraft(); updateComposer(); });
$("prompt").addEventListener("input", () => { saveDraft(); updateComposer(); });
$("chatProject").addEventListener("change", saveDraft);
$("chatGoal").addEventListener("change", saveDraft);
$("stopTurn").onclick = () => controlTurn("stop");
$("modelPill").onclick = () =>
  state.session?.turns.at(-1) ? openControlDialog() : go("settings");
$("sessionMenu").onclick = () => editSession(state.session);
$("steerTurn").onclick = openControlDialog;
$("pauseTurn").onclick = () => controlTurn("pause");
$("resumeTurn").onclick = () => controlTurn("resume");
$("compactTurn").onclick = () => controlTurn("compact");
$("stopRun").onclick = () => controlTurn("stop");
$("applySteer").onclick = async () => {
  const text = $("steerInput").value.trim();
  if (!text) return toast("Steering 不能为空。");
  await controlTurn("steer", { text });
  openControlDialog();
};
$("applyModelSwitch").onclick = async () => {
  const model = $("turnModelInput").value.trim();
  if (!model) return toast("模型名称不能为空。");
  await controlTurn("switch_model", { model });
  openControlDialog();
};
$("applyThinkingSwitch").onclick = async () => {
  await controlTurn("switch_thinking", {
    thinking: reasoningSelectionValue($("turnThinkingInput")),
  });
  openControlDialog();
};
bindNavigationDrawer();
$("themeToggle").onclick = () =>
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
document.querySelectorAll("[data-theme-choice]").forEach((button) => {
  button.onclick = () => {
    if (button.dataset.themeChoice === "system") {
      try { localStorage.removeItem(THEME_STORAGE_KEY); } catch (_) {}
      applyTheme(themeMedia.matches ? "dark" : "light");
    } else applyTheme(button.dataset.themeChoice, true);
  };
});
// 导航收合仅保存本机展示偏好，手机仍以完整抽屉呈现同一导航。
function setSidebarCollapsed(collapsed, persist = false) {
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  const button = $("sidebarCollapse");
  if (button) {
    button.setAttribute("aria-expanded", String(!collapsed));
    button.setAttribute("aria-label", collapsed ? "展开侧栏" : "收起侧栏");
    button.title = collapsed ? "展开侧栏" : "收起侧栏";
  }
  if (persist) {
    try { localStorage.setItem("myth-sidebar-collapsed", String(collapsed)); } catch (_) {}
  }
}
try { setSidebarCollapsed(localStorage.getItem("myth-sidebar-collapsed") === "true"); } catch (_) {}
if ($("sidebarCollapse")) $("sidebarCollapse").onclick = () =>
  setSidebarCollapsed(!document.body.classList.contains("sidebar-collapsed"), true);
window.addEventListener("storage", (event) => {
  if (event.key === "myth-sidebar-collapsed") setSidebarCollapsed(event.newValue === "true");
});
document.querySelectorAll("[data-suggestion]").forEach(
  (b) =>
    (b.onclick = () => {
      $("prompt").value = b.dataset.suggestion;
      saveDraft();
      updateComposer();
      $("prompt").focus();
    }),
);
document
  .querySelectorAll("[data-action]")
  .forEach((b) => (b.onclick = () => go(b.dataset.action)));
document
  .querySelectorAll("[data-close]")
  .forEach((b) => (b.onclick = () => $(b.dataset.close).close()));
document.querySelectorAll("dialog").forEach((dialog) => {
  // Chrome 原生模态的末尾 Tab 可能转到浏览器工具栏，显式围栏保持工作台键盘链连续。
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const targets = [...dialog.querySelectorAll("a[href], button, input, select, textarea, summary, [tabindex]")]
      .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
    const first = targets[0], last = targets.at(-1);
    if (!first) { event.preventDefault(); return; }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  });
  // 仅从遮罩按下并在遮罩抬起才关闭，避免从表单拖选到遮罩时丢失编辑位置。
  let backdropDown = false;
  const outside = (event) => {
    const rect = dialog.getBoundingClientRect();
    return event.clientX < rect.left || event.clientX > rect.right ||
      event.clientY < rect.top || event.clientY > rect.bottom;
  };
  dialog.addEventListener("pointerdown", (event) => { backdropDown = event.target === dialog && outside(event); });
  dialog.addEventListener("click", (event) => {
    if (backdropDown && event.target === dialog && outside(event)) dialog.close();
    backdropDown = false;
  });
  dialog.addEventListener("close", () => {
    if (dialog._returnFocus?.isConnected) dialog._returnFocus.focus();
    dialog._returnFocus = null;
  });
});
if ($("commandToggle")) $("commandToggle").onclick = openCommandPalette;
if ($("commandSearch")) {
  $("commandSearch").setAttribute("role", "combobox");
  $("commandSearch").setAttribute("aria-autocomplete", "list");
  $("commandSearch").setAttribute("aria-controls", "commandResults");
  $("commandSearch").setAttribute("aria-expanded", "true");
  $("commandResults").setAttribute("role", "listbox");
  $("commandResults").setAttribute("aria-label", "命令与搜索结果");
  $("commandSearch").oninput = renderCommands;
  $("commandSearch").onkeydown = (e) => {
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      selectCommand((selectedCommand + (e.key === "ArrowDown" ? 1 : -1) + commandItems.length) % (commandItems.length || 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      runCommand(selectedCommand);
    }
  };
}
if ($("scrollToBottom")) $("scrollToBottom").onclick = () => {
  $("chatScroll").scrollTo({ top: $("chatScroll").scrollHeight,
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
};
$("chatScroll").addEventListener("scroll", updateScrollButton, { passive: true });
document
  .querySelectorAll(".navigation a,.settings-link")
  .forEach((a) => (a.onclick = closeNavigation));
$("createProject").onclick = () => projectDialog();
$("editProject").onclick = () => projectDialog(state.project);
$("projectChat").onclick = () => newChat(state.project.id);
$("projectImport").onclick = () => knowledgeDialog(state.project.id);
$("projectForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const value = {
      name: $("projectNameInput").value,
      description: $("projectDescriptionInput").value,
      root: $("projectRootInput").value,
      instructions: $("projectInstructionsInput").value,
    };
    const p = await api(
      state.editingProject
        ? `/projects/${state.editingProject.id}`
        : "/projects",
      value,
    );
    $("projectDialog").close();
    await refresh();
    go("projects", p.id);
    await route();
  } catch (e) {
    toast(e.message);
  }
};
$("sessionForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await api(`/sessions/${state.editingSession.id}`, {
      title: $("sessionTitleInput").value,
      project_id: $("sessionProjectInput").value || null,
      pinned: $("sessionPinned").checked,
    });
    $("sessionDialog").close();
    await refresh();
    await route();
  } catch (e) {
    toast(e.message);
  }
};
$("archiveSession").onclick = async () => {
  try {
    await api(`/sessions/${state.editingSession.id}`, {
      archived: !state.editingSession.archived,
    });
    $("sessionDialog").close();
    await refresh();
    go("sessions");
    await route();
  } catch (e) {
    toast(e.message);
  }
};
$("activeSessions").onclick = () => {
  state.archived = false;
  renderSessionPage().catch((e) => toast(e.message));
};
$("archivedSessions").onclick = () => {
  state.archived = true;
  renderSessionPage().catch((e) => toast(e.message));
};
$("sessionSearch").oninput = () => renderSessions(state.sessionList);
$("importKnowledge").onclick = () =>
  knowledgeDialog($("knowledgeProject").value);
$("knowledgeProject").onchange = () => {
  show("searchResults", false);
  renderKnowledge();
};
$("searchKnowledge").onclick = searchKnowledge;
$("knowledgeSearch").onkeydown = (e) => {
  if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); searchKnowledge(); }
};
$("knowledgeFile").onchange = async () => {
  try {
    state.knowledgeFiles = [...$("knowledgeFile").files];
    if (state.knowledgeFiles[0]) {
      $("documentTitle").value =
        state.knowledgeFiles.length === 1
          ? state.knowledgeFiles[0].name
          : `${state.knowledgeFiles.length} 个文件`;
      $("documentContent").value = await readTextFile(state.knowledgeFiles[0]);
    }
  } catch (e) {
    toast(e.message);
  }
};
$("knowledgeForm").onsubmit = async (e) => {
  e.preventDefault();
  const submit = e.target.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    const pid = $("documentProject").value;
    if (state.knowledgeFiles?.length > 1)
      await importFiles(state.knowledgeFiles, pid);
    else
      await api("/documents", {
        title: $("documentTitle").value,
        content: $("documentContent").value,
        project_id: pid || null,
      });
    $("knowledgeDialog").close();
    await refresh();
    $("knowledgeProject").value = pid;
    if (state.page === "projects" && state.project)
      renderProjectDocuments(state.project.id);
    else renderKnowledge();
    toast("资料已导入并建立检索索引。");
  } catch (e) {
    toast(e.message);
  } finally {
    submit.disabled = false;
  }
};
$("attachButton").onclick = () => $("chatFiles").click();
$("chatFiles").onchange = async () => {
  const draft = saveDraft();
  const generation = state.generation;
  const files = [...$("chatFiles").files];
  try {
    if (draft.attached.length + files.length > 4)
      throw new Error("每条消息最多附加 4 份资料。");
    const docs = await importFiles(
      files,
      state.session?.project_id || $("chatProject").value,
    );
    draft.attached.push(...docs);
    if (state.drafts.get(state.composerKey) === draft) {
      state.attached = [...draft.attached];
      renderAttachments();
    }
    await refresh();
    toast(generation === state.generation ? "资料已附加到下一条消息" : "资料已导入并保留在原会话草稿中");
  } catch (e) {
    toast(e.message);
  } finally {
    $("chatFiles").value = "";
  }
};
$("provider").onchange = () => {
  invalidateConnection();
  $("model").value = "";
  delete $("maxTokens").dataset.catalogMax;
  $("providerApiKey").value = "";
  renderChatGPTAuth();
  renderClaudeAuth();
  renderProviderKeyAuth();
  renderConnection();
  renderAdaptiveModelSettings();
  poolRefreshPrices();
};
$("ollamaUrl").addEventListener("input", invalidateConnection);
$("chatgptLogin").onclick = beginChatGPTLogin;
$("claudeLogin").onclick = beginClaudeLogin;
$("claudeConfigure").onclick = async () => {
  const clientId = $("claudeClientId").value.trim();
  if (!clientId) return toast("请先填写 Myth 的 Claude OAuth Client ID。");
  try {
    state.claudeAuth = await claudeAuthApi("/configure", {client_id: clientId});
    $("claudeClientId").value = "";
    renderClaudeAuth();
    toast("Claude OAuth Client ID 已保存。");
  } catch (e) { toast(e.message); }
};
$("claudeLogout").onclick = async () => {
  try {
    await claudeAuthApi("/logout", {});
    await refreshClaudeAuth();
    state.connection = null;
    renderConnection();
    toast("Claude OAuth 本机凭据已清除。");
  } catch (e) { toast(e.message); }
};
$("providerKeyConnect").onclick = async () => {
  const provider = $("provider").value;
  const secret = $("providerApiKey").value.trim();
  if (!secret) return toast("请先粘贴 API Key。");
  $("providerKeyConnect").disabled = true;
  try {
    await providerAuthApi("/connect", { provider, api_key: secret });
    $("providerApiKey").value = "";
    await refreshProviderKeys();
    state.connection = null;
    await checkConnection(false);
    toast("API Key 已安全保存并验证，模型现在可直接使用。");
  } catch (e) {
    toast(e.message);
  } finally {
    $("providerApiKey").value = "";
    $("providerKeyConnect").disabled = false;
  }
};
$("providerKeyDisconnect").onclick = async () => {
  const provider = $("provider").value;
  try {
    await providerAuthApi("/disconnect", { provider });
    await refreshProviderKeys();
    state.connection = null;
    renderConnection();
    toast("Myth 内保存的 API Key 已断开。");
  } catch (e) {
    toast(e.message);
  }
};
$("chatgptLogout").onclick = async () => {
  try {
    const result = await authApi("/logout", {});
    await refreshChatGPTAuth();
    state.connection = null;
    renderConnection();
    toast(
      result.remote_revoked
        ? "ChatGPT 已退出并撤销远端会话。"
        : "本地凭据已清除；远端撤销未确认，请在 ChatGPT 设置中检查连接。",
    );
  } catch (e) {
    toast(e.message);
  }
};
$("model").addEventListener("change", renderAdaptiveModelSettings);
$("model").addEventListener("input", renderAdaptiveModelSettings);
let modelPriceTimer;
$("model").addEventListener("input", () => { delete $("maxTokens").dataset.catalogMax; clearTimeout(modelPriceTimer); modelPriceTimer = setTimeout(poolRefreshPrices, 350); });
$("model").addEventListener("change", poolRefreshPrices);
$("turnModelInput").addEventListener("change", () => {
  const turn = state.session?.turns.at(-1);
  if (turn) renderTurnReasoning(turn, turn.control?.thinking ?? turn.settings?.thinking);
});
$("checkConnection").onclick = () => checkConnection(false);
$("saveSettings").onclick = async () => {
  if ($("saveSettings").disabled) return;
  // 浏览器先定位越界/缺失字段，服务端仍独立验证；隐藏且无效的供应商字段不参与验证。
  const invalid = Array.from($("settingsPage").querySelectorAll("input, select")).find(input => !input.disabled && input.getClientRects().length && !input.checkValidity());
  if (invalid) { invalid.reportValidity(); return; }
  const payload = settingsPayload();
  $("saveSettings").disabled = true;
  $("saveSettings").textContent = "正在保存…";
  try {
    state.data.settings = await api("/settings", payload);
    $("settingsSaved").textContent = JSON.stringify(settingsPayload()) === JSON.stringify(payload) ? "已保存" : "当前修改尚未保存";
    renderConnection();
    toast("模型设置已保存。");
  } catch (e) {
    toast(e.message);
  } finally {
    $("saveSettings").disabled = false;
    $("saveSettings").textContent = "保存设置";
  }
};
window.addEventListener("hashchange", route);
document.addEventListener("keydown", (e) => {
  if (e.isComposing || e.keyCode === 229) return;
  if ($("runtimeInspector")?.classList.contains("open")) return;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if ($("commandPalette")?.open) $("commandPalette").close();
    else openCommandPalette();
  } else if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "o") {
    e.preventDefault();
    if (!document.querySelector("dialog[open]")) newChat();
  } else if (e.key === "Escape") closeNavigation();
});
updateComposer();
poll();
