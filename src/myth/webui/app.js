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
  // 脱敏账号投影；凭据保存在系统库。
  chatgptAuth: null,
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
  // 当前轮询定时器句柄；与业务 Run 生命周期独立。
  poll: null,
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
document
  .querySelectorAll("[data-icon]")
  .forEach((e) => e.replaceWith(icon(e.dataset.icon)));
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
  $("sidebar").classList.remove("open");
  show("sidebarShade", false);
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
  const first = el("option", "", "不绑定 Goal");
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
  box.replaceChildren();
  const sessions = state.data.sessions.slice(0, 9);
  if (!sessions.length)
    box.append(el("p", "recent-empty", "还没有对话。\n从一个问题开始吧。"));
  sessions.forEach((s) => {
    const a = el("a", "recent-item" + (state.id === s.id ? " active" : ""));
    a.href = `#chat/${s.id}`;
    if (s.pinned) a.append(el("span", "pin", "⌑"));
    a.append(document.createTextNode(s.title));
    a.onclick = closeNavigation;
    box.append(a);
  });
  document
    .querySelectorAll("[data-page]")
    .forEach((a) =>
      a.classList.toggle("active", a.dataset.page === state.page),
    );
}
// 刷新共享产品投影；并发页面请求通过各自 generation 防止迟到覆写。
async function refresh() {
  state.data = await api("");
  renderSidebar();
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
    thinking: $("thinking").checked,
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
  $("thinking").checked = s.thinking === true;
  renderChatGPTAuth();
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
        ? "使用 OpenAI 官方 Sign in with ChatGPT；凭据保存在系统安全凭据库。"
        : s.reason || "需要登录";
    show("chatgptLogout", false);
    $("chatgptLogin").textContent = "Continue with ChatGPT";
  }
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
// 呈现当前检查报告；连接 ready 不能当作某个任务已完成。
function renderConnection() {
  const c = state.connection;
  $("connectionDot").className =
    "connection-dot " + (c ? (c.ready ? "connected" : "disconnected") : "");
  const activeModel = state.session?.turns?.at(-1)?.settings?.model;
  const provider = state.data.settings.provider;
  $("modelLabel").textContent =
    activeModel ||
    state.data.settings.model ||
    (provider === "ollama"
      ? "连接 Ollama"
      : provider === "chatgpt"
        ? "连接 ChatGPT"
        : "连接模型");
  show("welcomeConnection", !state.data.settings.model || (c && !c.ready));
  if (c) {
    const fallback =
      provider === "ollama"
        ? "未连接，请确认 Ollama 正在运行。"
        : provider === "chatgpt"
          ? "ChatGPT 尚未完成授权或当前计划不可用。"
          : "模型提供方尚未就绪。";
    $("connectionResult").textContent = c.ready
      ? `已连接 · ${c.details.models?.length || 0} 个可用模型`
      : c.details.error || c.details.reason || fallback;
    $("connectionResult").className =
      "connection-result" + (c.ready ? "" : " bad");
    $("modelOptions").replaceChildren();
    (c.details.models || []).forEach((m) => {
      const o = el("option");
      o.value = m;
      $("modelOptions").append(o);
    });
  }
}
// 提交明确当前配置做连接检查；模型列表只是可用目录，保存设置后影响未来工作。
async function checkConnection(auto = false) {
  $("checkConnection").disabled = true;
  try {
    const payload = auto ? state.data.settings : settingsPayload();
    state.connection = await api("/connection", payload);
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
    toast(e.message);
  } finally {
    $("checkConnection").disabled = false;
  }
}
// 准备新对话展示并可固定项目；实际会话/Turn 由发送入口创建。
async function newChat(projectId = null) {
  state.session = null;
  state.id = null;
  state.threadKey = "";
  state.attached = [];
  state.pending = null;
  go("chat");
  fillProjects($("chatProject"), "独立对话", projectId || "");
  fillGoals($("chatGoal"), "");
  renderChat(null);
  $("prompt").focus();
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
      const language = newline >= 0 ? part.slice(0, newline) : "code";
      const code = newline >= 0 ? part.slice(newline + 1) : part;
      const block = el("div", "code-block"),
        head = el("div", "code-head"),
        copy = el("button", "", "复制");
      copy.onclick = () =>
        navigator.clipboard
          .writeText(code)
          .then(() => toast("已复制代码"))
          .catch(() => toast("浏览器未允许剪贴板访问。"));
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
  a.append(mark, info, el("span", "download", "下载 ↗"));
  return a;
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
      t.reply_timing,
    ]),
    session.artifacts,
  ]);
  if (signature === state.threadKey) return;
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
    if (message.role === "assistant")
      row.append(el("div", "message-avatar", "✳"));
    const main = el("div", "message-main"),
      body = el("div", "message-content");
    main.append(el("div", "message-label", "Myth"));
    if (message.role === "user") body.textContent = message.content;
    else markdown(body, message.content);
    main.append(body);
    if (message.role === "assistant") {
      const actions = el("div", "message-actions"),
        copy = el("button", "", "复制"),
        save = el("a", "", "保存为 Markdown ↗");
      copy.onclick = () =>
        navigator.clipboard
          .writeText(message.content)
          .then(() => toast("已复制回答"))
          .catch(() => toast("浏览器未允许剪贴板访问。"));
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
          const b = el("button", "", `↳ ${source.title}`);
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
    for (let i = 0; i < 3; i++) typing.append(el("span", "typing-dot"));
    const liveElapsed = last.reply_timing?.elapsed_seconds;
    typing.append(
      el(
        "span",
        "",
        last.driver_active
          ? "正在思考与处理…" +
              (liveElapsed !== undefined ? " · " + workedTime(liveElapsed) : "")
          : "这一轮已中断",
      ),
    );
    $("thread").append(typing);
  }
  if (nearBottom || state.justSent) {
    scroll.scrollTop = scroll.scrollHeight;
    state.justSent = false;
  }
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
      !(control.stopped ?? control.aborted) &&
      status === "RUNNING",
  );
  show("resumeTurn", !!turn && control.paused && status === "PAUSED");
  $("steerTurn").disabled =
    !turn ||
    (control.stopped ?? control.aborted) ||
    ["COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"].includes(status);
  $("compactTurn").disabled =
    !turn || (control.stopped ?? control.aborted) || status !== "RUNNING";
  $("stopRun").disabled =
    !turn ||
    (control.stopped ?? control.aborted) ||
    ["COMPLETED", "FAILED", "CANCELLED", "BUDGET_EXHAUSTED"].includes(status);

  show("stopTurn", !!active && !(control.stopped ?? control.aborted));
  show("send", !active || status === "WAITING_USER");
  $("send").disabled = state.busy;
  $("prompt").placeholder =
    status === "WAITING_USER"
      ? "回复这个问题…"
      : status === "PAUSED"
        ? "Run 已暂停。Resume 后继续。"
        : status === "INTERRUPTED"
          ? "Run 已中断；请从 durable checkpoint 继续。"
          : "给 Myth 一个任务，或继续当前对话…";

  if (turn?.settings?.model) $("modelLabel").textContent = turn.settings.model;
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
      status === "UNKNOWN"
        ? turn.error || "存在结果不明确的执行，必须先核对再继续。"
        : status === "INTERRUPTED"
          ? turn.error || "Driver 已中断；durable checkpoint 已保留，可以继续。"
          : status === "PAUSED"
            ? "Run 已暂停；已发出的调用仍会保留真实晚到结果。"
            : detached && leaseRemaining > 0
              ? "执行 Driver 已断开，等待租约过期后进入安全恢复状态（约 " +
                leaseRemaining +
                " 秒）。"
              : detached
                ? "执行 Driver 已断开；正在确认最后一个 durable checkpoint。"
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
  renderChat(session);
  renderSidebar();
}
// 显示本轮显式附加资料并允许移除；这只是未来发送选择，不倒写历史快照。
function renderAttachments() {
  $("attachmentChips").replaceChildren();
  state.attached.forEach((d, i) => {
    const chip = el("div", "attachment-chip");
    chip.append(icon("file"), el("span", "", d.title));
    const remove = el("button", "", "×");
    remove.setAttribute("aria-label", `移除 ${d.title}`);
    remove.onclick = () => {
      state.attached.splice(i, 1);
      renderAttachments();
    };
    chip.append(remove);
    $("attachmentChips").append(chip);
  });
}
// 冻结正文/附件/设置指纹并复用稳定 request_id；回答匹配 question_id，成功后才清本轮输入。
async function sendMessage(event) {
  event?.preventDefault();
  if (state.busy) return;
  const text = $("prompt").value.trim();
  if (!text) return;
  const generation = state.generation,
    projectId = $("chatProject").value || null,
    attachments = [...state.attached];
  let sid = state.id,
    session = state.session;
  state.busy = true;
  $("send").disabled = true;
  try {
    if (!state.data.settings.model) {
      go("settings");
      throw new Error("先检查模型连接并选择一个可用模型。");
    }
    if (!sid) {
      session = await api("/sessions", { project_id: projectId });
      sid = session.id;
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
        state.data.settings,
      ]);
      if (state.pending?.fingerprint !== fingerprint)
        state.pending = { fingerprint, id: crypto.randomUUID() };
      const requestId = state.pending.id;
      await api(`/sessions/${sid}/messages`, {
        text: message,
        request_id: requestId,
        document_ids: attachments.map((d) => d.id),
        goal_id: $("chatGoal")?.value || null,
      });
      if (state.pending?.id === requestId) state.pending = null;
    }
    await refresh();
    if (
      state.generation === generation &&
      state.page === "chat" &&
      state.id === sid
    ) {
      if ($("prompt").value.trim() === text) $("prompt").value = "";
      state.attached = [];
      state.justSent = true;
      await openSession(sid, generation);
      renderAttachments();
    }
  } catch (e) {
    toast(e.message);
  } finally {
    state.busy = false;
    $("send").disabled = false;
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
  const thinking = control.thinking;
  $("turnThinkingInput").value =
    thinking === true
      ? "on"
      : thinking === false
        ? "off"
        : thinking || "default";
  $("controlRevision").textContent =
    `control revision ${control.revision || 1}`;
  if (!$("controlDialog").open) $("controlDialog").showModal();
}

