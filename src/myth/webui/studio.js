// 工作台视图控制：导航折叠、观测角度、会话定位与专注布局只拥有浏览器偏好。
// 不写 Runtime、创建 Run 或推断执行结果；事实容器仍由原投影脚本维护。
(() => {
  "use strict";
  const byId = id => document.getElementById(id);
  const desktop = window.matchMedia("(min-width: 1121px)");
  const rail = window.matchMedia("(min-width: 801px)");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const groups = [...document.querySelectorAll("[data-nav-group]")];
  const tabs = [...document.querySelectorAll("[data-inspector-lens]")];
  const panels = [...document.querySelectorAll("[data-lens-panel]")];
  let focused = false, previousLayout = null, directoryKey = "", routeKey = "";
  let lens = "overview";

  // 偏好不可用时使用可操作的默认布局；损坏值不得影响页面与业务投影。
  function read(key, fallback) {
    try { return localStorage.getItem("myth-studio-" + key) ?? fallback; }
    catch (_) { return fallback; }
  }
  function write(key, value) {
    try { localStorage.setItem("myth-studio-" + key, String(value)); }
    catch (_) { /* 私密浏览或存储满时，当前视图仍然生效。 */ }
  }

  // 只收起观测内容；展开按钮留在窄轨道上，焦点不会进入被隐藏的事实区。
  function dock(collapsed, persist = false) {
    document.body.classList.toggle("inspector-collapsed", collapsed);
    const button = byId("inspectorDock");
    button.setAttribute("aria-expanded", String(!collapsed));
    button.setAttribute("aria-label", collapsed ? "展开观测栏" : "收起观测栏");
    button.title = collapsed ? "展开观测栏" : "收起观测栏";
    if (persist) write("inspector-collapsed", collapsed);
  }

  // 窄轨道显示所有主入口；组偏好只用于展开侧栏，临时强制打开不回写偏好。
  function syncNavigation() {
    const collapsed = rail.matches && document.body.classList.contains("sidebar-collapsed");
    groups.filter(group => group.dataset.navGroup !== "recent").forEach(group => {
      group.open = collapsed || read("nav-" + group.dataset.navGroup, "true") !== "false";
    });
  }

  // 专注是一段可撤销的布局事务；退出时恢复进入前两栏状态，不污染用户偏好。
  function focus(enabled) {
    if (enabled === focused || (enabled && !desktop.matches)) return;
    if (enabled) {
      previousLayout = {
        left: document.body.classList.contains("sidebar-collapsed"),
        right: document.body.classList.contains("inspector-collapsed"),
      };
      setSidebarCollapsed(true);
      dock(true);
    } else if (previousLayout) {
      setSidebarCollapsed(previousLayout.left);
      dock(previousLayout.right);
      previousLayout = null;
    }
    focused = enabled;
    document.body.classList.toggle("studio-focused", enabled);
    const button = byId("focusMode");
    button.setAttribute("aria-pressed", String(enabled));
    button.querySelector("span").textContent = enabled ? "退出专注" : "专注";
    button.title = enabled ? "恢复三栏布局" : "展开专注工作区";
    syncNavigation();
  }

  // 切换同一事实集合的观察角度：ARIA 面板身份稳定，未选内容退出焦点顺序。
  function selectLens(key, animate = false) {
    if (!tabs.some(tab => tab.dataset.inspectorLens === key)) key = "overview";
    lens = key;
    tabs.forEach(tab => {
      const active = tab.dataset.inspectorLens === key;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    panels.forEach(panel => {
      const active = panel.dataset.lensPanel === key;
      panel.hidden = !active;
      panel.setAttribute("role", "tabpanel");
      panel.open = true;
      if (active && animate && !reduced.matches) {
        panel.getAnimations().forEach(animation => animation.cancel());
        panel.animate([{ opacity: .65, transform: "translateY(5px)" }, { opacity: 1, transform: "translateY(0)" }],
          { duration: 180, easing: "cubic-bezier(.16,1,.3,1)" });
      }
    });
    write("lens", key);
  }

  // 目录引用公开消息身份，标题按纯文本截取；定位不会改 URL 或提交新消息。
  function sync(session, page, id) {
    byId("recentCount").textContent = String(state.data?.sessions?.length || 0);
    const route = page + "/" + (id || "");
    if (route !== routeKey) {
      routeKey = route;
      const active = document.querySelector(".nav-group [data-page].active");
      if (active) active.closest(".nav-group").open = true;
    }
    const messages = page === "chat" ? (session?.messages || []).filter(message => message.role === "user") : [];
    const directory = byId("conversationIndex");
    directory.classList.toggle("hidden", messages.length < 2);
    const key = JSON.stringify(messages.map(message => [message.id, message.content]));
    if (key === directoryKey) return;
    directoryKey = key;
    byId("conversationCount").textContent = messages.length + " 个问题";
    const list = byId("conversationLinks");
    list.replaceChildren();
    messages.forEach((message, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = String(message.content).replace(/\s+/g, " ").slice(0, 80);
      button.title = "定位到问题 " + (index + 1);
      button.onclick = () => {
        const row = [...byId("thread").querySelectorAll("[data-message-id]")].find(node => node.dataset.messageId === message.id);
        if (!row) return;
        directory.open = false;
        row.scrollIntoView({ block: "start", behavior: reduced.matches ? "instant" : "smooth" });
        row.tabIndex = -1;
        row.focus({ preventScroll: true });
      };
      list.append(button);
    });
  }

  groups.forEach(group => {
    group.open = read("nav-" + group.dataset.navGroup, "true") !== "false";
    group.addEventListener("toggle", () => {
      if (rail.matches && document.body.classList.contains("sidebar-collapsed")) return;
      write("nav-" + group.dataset.navGroup, group.open);
    });
  });
  document.querySelectorAll("[data-evidence-section]").forEach(section => {
    const key = "evidence-" + section.dataset.evidenceSection;
    section.open = read(key, String(section.open)) !== "false";
    section.addEventListener("toggle", () => write(key, section.open));
  });
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectLens(tab.dataset.inspectorLens, true));
    tab.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 :
        (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      selectLens(tabs[next].dataset.inspectorLens, true);
      tabs[next].focus();
    });
  });
  byId("focusMode").addEventListener("click", () => focus(!focused));
  byId("inspectorDock").addEventListener("click", () => {
    if (focused) { focus(false); dock(false, true); }
    else dock(!document.body.classList.contains("inspector-collapsed"), true);
  });
  // 手动展开任一栏先退出专注，避免按钮状态与实际空间不一致。
  byId("sidebarCollapse").addEventListener("click", () => {
    if (focused) { focus(false); setSidebarCollapsed(false, true); }
    syncNavigation();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !event.defaultPrevented && focused && !document.querySelector("dialog[open]")) focus(false);
  });
  desktop.addEventListener("change", () => { if (!desktop.matches) focus(false); });
  rail.addEventListener("change", syncNavigation);
  dock(read("inspector-collapsed", "false") === "true");
  document.body.classList.add("studio-ready");
  selectLens(read("lens", "overview"));
  syncNavigation();
  window.MythStudio = Object.freeze({ sync });
  sync(state.session, state.page, state.id);
})();
