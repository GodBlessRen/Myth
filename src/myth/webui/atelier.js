/* 工作台微交互：面板大小、阅读密度与可访问的状态入口仅属于本地视图。
 * 不读取凭据、不写 Run；运行标签只能显示现有观测节点已投影的文字。
 */
(() => {
  "use strict";
  const byId = id => document.getElementById(id);
  const desktop = window.matchMedia("(min-width: 1121px)");
  const root = document.documentElement;
  const safeRead = (key, fallback) => { try { return localStorage.getItem("myth-atelier-" + key) ?? fallback; } catch (_) { return fallback; } };
  const safeWrite = (key, value) => { try { localStorage.setItem("myth-atelier-" + key, String(value)); } catch (_) { /* 无存储时仅影响当前会话布局 */ } };
  const density = byId("densityToggle");
  const indicator = byId("runIndicator");

  function setDensity(compact) {
    root.dataset.density = compact ? "compact" : "comfortable";
    density.setAttribute("aria-pressed", String(compact));
    density.title = compact ? "切换舒适阅读密度" : "切换紧凑阅读密度";
    density.setAttribute("aria-label", density.title);
    safeWrite("density", compact ? "compact" : "comfortable");
  }
  density.addEventListener("click", () => setDensity(root.dataset.density !== "compact"));
  setDensity(safeRead("density", "comfortable") === "compact");

  // 可见指示灯仅镜像已有状态文本/类；不把心跳映射成持久进度。
  const pulse = byId("inspectorPulse");
  const label = byId("inspectorState");
  function syncIndicator() {
    const text = label.textContent?.trim() || "空闲";
    const state = ["running", "success", "danger", "unknown"].find(name => pulse.classList.contains(name)) || "idle";
    if (indicator.dataset.state !== state || indicator.dataset.label !== text) {
      indicator.dataset.state = state;
      indicator.dataset.label = text;
      indicator.querySelector(".run-indicator-label").textContent = text;
      indicator.title = "查看运行观测：" + text;
    }
  }
  indicator.addEventListener("click", () => {
    if (desktop.matches) {
      if (document.body.classList.contains("studio-focused")) byId("focusMode").click();
      if (document.body.classList.contains("inspector-collapsed")) byId("inspectorDock").click();
    } else byId("inspectorToggle").click();
    byId("lens-tab-overview")?.click();
  });
  const observer = new MutationObserver(syncIndicator);
  observer.observe(label, {childList: true, characterData: true, subtree: true});
  observer.observe(pulse, {attributes: true, attributeFilter: ["class"]});
  syncIndicator();

  // 拖拽时只更改 CSS 宽度变量；键盘方向键亦可精细调整。
  const limits = {sidebar: [210, 370], inspector: [285, 480]};
  const handles = [
    {node: byId("sidebarResize"), kind: "sidebar", property: "--myth-sidebar-width", fallback: 248},
    {node: byId("inspectorResize"), kind: "inspector", property: "--myth-inspector-width", fallback: 340},
  ];
  function applyWidth(item, width) {
    const [min, max] = limits[item.kind];
    const actual = Math.round(Math.max(min, Math.min(max, width)));
    root.style.setProperty(item.property, actual + "px");
    item.node.setAttribute("aria-valuenow", String(actual));
    item.node.setAttribute("aria-valuetext", actual + " 像素");
    safeWrite(item.kind + "-width", actual);
  }
  handles.forEach(item => {
    const stored = Number(safeRead(item.kind + "-width", item.fallback));
    applyWidth(item, Number.isFinite(stored) ? stored : item.fallback);
    item.node.addEventListener("keydown", event => {
      if (!desktop.matches || event.isComposing || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const [min, max] = limits[item.kind];
      const current = Number(item.node.getAttribute("aria-valuenow"));
      const delta = (event.shiftKey ? 24 : 8) * (event.key === "ArrowRight" ? 1 : -1) * (item.kind === "inspector" ? -1 : 1);
      applyWidth(item, event.key === "Home" ? min : event.key === "End" ? max : current + delta);
    });
    item.node.addEventListener("pointerdown", event => {
      if (!desktop.matches || event.button !== 0) return;
      if (document.body.classList.contains("studio-focused") ||
        document.body.classList.contains(item.kind === "sidebar" ? "sidebar-collapsed" : "inspector-collapsed")) return;
      event.preventDefault();
      const startX = event.clientX;
      const original = Number(item.node.getAttribute("aria-valuenow"));
      const sign = item.kind === "inspector" ? -1 : 1;
      const move = e => applyWidth(item, original + (e.clientX - startX) * sign);
      const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
        window.removeEventListener("pointercancel", stop);
        document.body.classList.remove("resizing-workspace");
      };
      document.body.classList.add("resizing-workspace");
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop, {once: true});
      window.addEventListener("pointercancel", stop, {once: true});
    });
  });
})();