// 渲染会话列表及恢复标记；归档改变导航可见性，执行控制另走 Control。
function renderSessions(list = state.data.sessions) {
  const query = $("sessionSearch").value.trim().toLowerCase();
  $("sessionCards").replaceChildren();
  const matches = list.filter((s) =>
    (s.title + " " + (s.preview || "")).toLowerCase().includes(query),
  );
  if (!matches.length) {
    empty(
      $("sessionCards"),
      state.archived ? "归档里还没有会话" : "还没有会话",
      "开始一个问题，讨论会自动保存。",
      "chat",
      () => newChat(),
      "开始对话",
    );
    return;
  }
  matches.forEach((s) => {
    const card = el("div", "session-card"),
      mark = el("span", "session-icon");
    mark.append(icon("chat"));
    const info = el("div", "session-info");
    info.append(
      el("strong", "", (s.pinned ? "⌑ " : "") + s.title),
      el("p", "", s.preview || "这个会话还没有消息。"),
    );
    info.onclick = () => go("chat", s.id);
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
        await api(`/sessions/${s.id}`, { archived: false });
        await refresh();
        await renderSessionPage();
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
  const list = state.archived
    ? (await api("/sessions?archived=1")).sessions
    : state.data.sessions;
  state.sessionList = list;
  $("activeSessions").classList.toggle("selected", !state.archived);
  $("archivedSessions").classList.toggle("selected", state.archived);
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
  $("sessionDialog").showModal();
}
// 显示保存的项目与统计；项目根访问始终由服务端受限执行器负责。
function renderProjects() {
  $("projectCards").replaceChildren();
  state.data.projects.forEach((p) => {
    const a = el("a", "project-card");
    a.href = `#projects/${p.id}`;
    const mark = el("span", "project-card-icon");
    mark.append(icon("folder"));
    a.append(
      mark,
      el("h2", "", p.name),
      el("p", "", p.description || "为这个项目关联文件、知识和持续的讨论。"),
    );
    const foot = el("div", "project-card-foot");
    foot.append(
      el("span", "", `${p.session_count} 个会话 · ${p.document_count} 份资料`),
      el("span", "", "打开 ↗"),
    );
    a.append(foot);
    $("projectCards").append(a);
  });
  const add = el("button", "project-card new-project-card");
  add.append(icon("plus"), el("strong", "", "创建一个项目"));
  add.onclick = () => projectDialog();
  $("projectCards").append(add);
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
  $("projectDialog").showModal();
}
// 连接项目详情、知识、会话与文件投影；不存在/归档身份显式失败。
async function renderProject(pid) {
  const project = state.data.projects.find((p) => p.id === pid);
  if (!project) throw new Error("项目不存在或已归档。");
  state.project = project;
  $("pageTitle").textContent = project.name;
  $("projectName").textContent = project.name;
  $("projectDescription").textContent =
    project.description || "文件、指令、资料与对话，共同构成项目上下文。";
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
      const back = el("button", "file-row", "← 返回上一级");
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
        el("small", "", f.type === "directory" ? "↗" : bytes(f.bytes)),
      );
      row.onclick =
        f.type === "directory"
          ? () => projectFiles(f.path)
          : () => {
              newChat(pid);
              $("prompt").value =
                `请读取项目文件 ${f.path}，概括内容并说明关键点。`;
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
      el("p", "empty-inline", "为项目添加资料，让回答有依据。"),
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
      el("strong", "", value.toString().padStart(2, "0")),
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
      "把资料带进工作区",
      "选择文本文件，或直接粘贴内容。",
      "book",
      () => knowledgeDialog($("knowledgeProject").value),
      "导入第一份资料",
    );
    return;
  }
  docs.forEach((d) => {
    const row = el("div", "document-row");
    row.append(icon("file"));
    const info = el("div", "document-info");
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
      await api(`/documents/${d.id}/archive`, {});
      await refresh();
      renderKnowledge();
      toast("资料已移出检索索引，历史引用仍保留。");
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
  $("knowledgeDialog").showModal();
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
    $("documentDialog").showModal();
  } catch (e) {
    toast(e.message);
  }
}
// 提交词面查询并显示来源引用/得分；得分不是语义真实性或信息增益。
async function searchKnowledge() {
  try {
    const q = $("knowledgeSearch").value.trim();
    show("searchResults", !!q);
    if (!q) return;
    const pid = $("knowledgeProject").value;
    const data = await api(
      `/search?q=${encodeURIComponent(q)}&project_id=${encodeURIComponent(pid)}`,
    );
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

// 展示服务端成熟度目录；planned 项保持规划状态，不造可执行按钮。
function renderArchitectureItems(parent, items) {
  parent.replaceChildren();
  (items || []).forEach((item) => {
    const maturity = item.maturity || item.state || "exists";
    const card = el("article", "platform-card " + maturity);
    const head = el("div", "platform-card-head");
    head.append(
      el("span", "platform-phase", item.kind || "component"),
      el("span", "platform-state " + maturity, maturity),
    );
    card.append(
      head,
      el("h2", "", item.label),
      el("p", "", item.responsibility),
    );
    if (item.depends_on?.length)
      card.append(el("small", "", "uses · " + item.depends_on.join(" / ")));
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
      "Architecture snapshot unavailable",
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
      el("small", "", cap.family + " · " + cap.risk),
    );
    row.append(left, el("span", "platform-state " + cap.state, cap.state));
    caps.append(row);
  });
  $("capabilityCount").textContent =
    (platform.executable_capabilities?.length || 0) + " executable";
}

// 按 hash 装配页面并推进 generation；异步响应只有仍匹配当前页面时才展示。
async function route() {
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
  state.id = id ? decodeURIComponent(id) : null;
  state.threadKey = "";
  state.session = null;
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
    sessions: "会话管理",
    projects: "项目",
    knowledge: "知识库",
    settings: "模型与设置",
  }[state.page];
  show("sessionMenu", false);
  renderSidebar();
  try {
    if (state.page === "chat") {
      if (state.id) await openSession(state.id, generation);
      else {
        fillProjects($("chatProject"), "独立对话", $("chatProject").value);
        renderChat(null);
      }
    } else if (state.page === "goals") await renderGoals();
    else if (state.page === "runtime") renderRuntime();
    else if (state.page === "sessions") await renderSessionPage();
    else if (state.page === "projects")
      id ? await renderProject(id) : renderProjects();
    else if (state.page === "knowledge") renderKnowledge();
    else {
      loadSettings();
      renderConnection();
    }
  } catch (e) {
    toast(e.message);
  }
}
// 周期读取当前会话与连接变化；读取不重新发出任务，失败不会清除持久恢复信息。
async function poll() {
  clearTimeout(state.poll);
  if (state.page === "chat" && state.id) {
    try {
      const id = state.id,
        generation = state.generation;
      await openSession(id, generation);
    } catch (e) {
      console.warn("conversation", e.message);
    }
  }
  if (state.page === "goals") {
    try {
      await renderGoals();
    } catch (e) {
      console.warn("goals", e.message);
    }
  }
  state.poll = setTimeout(
    poll,
    document.hidden
      ? 6000
      : state.session?.turns.at(-1)?.driver_active
        ? 1000
        : 3000,
  );
}

// 事件绑定只消费明确用户操作；业务身份、参数和状态仍经服务器校验。
$("newChat").onclick = () => newChat();
$("newSession").onclick = () => newChat();
$("composer").onsubmit = sendMessage;
$("quickGoal").onclick = () => {
  $("goalTitleInput").value = "";
  $("goalDescriptionInput").value = "";
  $("goalDialog").showModal();
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
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    sendMessage();
  }
};
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
    thinking: $("turnThinkingInput").value,
  });
  openControlDialog();
};
$("menuToggle").onclick = () => {
  $("sidebar").classList.add("open");
  show("sidebarShade", true);
};
$("sidebarShade").onclick = closeNavigation;
document.querySelectorAll("[data-suggestion]").forEach(
  (b) =>
    (b.onclick = () => {
      $("prompt").value = b.dataset.suggestion;
      $("prompt").focus();
    }),
);
document
  .querySelectorAll("[data-action]")
  .forEach((b) => (b.onclick = () => go(b.dataset.action)));
