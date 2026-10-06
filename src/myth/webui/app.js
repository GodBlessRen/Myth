/* Myth 对话工作台：原生 JS 投影持久 Runtime 状态。
 * 浏览器负责导航/草稿/显式控制与只读轮询，不以渲染状态替代准入、Receipt 或 UNKNOWN 核对。
 */
"use strict";

// 前端易失状态：data/session 为服务端投影；drafts/busy/generation 只管理当前页面交互。
const state = {
  // data：最近一次 bootstrap 只读投影；不保存认证 token。
  data: null,
  // page/id：当前 hash 路由和资源身份；不是后端权限凭据。
  page: "chat",
  id: null,
  // session：当前会话的持久事实投影，只有 API 可改变真实 Turn。
  session: null,
  // connection：公开 Provider/model 目录检查结果，不代表模型调用成功。
  connection: null,
  // chatgptAuth/claudeAuth/providerAuth：脱敏连接投影；不含 access/refresh/API token。
  chatgptAuth: null,
  claudeAuth: null,
  providerAuth: null,
  // attached/drafts：尚未发送的显式资料与逐会话草稿；刷新服务端投影不能清空它们。
  attached: [],
  drafts: new Map(),
  composerKey: "new",
  // busy/composing/loadingSession：本机发送、输入法与会话装载边界，避免重复/错误输入提交。
  busy: false,
  composing: false,
  loadingSession: false,
  // archived：会话目录筛选，不改变 Run 生命周期。
  archived: false,
  // generation/threadKey：丢弃迟到读取和避免重复重绘；不是业务 revision。
  generation: 0,
  threadKey: "",
  // pending：当前草稿待确认入口身份；网络超时后复用 request_id，不盲目新建 Turn。
  pending: null,
};
// 固定 DOM 身份查找；页面结构变化必须由测试同步核对。
const $ = (id) => document.getElementById(id);

