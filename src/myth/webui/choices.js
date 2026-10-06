// 统一选择器与模型建议菜单；保留原字段作为公开值来源，不创建第二份业务配置。
(() => {
  const controls = new Map();
  let opened = null;
  let serial = 0;

  // 标签来自现有表单；不把目录中的文本解释为 HTML。
  function labelFor(source) {
    return Array.from(source.labels || []).map(label => label.textContent.trim()).join(" ") || source.getAttribute("aria-label") || "选择";
  }

  class Choice {
    // 包装现有字段并建立ARIA关联；原字段保持唯一值来源，弹层不保存另一份业务配置。
    constructor(source) {
      this.source = source;
      this.editable = source.tagName === "INPUT";
      this.listId = this.editable ? source.getAttribute("list") : null;
      this.active = -1;
      this.rows = [];
      this.query = "";
      this.wrapper = document.createElement("span");
      this.wrapper.className = "choice-control";
      source.before(this.wrapper);
      this.wrapper.append(source);
      if (this.editable) {
        source.removeAttribute("list");
        source.autocomplete = "off";
        this.trigger = source;
      } else {
        source.classList.add("choice-source");
        source.tabIndex = -1;
        source.setAttribute("aria-hidden", "true");
        this.trigger = document.createElement("button");
        this.trigger.type = "button";
        this.trigger.className = "choice-trigger";
        this.text = document.createElement("span");
        this.trigger.append(this.text);
        this.wrapper.append(this.trigger);
        source.labels?.forEach(label => label.addEventListener("click", event => {
          event.preventDefault(); this.trigger.focus();
        }));
      }
      const chevron = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      chevron.setAttribute("viewBox", "0 0 16 16"); chevron.setAttribute("aria-hidden", "true");
      chevron.classList.add("choice-chevron");
      const path = document.createElementNS(chevron.namespaceURI, "path");
      path.setAttribute("d", "m4 6 4 4 4-4"); chevron.append(path); this.wrapper.append(chevron);
      this.popup = document.createElement("div");
      this.popup.className = "choice-menu"; this.popup.id = `myth-choices-${++serial}`;
      this.popup.setAttribute("popover", "manual"); this.popup.setAttribute("role", "listbox");
      (source.closest("dialog") || document.body).append(this.popup);
      this.trigger.setAttribute("role", "combobox");
      this.trigger.setAttribute("aria-autocomplete", this.editable ? "list" : "none");
      this.trigger.setAttribute("aria-haspopup", "listbox");
      this.trigger.setAttribute("aria-controls", this.popup.id);
      this.trigger.setAttribute("aria-expanded", "false");
      this.trigger.addEventListener("keydown", event => this.key(event));
      this.trigger.addEventListener("click", () => this.isOpen ? this.close() : this.open());
      if (this.editable) {
        this.trigger.addEventListener("input", () => this.open());
        this.trigger.addEventListener("focus", () => this.open());
      }
      this.trigger.addEventListener("blur", () => this.close());
      this.sync();
    }

    // 以浏览器原生Popover状态为准，避免内部布尔值与顶层弹层失配。
    get isOpen() { return this.popup.matches(":popover-open"); }

    // 从当前目录读取可见项；仅筛选显示，不修改提供方允许的值或禁用状态。
    options() {
      const list = this.editable ? document.getElementById(this.listId) : this.source;
      const query = this.editable ? this.source.value.trim().toLowerCase() : "";
      return Array.from(list?.querySelectorAll("option") || [])
        .filter(option => !option.hidden && (!query || option.value.toLowerCase().includes(query) || option.textContent.toLowerCase().includes(query)))
        .map(option => ({value: option.value, label: option.label || option.textContent || option.value, disabled: option.disabled}));
    }

    // 轮询更新标签或可用性，保留源字段；字段离开DOM时同时清理弹层与映射。
    sync() {
      if (!this.source.isConnected) { this.close(); this.popup.remove(); controls.delete(this.source); return; }
      if (!this.editable) {
        this.text.textContent = this.source.selectedOptions[0]?.textContent || "请选择";
        this.trigger.disabled = this.source.disabled;
        this.trigger.setAttribute("aria-label", `${labelFor(this.source)}：${this.text.textContent}`);
        this.wrapper.title = this.text.textContent;
      } else {
        this.trigger.setAttribute("aria-label", labelFor(this.source));
      }
      this.popup.setAttribute("aria-label", labelFor(this.source));
      if (this.isOpen) this.render();
    }

    // 每项只写textContent；当前选择和键盘活动项分开，导航本身不提交配置。
    render() {
      this.rows = this.options();
      this.popup.replaceChildren();
      this.rows.forEach((row, index) => {
        const item = document.createElement("div");
        item.className = "choice-option"; item.id = `${this.popup.id}-${index}`;
        item.setAttribute("role", "option"); item.setAttribute("aria-disabled", String(row.disabled));
        item.setAttribute("aria-selected", String(row.value === this.source.value));
        item.textContent = row.label;
        item.addEventListener("pointerdown", event => event.preventDefault());
        item.addEventListener("pointermove", () => { if (!row.disabled) this.activate(index); });
        item.addEventListener("click", () => this.choose(index));
        this.popup.append(item);
      });
      const selected = this.rows.findIndex(row => row.value === this.source.value && !row.disabled);
      this.activate(selected >= 0 ? selected : this.rows.findIndex(row => !row.disabled));
      if (!this.rows.length) this.close();
    }

    // 全页最多一个选择菜单；打开只投影选项，不触发HTTP命令。
    open() {
      if (this.trigger.disabled) return;
      if (opened && opened !== this) opened.close();
      if (!this.options().length) return;
      if (!this.isOpen) this.popup.showPopover();
      opened = this;
      this.trigger.setAttribute("aria-expanded", "true");
      this.render(); this.position();
    }

    // 弹层进入原生顶层后按当前视口定位，空间不足向上展开；不挤压工作台布局。
    position() {
      if (!this.isOpen) return;
      const bounds = this.trigger.getBoundingClientRect();
      const width = Math.min(Math.max(bounds.width, 180), window.innerWidth - 24);
      const below = window.innerHeight - bounds.bottom - 16;
      const above = bounds.top - 16;
      const up = below < 200 && above > below;
      this.popup.style.width = `${width}px`;
      this.popup.style.maxHeight = `${Math.max(80, Math.min(320, up ? above : below))}px`;
      this.popup.style.left = `${Math.max(12, Math.min(bounds.left, window.innerWidth - width - 12))}px`;
      this.popup.style.top = `${up ? Math.max(12, bounds.top - this.popup.offsetHeight - 6) : bounds.bottom + 6}px`;
    }

    // 关闭同步清理ARIA活动项，焦点仍由触发字段所有。
    close() {
      if (this.isOpen) this.popup.hidePopover();
      this.trigger.setAttribute("aria-expanded", "false");
      this.trigger.removeAttribute("aria-activedescendant");
      if (opened === this) opened = null;
    }

    // 键盘导航只改变活动项；aria-activedescendant让读屏器跟随而不移动DOM焦点。
    activate(index) {
      this.active = index;
      Array.from(this.popup.children).forEach((item, i) => item.classList.toggle("is-active", i === index));
      const item = this.popup.children[index];
      if (item) { this.trigger.setAttribute("aria-activedescendant", item.id); item.scrollIntoView({block: "nearest"}); }
    }

    // 用户确认才写源字段并派发原有input/change事件；禁用项始终不能提交。
    choose(index) {
      const row = this.rows[index];
      if (!row || row.disabled) return;
      this.source.value = row.value;
      this.close(); this.sync();
      this.source.dispatchEvent(new Event("input", {bubbles: true}));
      this.source.dispatchEvent(new Event("change", {bubbles: true}));
      this.close(); this.trigger.focus({preventScroll: true});
    }

    // Arrow/Home/End/字首定位与Enter确认遵循列表框合同；Escape只收起菜单，Tab继续原焦点顺序。
    key(event) {
      // 中文候选确认属于输入法；菜单不能抢走 composition 的 Enter、方向键或 Escape。
      if (event.isComposing || event.keyCode === 229) return;
      if (event.key === "Escape" && this.isOpen) {
        event.preventDefault(); event.stopPropagation(); this.close(); return;
      }
      if (event.key === "Tab") { this.close(); return; }
      if (event.key === "Enter" && this.isOpen) {
        event.preventDefault(); event.stopPropagation(); this.choose(this.active); return;
      }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key) && (!this.editable || this.isOpen || event.key.startsWith("Arrow"))) {
        event.preventDefault(); event.stopPropagation();
        if (!this.isOpen) { this.open(); return; }
        const enabled = this.rows.map((row, i) => row.disabled ? -1 : i).filter(i => i >= 0);
        const current = enabled.indexOf(this.active);
        const next = event.key === "Home" ? 0 : event.key === "End" ? enabled.length - 1 : (current + (event.key === "ArrowDown" ? 1 : -1) + enabled.length) % enabled.length;
        this.activate(enabled[next]); return;
      }
      if (!this.editable && event.key.length === 1 && !event.ctrlKey && !event.metaKey && event.key !== " ") {
        event.preventDefault();
        this.query = Date.now() - (this.typedAt || 0) < 700 ? this.query + event.key.toLowerCase() : event.key.toLowerCase();
        this.typedAt = Date.now(); this.open();
        const index = this.rows.findIndex(row => !row.disabled && row.label.toLowerCase().startsWith(this.query));
        if (index >= 0) this.activate(index);
      }
    }
  }

  // 动态 Goal、项目、模型目录和子槽位沿用原 DOM；每次渲染后只同步可见选择器。
  function sync() {
    document.querySelectorAll("select, input[list]").forEach(source => {
      if (!controls.has(source)) controls.set(source, new Choice(source));
    });
    controls.forEach(control => control.sync());
  }
  window.MythChoices = {sync};
  document.addEventListener("change", sync);
  document.addEventListener("pointerdown", event => {
    if (opened && !opened.wrapper.contains(event.target) && !opened.popup.contains(event.target)) opened.close();
  });
  window.addEventListener("resize", () => opened?.position());
  document.addEventListener("scroll", event => {
    if (opened && !opened.popup.contains(event.target)) opened.close();
  }, true);
  let scheduled = false;
  const observer = new MutationObserver(records => {
    if (!records.some(record => !record.target.closest?.(".choice-menu, .choice-control") || record.target.tagName === "SELECT" || record.target.closest?.("select"))) return;
    if (!scheduled) { scheduled = true; queueMicrotask(() => { scheduled = false; sync(); }); }
  });
  observer.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "hidden", "label", "value"]});
  sync();
})();