document
  .querySelectorAll("[data-close]")
  .forEach((b) => (b.onclick = () => $(b.dataset.close).close()));
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
  if (e.key === "Enter") searchKnowledge();
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
  try {
    if (state.attached.length + $("chatFiles").files.length > 4)
      throw new Error("每条消息最多附加 4 份资料。");
    const docs = await importFiles(
      [...$("chatFiles").files],
      state.session?.project_id || $("chatProject").value,
    );
    state.attached.push(...docs);
    renderAttachments();
    await refresh();
    toast("资料已导入，将加入下一条消息的上下文。");
  } catch (e) {
    toast(e.message);
  } finally {
    $("chatFiles").value = "";
  }
};
$("provider").onchange = () => {
  state.connection = null;
  renderChatGPTAuth();
  renderConnection();
};
$("chatgptLogin").onclick = beginChatGPTLogin;
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
$("checkConnection").onclick = () => checkConnection(false);
$("saveSettings").onclick = async () => {
  try {
    state.data.settings = await api("/settings", settingsPayload());
    $("settingsSaved").textContent = "已保存";
    renderConnection();
    toast("模型设置已保存。");
  } catch (e) {
    toast(e.message);
  }
};
window.addEventListener("hashchange", route);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeNavigation();
});
(async () => {
  try {
    await refresh();
    loadSettings();
    await refreshChatGPTAuth();
    fillGoals($("chatGoal"), "");
    await route();
    await checkConnection(true);
    poll();
  } catch (e) {
    toast("工作区未连接：" + e.message);
  }
})();