// 封闭矢量图标目录，不解释用户提供的 SVG/HTML。
const paths = {
  plus: "M12 5v14M5 12h14",
  close: "m6 6 12 12M18 6 6 18",
  arrow: "m12 19 0-14m-6 6 6-6 6 6",
  right: "m9 5 7 7-7 7",
  down: "m6 9 6 6 6-6",
  search: "M21 21l-4.4-4.4M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0",
  chat: "M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z",
  folder: "M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 3H20v19H6.5A2.5 2.5 0 0 1 4 19.5v-14A2.5 2.5 0 0 1 6.5 3Z",
  settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8m8.4 4a7.7 7.7 0 0 0-.1-1.3l1.1-1.3-1.7-3-1.7.3a8 8 0 0 0-2.2-1.3l-.6-1.6h-3.4l-.6 1.6A8 8 0 0 0 7 6.7l-1.7-.3-1.7 3 1.1 1.3a7.7 7.7 0 0 0 0 2.6l-1.1 1.3 1.7 3 1.7-.3a8 8 0 0 0 2.2 1.3l.6 1.6h3.4l.6-1.6a8 8 0 0 0 2.2-1.3l1.7.3 1.7-3-1.1-1.3a7.7 7.7 0 0 0 .1-1.3Z",
  moon: "M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  menu: "M4 6h16M4 12h16M4 18h16",
  panels: "M4 4h16v16H4ZM9 4v16",
  paperclip: "m21.4 11.6-9.2 9.2a6 6 0 0 1-8.5-8.5L13 3a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5",
  stop: "M6 6h12v12H6Z",
  pause: "M7 5v14M17 5v14",
  play: "m8 5 11 7-11 7Z",
  refresh: "M20 7v5h-5M4 17v-5h5M6.1 7a7 7 0 0 1 11.6-2L20 8M4 16l2.3 3A7 7 0 0 0 17.9 17",
  file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Zm0 0v6h6M8 13h8M8 17h6",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  pin: "m16 3 5 5-4 1-4 4-1 5-2-2-5 5 5-5-2-2 5-1 4-4Z",
  trash: "M3 6h18M8 6V4h8v2M5 6l1 14h12l1-14M10 10v6M14 10v6",
  spark: "m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6Z",
  goal: "M12 3v3M12 18v3M3 12h3M18 12h3M19 12a7 7 0 1 1-14 0 7 7 0 0 1 14 0M14 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0",
  clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M12 7v5l3 2",
  check: "m5 12 4 4L19 6",
  link: "M10 13a5 5 0 0 0 7 .5l3-3a5 5 0 0 0-7-7l-2 2M14 11a5 5 0 0 0-7-.5l-3 3a5 5 0 0 0 7 7l2-2",
  terminal: "m4 17 6-5-6-5M13 17h7",
  layout: "M3 3h7v7H3ZM14 3h7v7h-7ZM3 14h7v7H3ZM14 14h7v7h-7Z",
  shield: "M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Zm-4-11 3 3 5-6",
};
// 从封闭图标名建立 SVG 节点；未知名字回退固定 spark，不注入外部标记。
function icon(name, className = "icon") {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("class", className);
  s.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(s.namespaceURI, "path");
  p.setAttribute("d", paths[name] || paths.spark);
  s.append(p);
  return s;
}
// 同一离线矢量用于品牌与真实等待；图片无业务语义，状态由相邻文字说明。
function brandMark(waiting = false) {
  const mark = el("img", "brand-mark" + (waiting ? " brand-wait" : ""));
  mark.src = "/myth-mark.svg";
  mark.alt = "";
  mark.width = 16;
  mark.height = 16;
  mark.setAttribute("aria-hidden", "true");
  return mark;
}
document.querySelectorAll("[data-icon]").forEach((n) => {
  n.replaceChildren(icon(n.dataset.icon));
});
// 创建文本节点而非 innerHTML，用户/模型内容不能成为页面脚本。
function el(tag, className = "", text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}
// 只切换固定节点可见性；业务状态由对应 API 投影决定。
function show(id, yes) {
  $(id)?.classList.toggle("hidden", !yes);
}
// 页面提示拥有独立短时生命周期；提示不表示任何持久业务完成。
function toast(message) {
  const n = $("toast");
  n.textContent = message;
  n.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => n.classList.add("hidden"), 3600);
}
// 显式用户主题优先；选择跟随系统时保持未设置，不把自动主题误存为偏好。
const THEME_STORAGE_KEY = "myth-theme";
const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme(value, persist = false) {
  const mode = value === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = mode;
  document.documentElement.style.colorScheme = mode;
  if (persist) { try { localStorage.setItem(THEME_STORAGE_KEY, mode); } catch (_) {} }
  $("themeToggle").replaceChildren(icon(mode === "dark" ? "sun" : "moon"));
  $("themeToggle").setAttribute("aria-label", mode === "dark" ? "切换浅色主题" : "切换深色主题");
  let choice = "system";
  try { const saved = localStorage.getItem(THEME_STORAGE_KEY); if (["light", "dark"].includes(saved)) choice = saved; } catch (_) {}
  document.querySelectorAll("[data-theme-choice]").forEach(button => {
    const selected = button.dataset.themeChoice === choice;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", mode === "dark" ? "#0E100F" : "#FFFEF8");
}
applyTheme(document.documentElement.dataset.theme);
themeMedia.addEventListener("change", event => {
  let saved = null; try { saved = localStorage.getItem(THEME_STORAGE_KEY); } catch (_) {}
  if (!["light", "dark"].includes(saved)) applyTheme(event.matches ? "dark" : "light");
});
window.addEventListener("storage", event => {
  if (event.key === THEME_STORAGE_KEY) applyTheme(event.newValue || (themeMedia.matches ? "dark" : "light"));
});
// 有界同源 JSON 传输，超时覆盖响应体；不自动重试可能已经准入的写入。
async function jsonRequest(prefix, path, value) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const r = await fetch(prefix + path, {
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
// 工作区写入保持调用者 request_id；传输失败不等于服务端未准入。
function api(path, value) {
  return jsonRequest("/api/workspace", path, value);
}
// ChatGPT 的公开认证投影使用独立固定前缀；浏览器不读取 token。
function authApi(path, value) {
  return jsonRequest("/api/auth/chatgpt", path, value);
}
// Claude 配置与登录保持独立端点；不借共享传输跨越凭据所有权。
function claudeAuthApi(path, value) {
  return jsonRequest("/api/auth/claude", path, value);
}
// API Key 只进入用户明确发起的请求体；不保存到浏览器持久状态。
function providerAuthApi(path, value) {
  return jsonRequest("/api/auth/providers", path, value);
}
// Provider API Key 可由 Myth 内保存，也可由环境变量提供；页面只呈现公开连接事实。
function renderProviderKeyAuth() {
  const provider = $("provider").value;
  const supportsKey = ["openai", "deepseek", "moonshot"].includes(provider);
  show("apiKeyAuthBox", supportsKey);
  if (!supportsKey) return;
  const status = state.providerAuth?.providers?.[provider] || {};
  const connected = !!status.connected;
  const label = provider === "deepseek" ? "DeepSeek" : provider === "moonshot" ? "Kimi" : "OpenAI";
  $("providerAuthSummary").textContent = connected ? `${label} 已连接` : `在 Myth 内连接 ${label}`;
  $("providerAuthDetail").textContent = connected
    ? status.source === "secure_store" ? "API Key 已保存在系统安全凭据库；不会写入项目文件、日志或页面状态。" : "当前使用显式环境变量配置；也可以在这里保存 Myth 专用 API Key。"
    : status.reason === "secure_store_unavailable" ? "系统安全凭据库不可用；Myth 不会降级为明文保存。请启用系统凭据服务后重试。" : "粘贴一次 API Key 后即可在应用内直接选择模型；不需要 PowerShell 或外部脚本。";
  $("providerKeyDisconnect").disabled = status.source !== "secure_store";
  $("providerKeyConnect").textContent = status.source === "secure_store" ? "更新并验证" : "连接并验证";
}
// 获取脱敏连接状态，不把 API Key 从后端带回浏览器。
async function refreshProviderKeys() {
  try { state.providerAuth = await providerAuthApi("/status"); }
  catch (_) { state.providerAuth = { providers: {} }; }
  renderProviderKeyAuth();
}
// 用非秘钥元数据显示 ChatGPT 账号连接，不以页面“已连接”扩大 Runtime 权限。
function renderChatGPTAuth() {
  const isChatGPT = $("provider").value === "chatgpt";
  show("chatgptAuthBox", isChatGPT);
  if (!isChatGPT) return;
  const status = state.chatgptAuth?.status;
  const connected = !!status?.connected;
  $("chatgptAuthSummary").textContent = connected
    ? "ChatGPT 已连接"
    : "使用 ChatGPT 账号登录";
  $("chatgptAuthDetail").textContent = connected
    ? [status.email, status.plan, status.profile_id].filter(Boolean).join(" · ")
    : status?.reason === "client_not_configured"
      ? "尚未配置 Myth 的 OAuth client_id。请按 README 完成应用注册后登录；Myth 不会借用其他应用的客户端身份。"
      : "登录使用 PKCE/OIDC；token 仅保存在系统安全凭据库，资料与会话不含 token。";
  $("chatgptLogin").textContent = connected ? "重新授权" : "登录 ChatGPT";
  $("chatgptLogout").disabled = !connected;
}
// 获取公开认证状态供表单展示；失败仅降级展示，不把未知状态当作 token 可用。
async function refreshChatGPTAuth() {
  try {
    state.chatgptAuth = await authApi("/status");
  } catch (_) {
    state.chatgptAuth = null;
  }
  renderChatGPTAuth();
}
// 只展示 Claude OAuth 的公开元数据；client_id 是应用身份，token 不进入浏览器。
function renderClaudeAuth() {
  const isClaude = $("provider").value === "claude";
  show("claudeAuthBox", isClaude);
  if (!isClaude) return;
  const status = state.claudeAuth?.status;
  const connected = !!status?.connected;
  $("claudeAuthSummary").textContent = connected
    ? "Claude 已连接"
    : status?.client_id_configured
      ? "使用 Claude 账号登录"
      : "先配置 Myth 的 Claude OAuth 客户端";
  $("claudeAuthDetail").textContent = connected
    ? [status.email, status.organization, status.workspace].filter(Boolean).join(" · ") || "Claude OAuth 凭据已保存在系统安全凭据库。"
    : status?.client_id_configured
      ? "登录使用 authorization-code + PKCE S256；浏览器只取得脱敏状态，token 不写入项目文件。"
      : "填写你为 Myth 配置的 OAuth Client ID。Myth 不会复用 Claude Code 或其他应用的客户端身份。";
  $("claudeLogin").textContent = connected ? "重新授权 Claude" : "登录 Claude";
  $("claudeLogin").disabled = !status?.client_id_configured;
  $("claudeLogout").disabled = !connected;
}
// 读取 Claude 的非秘钥连接事实；失败保留未知状态，不伪造可用模型。
async function refreshClaudeAuth() {
  try { state.claudeAuth = await claudeAuthApi("/status"); }
  catch (_) { state.claudeAuth = null; }
  renderClaudeAuth();
}
// 在点击栈同步打开认证窗口，随后才创建挑战；noopener 防止供应商页面控制 Myth。
async function beginClaudeLogin() {
  let popup = window.open("about:blank", "myth-claude-login");
  if (popup) popup.opener = null;
  try {
    const started = await claudeAuthApi("/start", {});
    if (popup) popup.location.href = started.auth_url;
    else window.open(started.auth_url, "_blank", "noopener,noreferrer");
    toast("请在新窗口完成 Claude 登录，完成后会自动更新连接状态。");
    const until = Date.now() + 10 * 60 * 1000;
    // 轮询只确认本次 login_revision；旧账号连接不能冒充新挑战完成。
    const watch = async () => {
      await refreshClaudeAuth();
      if (state.claudeAuth?.status?.login_revision === started.login_id) {
        try { popup?.close(); } catch (_) {}
        await checkConnection(false);
        toast("Claude 已连接，可以直接在 Myth 内选择模型。");
        return;
      }
      if (Date.now() < until) setTimeout(watch, 1800);
    };
    watch();
  } catch (e) {
    try { popup?.close(); } catch (_) {}
    toast(e.message);
  }
}
// 在用户点击栈同步打开窗口，再请求 PKCE 入口，防止浏览器拦截异步弹窗；不使用外部 CLI/token 导入。
async function beginChatGPTLogin() {
  let popup = window.open("about:blank", "myth-chatgpt-login");
  if (popup) popup.opener = null;
  try {
    const started = await authApi("/start", {});
    if (popup) popup.location.href = started.auth_url;
    else window.open(started.auth_url, "_blank", "noopener,noreferrer");
    toast("请在新窗口完成 ChatGPT 登录，完成后会自动更新连接状态。");
    const until = Date.now() + 10 * 60 * 1000;
    // 每次只读取非秘钥状态确认当前挑战完成，超时不创建重复认证请求。
    const watch = async () => {
      await refreshChatGPTAuth();
      if (
        state.chatgptAuth?.status?.connected &&
        state.chatgptAuth?.status?.profile_id === started.profile_id &&
        state.chatgptAuth?.status?.login_revision === started.login_id
      ) {
        try { popup?.close(); } catch (_) {}
        await checkConnection(false);
        toast("ChatGPT 已连接");
        return;
      }
      if (Date.now() < until) setTimeout(watch, 1800);
    };
    watch();
  } catch (e) {
    try { popup?.close(); } catch (_) {}
    toast(e.message);
  }
}
// 展示体积，不把字符长度等同文件字节数。
function bytes(n) {
  return n < 1024
    ? `${n} B`
    : n < 1024 ** 2
      ? `${(n / 1024).toFixed(1)} KB`
      : `${(n / 1024 ** 2).toFixed(1)} MB`;
}
// 将 API 时间按浏览器本地显示；原始时间事实仍保留在服务端。
function date(s) {
  return s
    ? new Date(s.replace(" ", "T") + "Z").toLocaleString("zh-CN", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";
}
// 回复耗时只取后端给出的 wall-clock 元数据；缺失保持不显示，不用浏览器猜测模型内部推理时间。
function workedTime(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  if (value < 60) return `已用时 ${value} 秒`;
  const minutes = Math.floor(value / 60);
  const rest = value % 60;
  return `已用时 ${minutes} 分 ${rest} 秒`;
}
// 显式改变导航，状态变更由 hashchange 和 generation 管理。
function go(page, id) {
  location.hash = id ? `${page}/${encodeURIComponent(id)}` : page;
}
// 新对话只准备本地空白视图；真正 Session/Turn 由发送时的 API 创建。
function newChat(projectId) {
  saveDraft();
  state.drafts.delete("new");
  restoreDraft("new");
  state.session = null;
  state.id = null;
  state.threadKey = "";
  go("chat");
  route().then(() => {
    if (projectId) $("chatProject").value = projectId;
    saveDraft();
    $("prompt").focus();
  });
  closeNavigation();
}
// 归还导航焦点并撤销背景 inert；不会折叠 Runtime 桌面轨道。
function closeNavigation() {
  const wasOpen = $("sidebar").classList.contains("open");
  $("sidebar").classList.remove("open");
  show("sidebarShade", false);
  if ($("mainContent")) $("mainContent").inert = false;
  if ($("runtimeInspector")) $("runtimeInspector").inert = false;
  $("mobileMenu")?.setAttribute("aria-expanded", "false");
  if (wasOpen) $("mobileMenu")?.focus();
}
// 手机导航保留同一信息树；打开期间焦点和键盘不落入遮罩后的页面。
function bindNavigationDrawer() {
  $("mobileMenu")?.setAttribute("aria-expanded", "false");
  $("mobileMenu").onclick = () => {
    $("sidebar").classList.add("open");
    show("sidebarShade", true);
    $("mobileMenu").setAttribute("aria-expanded", "true");
    $("mainContent").inert = true;
    $("runtimeInspector").inert = true;
    $("sidebar").querySelector("a, button")?.focus();
  };
  $("sidebarShade").onclick = closeNavigation;
  $("sidebar").addEventListener("keydown", event => {
    if (!$("sidebar").classList.contains("open")) return;
    if (event.key === "Escape") { event.preventDefault(); closeNavigation(); return; }
    if (event.key !== "Tab") return;
    const controls = [...$("sidebar").querySelectorAll("a[href], button, input, summary, [tabindex]")]
      .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  });
  window.matchMedia("(min-width: 801px)").addEventListener("change", event => {
    if (event.matches) closeNavigation();
  });
}
// 草稿只活在本页内存，按会话隔离；pending 和正文一起保留，防止失败后换 request_id。
function saveDraft() {
  const key = state.composerKey;
  const draft = state.drafts.get(key) || {};
  Object.assign(draft, {
    text: $("prompt").value,
    attached: [...state.attached],
    pending: state.pending,
    projectId: $("chatProject").value,
    goalId: $("chatGoal")?.value || "",
  });
  state.drafts.set(key, draft);
  return draft;
}
// 切换会话只切换草稿视图；尚未准入的消息不会因轮询或路由改变而丢失。
function restoreDraft(key) {
  const draft = state.drafts.get(key) || { text: "", attached: [], pending: null, projectId: "", goalId: "" };
  state.composerKey = key;
  $("prompt").value = draft.text;
  state.attached = [...draft.attached];
  state.pending = draft.pending;
  $("chatProject").value = draft.projectId || "";
  if ($("chatGoal")) $("chatGoal").value = draft.goalId || "";
  return draft;
}
// 排除输入法组合、空正文、在途 POST 与不可直接追加的 Turn；WAITING_USER 只走对应回答入口。
function composerCanSend() {
  const status = state.session?.turns.at(-1)?.status;
  const blocked = ["RUNNING", "INTERRUPTED", "UNKNOWN", "PAUSED"].includes(status);
  return state.page === "chat" && !state.loadingSession && !state.busy && !state.composing && !blocked && !!$("prompt").value.trim();
}
// 输入控件只计算本地可交互状态；持续轮询不覆盖用户输入或焦点。
function updateComposer() {
  const input = $("prompt");
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 220) + "px";
  $("send").disabled = !composerCanSend();
  $("send").setAttribute("aria-busy", String(state.busy));
}
// 阅读中只显示回到底部入口；不在用户向上阅读时强行自动滚动。
function updateScrollButton() {
  const scroll = $("chatScroll");
  const distance = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight;
  show("scrollToBottom", state.page === "chat" && distance > 160);
}
// 原生 dialog 负责模态焦点围栏；记录启动点，关闭时回到仍存在的按钮。
function openDialog(id, focusId) {
  const dialog = $(id);
  if (!dialog || dialog.open) return;
  dialog._returnFocus = document.activeElement;
  dialog.showModal();
  if (focusId) $(focusId)?.focus();
}
// 复制结果有可观察反馈；剪贴板受限时保留可手工选择的原文。
async function copyText(text, button, success = "已复制") {
  try {
    await navigator.clipboard.writeText(text);
    const previous = button.textContent;
    button.textContent = "已复制";
    toast(success);
    setTimeout(() => { if (button.isConnected) button.textContent = previous; }, 1400);
  } catch (_) { toast("浏览器未允许复制，请选中文字后复制。"); }
}
// 命令菜单只导航或打开用户可见表单；搜索结果不自动执行任何工具。
let commandItems = [];
let selectedCommand = 0;
function commandCandidates(query) {
  const commands = [
    { label: "新建对话", detail: "开始一个新的讨论", icon: "plus", key: "⌘ ⇧ O", run: () => newChat() },
    { label: "目标与计划", detail: "查看长期目标与执行安排", icon: "goal", run: () => go("goals") },
    { label: "所有会话", detail: "搜索与整理历史讨论", icon: "chat", run: () => go("sessions") },
    { label: "项目", detail: "打开项目工作区", icon: "folder", run: () => go("projects") },
    { label: "知识库", detail: "检索与管理资料", icon: "book", run: () => go("knowledge") },
    { label: "模型与设置", detail: "连接模型、调整外观", icon: "settings", run: () => go("settings") },
    { label: "新建项目", detail: "为一项长期工作建立空间", icon: "folder", run: () => { go("projects"); projectDialog(); } },
  ];
  const sessions = (state.data?.sessions || []).map(s => ({
    label: s.title, detail: s.project_name || "会话", icon: "chat", run: () => go("chat", s.id),
  }));
  const projects = (state.data?.projects || []).map(p => ({
    label: p.name, detail: p.description || "项目", icon: "folder", run: () => go("projects", p.id),
  }));
  const all = query ? [...commands, ...sessions, ...projects] : [...commands, ...sessions.slice(0, 4)];
  const q = query.trim().toLowerCase();
  return (q ? all.filter(item => (item.label + " " + item.detail).toLowerCase().includes(q)) : all).slice(0, 30);
}
// 键盘选中态与 aria-activedescendant 同步，避免可见选择和读屏位置分离。
function selectCommand(index) {
  selectedCommand = index;
  $("commandResults").querySelectorAll(".command-item").forEach((button, i) => {
    button.classList.toggle("selected", i === index);
    button.setAttribute("aria-selected", String(i === index));
  });
  const option = $("command-option-" + index);
  if (option) {
    $("commandSearch").setAttribute("aria-activedescendant", option.id);
    option.scrollIntoView({ block: "nearest" });
  } else $("commandSearch").removeAttribute("aria-activedescendant");
}
// 关闭菜单后再执行显式命令，确保新表单获得正确焦点。
function runCommand(index) {
  const item = commandItems[index];
  if (!item) return;
  $("commandPalette").close();
  item.run();
}
// 使用节点文本构建本地检索结果；用户项目名不会成为 HTML。
function renderCommands() {
  commandItems = commandCandidates($("commandSearch").value);
  $("commandResults").replaceChildren();
  commandItems.forEach((item, index) => {
    const row = el("button", "command-item");
    row.type = "button";
    row.id = "command-option-" + index;
    row.setAttribute("role", "option");
    row.setAttribute("aria-selected", "false");
    const main = el("span", "command-item-main");
    main.append(el("strong", "", item.label), el("small", "", item.detail));
    row.append(icon(item.icon), main);
    if (item.key) row.append(el("span", "command-key", item.key));
    row.onclick = () => runCommand(index);
    row.onmouseenter = () => selectCommand(index);
    $("commandResults").append(row);
  });
  if (!commandItems.length) $("commandResults").append(el("p", "command-empty", "没有找到匹配结果"));
  selectCommand(0);
}
// 搜索入口在打开时重建当前目录，不引入新的后端查询或执行机会。
function openCommandPalette() {
  if (!$("commandPalette")) return;
  $("commandSearch").value = "";
  renderCommands();
  openDialog("commandPalette", "commandSearch");
}
// 统一空态的标题/原因/明确下一步，不用不可操作的占位卡片。
function empty(parent, title, description, name = "folder", action, actionLabel) {
  const n = el("div", "empty-card");
  n.append(icon(name), el("h3", "", title), el("p", "", description));
  if (action && actionLabel) {
    const button = el("button", "secondary", actionLabel);
    button.type = "button";
    button.onclick = action;
    n.append(button);
  }
  parent.append(n);
}
// 仅提供服务端可见项目选项；选择本身不授予本机文件权限。
function fillProjects(select, emptyText, selected = "") {
  select.replaceChildren();
  const o = el("option", "", emptyText);
  o.value = "";
  select.append(o);
  for (const p of state.data?.projects || []) {
    const o = el("option", "", p.name);
    o.value = p.id;
    select.append(o);
  }
  select.value = selected;
}
// 渲染导航与最近会话投影；不会因查看列表重启任何 Run。
function renderSidebar() {
  document.querySelectorAll(".navigation a").forEach((a) => {
    const active = a.dataset.page === state.page;
    a.classList.toggle("active", active);
    if (active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  const list = $("recentSessions");
  list.replaceChildren();
  const sessions = state.data?.sessions || [];
  sessions.slice(0, 12).forEach((s) => {
    const a = el("a", "recent-item");
    a.href = `#chat/${encodeURIComponent(s.id)}`;
    a.classList.toggle("active", s.id === state.id && state.page === "chat");
    if (s.pinned) a.append(icon("pin", "icon pin"));
    const text = el("span", "recent-title", s.title);
    a.append(text);
    list.append(a);
  });
  if (!sessions.length)
    list.append(el("p", "recent-empty", "还没有会话"));
  $("sessionCount").textContent = sessions.length;
  if ($("projectCount")) $("projectCount").textContent = state.data?.projects?.length || 0;
  if ($("knowledgeCount")) $("knowledgeCount").textContent = state.data?.documents?.length || 0;
  if ($("goalCount")) $("goalCount").textContent = state.data?.goals?.length || 0;
  $("profileName").textContent = "本机工作区";
}
// 只读取 bootstrap；写入、模型探测与用户表单分别管理，避免轮询副作用。
async function refresh() {
  state.data = await api("");
  renderSidebar();
  renderConnection();
}
// 按实际 Provider 能力选择认证说明和可用字段，不把设置页初始化当作已连接。
function settingsProviderMode() {
  const provider = $("provider").value;
  const isOllama = provider === "ollama";
  show("ollamaField", isOllama);
  $("ollamaUrl").disabled = !isOllama;
  $("modelHelp").textContent = provider === "claude"
    ? "登录后读取账号可用模型；也可以填写该账号已获权限的精确模型 ID。"
    : provider === "chatgpt"
    ? "登录后读取 ChatGPT 可用模型；Thinking 与上下文限制以实际目录为准。"
    : provider === "deepseek"
      ? "DeepSeek 能力随模型变化；思考开关与档位只在当前模型支持时显示。"
      : provider === "moonshot"
        ? "Kimi 能力随模型变化；连接后读取可用模型，也支持填写精确模型 ID。"
        : isOllama
        ? "从本机 Ollama 读取已安装模型；只对实际报告支持的模型开放思考设置。"
        : "填写精确模型 ID；连接后读取可用目录与能力。";
}
// 页面明确编辑的连接目标；后台活跃 Run 的历史设置不允许反过来覆盖表单。
function connectionSettings() {
  const settings = state.data?.settings || {};
  if (state.page === "settings") return { ...settings, ...settingsPayload() };
  const turnSettings = state.session?.turns.at(-1)?.settings;
  return { ...settings, ...(turnSettings || {}) };
}
// 连接检查绑定 Provider 与端点；目标改变后旧成功结果不能显示成新目标已连接。
function connectionIdentity(settings) {
  return JSON.stringify([
    settings.provider || "ollama",
    settings.provider === "ollama" ? settings.ollama_url || "" : "",
  ]);
}
// 用户改动连接字段时显式失效上一次目录结果，不触发新的联网检查。
function invalidateConnection() {
  state.connection = null;
  $("connectionResult").textContent = "";
  $("connectionResult").classList.remove("bad");
  renderConnection();
  renderAdaptiveModelSettings();
}
// 只显示与当前目标匹配的连接事实；首屏未知保持待检查，不制造成功反馈。
function renderConnection() {
  const settings = connectionSettings();
  const provider = settings.provider || "ollama";
  const result = state.connection?.identity === connectionIdentity(settings) ? state.connection : null;
  const readiness = result ? !!result.ready : null;
  $("connectionDot").className = "connection-dot" + (readiness === true ? " connected" : readiness === false ? " disconnected" : "");
  $("modelLabel").textContent = settings.model || "选择模型";
  const label = provider === "claude" ? "Claude OAuth" : provider === "chatgpt" ? "ChatGPT OAuth" : provider === "deepseek" ? "DeepSeek API" : provider === "moonshot" ? "Kimi API" : provider === "openai" ? "OpenAI API" : "Ollama";
  $("connectionLabel").textContent = label + (readiness === true ? " 已连接" : readiness === false ? " 未连接" : " 待检查");
  $("welcomeConnectionText").textContent = readiness === true
    ? settings.model ? "已连接到 " + settings.model : "已连接，请选择一个模型"
    : readiness === false ? "模型未连接，检查连接后即可开始对话。" : "选择模型并检查连接，开始第一段对话。";
}
// 读取目录时冻结连接身份；用户中途切换 Provider 后迟到结果丢弃而不是误填新表单。
async function checkConnection(quiet = false) {
  if (state.checkingConnection) return;
  settingsProviderMode();
  const payload = settingsPayload();
  const identity = connectionIdentity(payload);
  state.checkingConnection = true;
  $("checkConnection").disabled = true;
  $("checkConnection").textContent = "正在连接…";
  $("connectionResult").textContent = "";
  try {
    const result = await api("/connection", payload);
    if (connectionIdentity(settingsPayload()) !== identity) return;
    state.connection = { ...result, identity };
    state.modelCapabilities = result.details?.model_capabilities || {};
    const models = result.details?.models || [];
    $("modelList").replaceChildren();
    models.forEach((m) => {
      const o = el("option"); o.value = m; $("modelList").append(o);
    });
    if (!$("model").value && models[0]) $("model").value = models[0];
    const message = result.ready
      ? `${models.length} 个可用模型 · 连接正常`
      : result.details?.error || "连接失败，请检查配置。";
    $("connectionResult").textContent = message;
    $("connectionResult").classList.toggle("bad", !result.ready);
    renderConnection();
    renderChatGPTAuth();
    renderClaudeAuth();
    renderProviderKeyAuth();
    renderAdaptiveModelSettings();
    poolRefreshPrices();
    if (!quiet) toast(result.ready ? "连接正常，模型列表已更新。" : message);
  } catch (e) {
    if (connectionIdentity(settingsPayload()) === identity) {
      state.connection = { ready: false, identity };
      $("connectionResult").textContent = e.message;
      $("connectionResult").classList.add("bad");
      renderConnection();
    }
    if (!quiet) toast(e.message);
  } finally {
    state.checkingConnection = false;
    $("checkConnection").disabled = false;
    $("checkConnection").textContent = "检查连接";
  }
}
// 模型档位文案只映射已报告的能力值；无报告不猜测 OpenAI/Claude/Kimi 的支持范围。
function reasoningLabel(value) {
  return ({
    none: "不启用额外思考", off: "不启用额外思考", no: "不启用额外思考", false: "不启用额外思考",
    minimal: "最小", low: "低", medium: "中", high: "高", xhigh: "很高", max: "最大",
  })[String(value).toLowerCase()] || value;
}
// 优先使用最近一次同连接的目录能力；DeepSeek 的确定性模型规则是离线后备，而不是全 Provider 通用档位。
function selectedModelCapability(provider, model) {
  const sameConnection = state.connection?.identity === connectionIdentity({ provider, ollama_url: $("ollamaUrl").value });
  const exact = sameConnection ? state.connection?.details?.model_capabilities?.[model] : null;
  if (exact) return exact;
  if (provider === "deepseek") {
    const key = String(model || "").toLowerCase();
    if (key === "deepseek-v4-pro") return { context_window: 1_000_000, max_output_tokens: 393216, reasoning: { off: "none", levels: ["high", "max"], default: "high" }, source: "provider mapping" };
    if (key === "deepseek-v4-flash") return { context_window: 1_000_000, max_output_tokens: 393216, reasoning: { off: "none", levels: ["high"], default: "high" }, source: "provider mapping" };
    if (key === "deepseek-chat") return { context_window: 131072, max_output_tokens: 8192, source: "provider mapping" };
    if (key === "deepseek-reasoner") return { context_window: 131072, max_output_tokens: 65536, reasoning: { off: "none", levels: ["low", "high"], default: "high" }, source: "provider mapping" };
  }
  return {};
}
// 由真实能力配置思考选择器；缺能力时只保留已保存/正在执行的显式值，不补造可选档位。
function populateReasoningSelect(select, capability, current) {
  const reasoning = capability?.reasoning || {};
  const levels = Array.isArray(reasoning.levels) ? reasoning.levels.filter((item) => typeof item === "string" && item) : [];
  select.replaceChildren();
  if (reasoning.off) {
    const off = el("option", "", "不启用额外思考");
    off.value = "__off__";
    off.dataset.value = reasoning.off;
    select.append(off);
  }
  levels.forEach((level) => {
    const option = el("option", "", reasoningLabel(level));
    option.value = level;
    select.append(option);
  });
  if (!reasoning.off && !levels.length) {
    const option = el("option", "", current ? `当前设置 · ${reasoningLabel(current)}` : "当前模型未报告可调思考档位");
    option.value = current || "";
    select.append(option);
    select.disabled = true;
    return;
  }
  const candidates = [...select.options].map((option) => option.value);
  const selected = current === reasoning.off ? "__off__" : current;
  if (current && !candidates.includes(selected)) {
    // 手动保存的原始设置不因能力目录暂缺而静默删除；提交时由服务端再次核对。
    const raw = el("option", "", `已保存设置 · ${reasoningLabel(current)}`);
    raw.value = current;
    select.append(raw);
  }
  select.value = selected && [...select.options].some((option) => option.value === selected)
    ? selected
    : reasoning.default || (reasoning.off ? "__off__" : levels[0] || "");
  select.disabled = false;
}
// disabled 表示没有可供选择的新档位，不表示抹掉已有设置。
function reasoningSelectionValue(select) {
  return select.value === "__off__" ? select.options[0]?.dataset.value || "none" : select.value || null;
}
// 运行时控制始终相对最新模型/Control 投影计算档位；不会沿用设置页另一个模型的能力。
function renderTurnReasoning(turn, thinking) {
  const provider = turn?.settings?.provider || state.data?.settings?.provider || "ollama";
  const model = $("turnModelInput").value.trim() || turn?.control?.model || turn?.settings?.model || "";
  populateReasoningSelect($("turnThinkingInput"), selectedModelCapability(provider, model), thinking);
}
// 表单尺寸与最大值来自能力目录，但仅在值仍由目录自动填入时更新；不覆盖用户手动输入。
function renderAdaptiveModelSettings() {
  settingsProviderMode();
  const provider = $("provider").value;
  const model = $("model").value.trim();
  const sameIdentity = state.reasoningModelIdentity === `${provider}:${model}`;
  const current = sameIdentity
    ? reasoningSelectionValue($("reasoningSetting"))
    : (state.data?.settings?.provider === provider && state.data?.settings?.model === model ? state.data.settings.thinking : null);
  const capability = selectedModelCapability(provider, model);
  populateReasoningSelect($("reasoningSetting"), capability, current);
  state.reasoningModelIdentity = `${provider}:${model}`;
  const levels = capability.reasoning?.levels || [];
  $("reasoningHelp").textContent = levels.length
    ? `当前模型报告 ${levels.map(reasoningLabel).join(" / ")}${capability.reasoning?.off ? "，支持关闭额外思考。" : "。"}`
    : "未报告可调档位；Myth 不会根据模型名称猜测远端支持。已保存设置保持原样。";
  const output = Number(capability.max_output_tokens) || 0;
  const nextMax = output > 0 ? String(Math.min(output, 393216)) : "393216";
  const previousMax = $("maxTokens").dataset.catalogMax;
  $("maxTokens").max = nextMax;
  if (previousMax !== nextMax && Number($("maxTokens").value) > Number(nextMax)) $("maxTokens").value = nextMax;
  $("maxTokens").dataset.catalogMax = nextMax;
  $("maxTokensHelp").textContent = output > 0
    ? `当前模型单次输出上限 ${output.toLocaleString()} token。`
    : "此值是 Myth 的单次输出限制；远端可能报告更低上限。";
  const reportedContext = Number(capability.context_window) || 0;
  const autoContext = $("contextWindow").dataset.auto;
  if (reportedContext > 0 && (!$("contextWindow").value || $("contextWindow").value === autoContext)) {
    $("contextWindow").value = String(reportedContext);
    $("contextWindow").dataset.auto = String(reportedContext);
  }
  $("contextWindowHelp").textContent = reportedContext > 0
    ? `模型目录报告 ${reportedContext.toLocaleString()} token；可手动使用更保守的窗口。`
    : "模型未报告上下文窗口；此值是显式本地预算，不代表远端能力。";
  const metadata = {
    provider,
    model: model || "未选择",
    capability_source: capability.source || (Object.keys(capability).length ? "provider catalog" : "not_reported"),
    reported_context_window: reportedContext || null,
    reported_max_output_tokens: output || null,
    reasoning: capability.reasoning || null,
  };
  $("modelCapabilitySummary").textContent = Object.keys(capability).length
    ? "模型特性与来源" : "模型尚未报告能力";
  $("modelCapabilityDetail").textContent = JSON.stringify(metadata, null, 2);
}
// 读取明确的表单值形成提交 payload；模型池/密钥管理各由专用入口处理。
function settingsPayload() {
  return {
    provider: $("provider").value,
    model: $("model").value.trim(),
    ollama_url: $("ollamaUrl").value.trim(),
    max_steps: Number($("maxSteps").value),
    max_output_tokens: Number($("maxTokens").value),
    context_window: Number($("contextWindow").value),
    thinking: reasoningSelectionValue($("reasoningSetting")),
    system_prompt: $("systemPrompt").value,
  };
}
// 只在进入设置页或首次启动时回填，普通状态轮询不会覆盖未保存编辑。
function loadSettings() {
  const s = state.data.settings;
  $("provider").value = s.provider;
  $("model").value = s.model;
  $("ollamaUrl").value = s.ollama_url;
  $("maxSteps").value = s.max_steps;
  $("maxTokens").value = s.max_output_tokens;
  $("contextWindow").value = s.context_window;
  delete $("contextWindow").dataset.auto;
  state.reasoningModelIdentity = null;
  $("systemPrompt").value = s.system_prompt;
  $("settingsSaved").textContent = "";
  settingsProviderMode();
  renderChatGPTAuth();
  renderClaudeAuth();
  renderProviderKeyAuth();
  renderAdaptiveModelSettings();
}
// 受限 Markdown 行内渲染：只创建文本、code、strong/em 与显式 http(s) 链接，不接受原始 HTML。
function inline(parent, text) {
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\(https?:\/\/[^)]+\))/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last)
      parent.append(document.createTextNode(text.slice(last, m.index)));
    const x = m[0];
    let n;
    if (x.startsWith("`")) n = el("code", "", x.slice(1, -1));
    else if (x.startsWith("**")) n = el("strong", "", x.slice(2, -2));
    else if (x.startsWith("*")) n = el("em", "", x.slice(1, -1));
    else {
      const a = x.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
      n = el("a", "", a[1]);
      n.href = a[2];
      n.target = "_blank";
      n.rel = "noopener noreferrer";
    }
    parent.append(n);
    last = m.index + x.length;
  }
  parent.append(document.createTextNode(text.slice(last)));
}
// 行级 Markdown 使用 DOM 节点并保持代码可复制；错误/未知内容作为原文，不执行脚本。
function markdown(parent, text) {
  const lines = String(text).split("\n");
  let code = null,
    language = "",
    paragraph = [];
  // 延后合并普通段落，代码围栏与列表边界先落盘到 DOM，避免丢失换行或跨段解释。
  const flush = () => {
    if (paragraph.length) {
      const p = el("p");
      inline(p, paragraph.join("\n"));
      p.style.whiteSpace = "pre-wrap";
      parent.append(p);
      paragraph = [];
    }
  };
  // 代码块正文只进 textContent；复制反馈不改写代码证据。
  const codeBlock = () => {
    const box = el("div", "code-block"),
      head = el("div", "code-head");
    head.append(el("span", "", language || "code"));
    const b = el("button", "code-copy", "复制");
    b.prepend(icon("file"));
    const value = code.join("\n");
    b.onclick = () => copyText(value, b, "已复制代码");
    head.append(b);
    box.append(head, el("pre", "", value));
    parent.append(box);
  };
  for (const line of lines) {
    if (line.startsWith("```")) {
      if (code !== null) {
        codeBlock();
        code = null;
      } else {
        flush();
        code = [];
        language = line.slice(3).trim();
      }
      continue;
    }
    if (code !== null) {
      code.push(line);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flush();
      const h = el(heading[1].length < 3 ? "h2" : "h3");
      inline(h, heading[2]);
      parent.append(h);
    } else if (!line.trim()) flush();
    else if (/^[-*]\s/.test(line) || /^\d+\.\s/.test(line)) {
      flush();
      const p = el("p");
      p.style.paddingLeft = "16px";
      inline(p, line.replace(/^[-*]\s/, "• "));
      parent.append(p);
    } else paragraph.push(line);
  }
  if (code !== null) codeBlock();
  flush();
}
// 按真实步骤投影可折叠工具过程；只读 UI 不重新执行工具或补造收据。
function toolGroup(turn) {
  const steps = turn.activities.filter(
    (s) => s.decision.decision_type === "tool_call",
  );
  if (!steps.length) return null;
  const details = el("details", "tool-group");
  details.dataset.turn = turn.run_id;
  const summary = el("summary");
  summary.append(icon("terminal"), el("span", "", `执行了 ${steps.length} 个操作`));
  details.append(summary);
  steps.forEach((s) => {
    const item = el("div", "tool-item"),
      d = s.decision,
      r = s.result;
    item.append(
      el("strong", "", `${s.step}. ${d.capability_id || "工具"} · ${s.state}`),
    );
    if (d.reason) item.append(el("p", "muted", d.reason));
    if (r) {
      const content = r.content ?? r.feedback ?? r.error ?? JSON.stringify(r, null, 2);
      const full = String(content);
      const output = el("pre", "", full.slice(0, 3000));
      item.append(output);
      if (full.length > 3000) {
        const more = el("button", "tool-truncation", "显示完整结果");
        more.type = "button";
        more.setAttribute("aria-expanded", "false");
        more.onclick = () => {
          const expanded = more.getAttribute("aria-expanded") !== "true";
          output.textContent = expanded ? full : full.slice(0, 3000);
          more.setAttribute("aria-expanded", String(expanded));
          more.textContent = expanded ? "收起长结果" : "显示完整结果";
        };
        item.append(more);
      }
    }
    details.append(item);
  });
  return details;
}
// 产物入口绑定已结算 decision_id，下载由服务器再次核对真实对象摘要。
function artifactCard(a) {
  const link = `/api/workspace/artifacts/${encodeURIComponent(a.decision_id)}`;
  const card = el("a", "artifact-card");
  card.href = link;
  card.download = a.name;
  const mark = el("span", "artifact-icon");
  mark.append(icon("file"));
  const info = el("div");
  info.append(el("strong", "", a.name), el("small", "", "已保存的产物 · " + bytes(a.bytes || 0)));
  const download = el("span", "download", "下载");
  download.append(icon("download"));
  card.append(mark, info, download);
  return card;
}
// 持久事实不变时只更新执行中的时钟，不能用心跳重建历史消息打断阅读与选择。
function liveTurnLabel(turn) {
  if (!turn.driver_active) return "Driver 已断开，等待恢复";
  const elapsed = turn.reply_timing?.elapsed_seconds;
  return "正在处理…" + (typeof elapsed === "number" && Number.isFinite(elapsed) && elapsed >= 0 ? " · " + workedTime(elapsed) : "");
}
// 一次投影建立临时索引，避免每条消息重扫所有 Turn/产物；不持久化或改写输入。
function indexThread(session) {
  const turns = new Map(), artifacts = new Map();
  for (const turn of session.turns) {
    if (!turns.has(turn.run_id)) turns.set(turn.run_id, turn);
  }
  for (const artifact of session.artifacts) {
    const items = artifacts.get(artifact.run_id) || [];
    items.push(artifact);
    artifacts.set(artifact.run_id, items);
  }
  return { turns, artifacts };
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
  const indexed = indexThread(session);
  session.messages.forEach((message) => {
    const turn = indexed.turns.get(message.run_id);
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
      (indexed.artifacts.get(turn.run_id) || [])
        .filter((a) => !emitted.has(a.decision_id))
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
    if (last.driver_active) typing.append(brandMark(true));
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
        ? "结果尚未确认；请先核对已发出的操作，不要重复发送。"
        : status === "INTERRUPTED"
          ? "Driver 已中断；断点已保存，可以继续。"
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
        (["FAILED", "BUDGET_EXHAUSTED"].includes(status) ? " error"
          : ["UNKNOWN", "INTERRUPTED"].includes(status) ? " warning" : "");
      $("turnNotice").append(el("span", "", text));
      // 默认说明下一步，技术原因仍可展开；UNKNOWN 不是已知失败。
      if (turn.error && turn.error !== text) {
        const detail = el("details", "turn-detail");
        detail.append(el("summary", "", "查看原因"), el("pre", "", turn.error));
        $("turnNotice").append(detail);
      }
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
        loading.prepend(brandMark(true));
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
  .forEach((a) => (a.onclick = closeNavigation()));
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
