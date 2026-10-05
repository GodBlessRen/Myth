// 模型池设置只编辑公开配置；密钥单独提交凭据接口，执行与评分事实由后端返回。
const poolProviders = {ollama: "Ollama", openai: "OpenAI", chatgpt: "ChatGPT OAuth", deepseek: "DeepSeek", anthropic: "Claude API Key", claude_oauth: "Claude OAuth", kimi: "Kimi"};

// 使用 DOM/textContent 构建表单，模型名称和标签不会成为 HTML。
function poolField(parent, labelText, key, value, options = null, type = "text") {
  const wrapper = document.createElement("div");
  wrapper.className = "pool-field";
  const label = document.createElement("label");
  const input = document.createElement(options ? "select" : "input");
  input.dataset.poolField = key;
  input.id = `${parent.closest("[data-pool-id]")?.dataset.poolId || "pool-main"}-${key}`;
  label.htmlFor = input.id;
  label.textContent = labelText;
  if (options) Object.entries(options).forEach(([id, text]) => {
    const option = document.createElement("option");
    option.value = id; option.textContent = text; input.append(option);
  });
  else input.type = type;
  if (type === "number") {
    const limits = {max_steps: [1, 8, 1], max_output_tokens: [128, 32768, 1], num_ctx: [2048, 262144, 1], temperature: [0, 2, 0.1], "price-input": [0, 100000, "any"], "price-output": [0, 100000, "any"]};
    const [min, max, step] = limits[key] || [0, 100000, 1];
    input.min = String(min); input.max = String(max); input.step = String(step);
    input.required = !key.startsWith("price-");
  }
  input.value = value ?? "";
  wrapper.append(label, input); parent.append(wrapper);
  return input;
}

// 价格空白保持未知，不把未填写的金额转换成零。
function poolPriceFields(parent, rates) {
  const panel = document.createElement("section"); panel.className = "model-pricing";
  panel.rates = rates?.source ? rates : null;
  const heading = document.createElement("h4"); heading.textContent = "模型标价";
  const quote = document.createElement("p"); quote.className = "price-quote";
  const meta = document.createElement("p"); meta.className = "field-meta"; meta.setAttribute("role", "status");
  const refresh = document.createElement("button"); refresh.type = "button"; refresh.className = "text-button"; refresh.textContent = "更新价格";
  refresh.onclick = () => poolRefreshPrice(panel, true);
  const top = document.createElement("div"); top.className = "price-heading"; top.append(heading, refresh);
  panel.append(top, quote, meta); parent.append(panel);
  const manual = document.createElement("details"); manual.className = "pool-advanced price-override";
  const summary = document.createElement("summary"); summary.textContent = "自定义合同费率"; manual.append(summary); panel.append(manual);
  const label = document.createElement("label"); label.className = "pool-toggle";
  const toggle = document.createElement("input"); toggle.type = "checkbox"; toggle.dataset.priceOverride = "true";
  toggle.checked = !!rates && !rates.source;
  label.append(toggle, document.createTextNode("使用我的合同单价")); manual.append(label);
  const row = document.createElement("div"); row.className = "two-fields pool-pricing";
  manual.append(row);
  poolField(row, "输入单价 / 百万 Token", "price-input", rates?.source ? "" : rates?.input, null, "number");
  poolField(row, "输出单价 / 百万 Token", "price-output", rates?.source ? "" : rates?.output, null, "number");
  poolField(row, "计价币种", "price-currency", rates?.currency || "USD", {USD: "USD", CNY: "CNY"});
  const changed = () => {
    row.hidden = !toggle.checked;
    row.querySelectorAll("input, select").forEach(input => { input.disabled = !toggle.checked; if (input.type === "number") input.required = toggle.checked; });
    window.MythChoices?.sync();
  };
  toggle.onchange = changed; changed(); manual.open = toggle.checked;
  quote.textContent = "选择模型后自动查询";
}

// 所选模型变化使旧价格失效；只接受与当前提供方/精确 ID 相符的异步结果。
async function poolRefreshPrice(panel, force = false) {
  const child = panel.closest("[data-pool-id]");
  const provider = child ? poolValue(child, "provider") : document.getElementById("provider").value;
  const model = child ? poolValue(child, "model").trim() : document.getElementById("model").value.trim();
  const signature = JSON.stringify([provider, model]);
  if (!force && panel.signature === signature) return;
  panel.signature = signature; panel.rates = null;
  const generation = panel.generation = (panel.generation || 0) + 1;
  const quote = panel.querySelector(".price-quote"), meta = panel.querySelector(".field-meta");
  const button = panel.querySelector(".price-heading button");
  quote.textContent = model ? "正在查询标价…" : "选择模型后自动查询"; meta.replaceChildren();
  if (!model) return;
  button.disabled = true;
  try {
    const info = await api("/model-info", {provider, model, force});
    if (!panel.isConnected || panel.generation !== generation) return;
    panel.rates = info.pricing;
    const messages = {unknown: "目录尚未收录此模型的价格", unavailable: "目录暂时无法连接，费用保持未知", unpublished: "模型价格尚未公布", subscription: "订阅渠道 · 不按 API 标价估算", oauth_channel: "OAuth 用户渠道 · 费用保持供应商原生语义", local_or_hosted: "本地或自托管服务 · 不自动假定免费"};
    quote.textContent = info.pricing ? `输入 $${info.pricing.input} · 输出 $${info.pricing.output} / 百万 Token` : messages[info.status] || "价格保持未知";
    if (info.checked_at) {
      const source = document.createElement("a"); source.href = "https://models.dev/"; source.target = "_blank"; source.rel = "noopener noreferrer"; source.textContent = "models.dev";
      meta.append(source, document.createTextNode(` · ${info.stale ? "缓存已过期 · " : "查询于 "}${new Date(info.checked_at).toLocaleString("zh-CN")}`));
    }
    if (info.official_url) {
      const official = document.createElement("a"); official.href = info.official_url; official.target = "_blank"; official.rel = "noopener noreferrer"; official.textContent = "提供方价格说明";
      meta.append(document.createTextNode(meta.childNodes.length ? " · " : ""), official);
    }
    const tokens = child?.querySelector('[data-pool-field="max_output_tokens"]') || document.getElementById("maxTokens");
    if (info.max_output_tokens) tokens.dataset.catalogMax = String(info.max_output_tokens);
    else delete tokens.dataset.catalogMax;
    if (child) poolChildLimits(child); else renderAdaptiveModelSettings();
  } catch {
    if (panel.isConnected && panel.generation === generation) quote.textContent = "查询失败 · 可稍后更新，费用保持未知";
  } finally { if (panel.generation === generation) button.disabled = false; }
}

// 一轮加载或输入只查询发生变化的模型，轮询不会覆盖自定义费率与生成参数。
function poolRefreshPrices() {
  document.querySelectorAll(".model-pricing").forEach(panel => poolRefreshPrice(panel));
}

// 子模型独立边界与原生能力；未检查时只允许默认推理，不提供自由文本入口。
function poolChildLimits(root, details = root.connectionDetails) {
  if (details) root.connectionDetails = details;
  const provider = poolValue(root, "provider"), model = poolValue(root, "model").trim();
  const profile = root.connectionDetails?.model_capabilities?.[model];
  const tokens = root.querySelector('[data-pool-field="max_output_tokens"]');
  tokens.max = String(Math.min(32768, profile?.max_output_tokens || Number(tokens.dataset.catalogMax) || 32768));
  const temp = root.querySelector('[data-pool-field="temperature"]');
  temp.max = ["anthropic", "claude_oauth"].includes(provider) ? "1" : "2";
  temp.disabled = provider === "chatgpt" || provider === "openai" && (!profile || !!profile.reasoning) || ["anthropic", "claude_oauth"].includes(provider) && profile?.temperature?.supported !== true;
  if (temp.disabled) temp.value = "0";
  temp.closest(".pool-field").querySelector("small").textContent = temp.disabled ? "当前适配器使用模型默认采样。" : `0–${temp.max} · 越低越稳定，越高越多样。`;
  const select = root.querySelector('[data-pool-field="thinking"]');
  const current = root.pendingThinking ?? (select.value === "__on__" ? true : select.value === "__off__" ? false : select.value === "default" ? null : select.value);
  const meta = select.closest(".pool-field").querySelector("small");
  if (!profile?.reasoning) {
    select.replaceChildren(new Option("默认 · 由模型决定", "default")); select.disabled = true;
    if (root.pendingThinking != null) {
      const raw = root.pendingThinking === true ? "__on__" : root.pendingThinking === false ? "__off__" : String(root.pendingThinking);
      select.append(new Option(`${String(root.pendingThinking)} · 已保存`, raw)); select.value = raw;
    }
    meta.textContent = "检查连接后显示该模型支持的推理选项；强度越高通常越耗时。";
  } else {
    select.disabled = false; fillReasoningSelect(select, profile, current, meta);
    delete root.pendingThinking;
  }
  window.MythChoices?.sync();
}

// 读取指定区域的公开字段；认证输入不属于配置字段集合。
function poolValue(root, key) { return root.querySelector(`[data-pool-field="${key}"]`)?.value ?? ""; }

// 两个单价都未填则不估价；单边缺失交给后端明确拒绝。
function poolReadPrice(root) {
  const panel = root.querySelector(".model-pricing");
  if (!panel?.querySelector("[data-price-override]")?.checked) return panel?.rates || null;
  const input = poolValue(root, "price-input"), output = poolValue(root, "price-output");
  if (!input && !output) return null;
  return {currency: poolValue(root, "price-currency"), input: input === "" ? null : Number(input), output: output === "" ? null : Number(output)};
}

// 从单个槽位收集冻结配置；不携带任何 API Key。
function poolReadChild(root) {
  const thinking = poolValue(root, "thinking");
  return {id: root.dataset.poolId, label: poolValue(root, "label"), provider: poolValue(root, "provider"),
    model: poolValue(root, "model").trim(), enabled: poolValue(root, "enabled") === "true", tier: Number(poolValue(root, "tier")),
    task_types: Array.from(root.querySelectorAll("[data-task-type]:checked")).map(x => x.value),
    max_steps: Number(poolValue(root, "max_steps")), max_output_tokens: Number(poolValue(root, "max_output_tokens")), num_ctx: Number(poolValue(root, "num_ctx")),
    ollama_url: poolValue(root, "ollama_url"), temperature: Number(poolValue(root, "temperature")),
    thinking: root.pendingThinking ?? (thinking === "__on__" ? true : thinking === "__off__" ? false : thinking === "default" ? null : thinking || null), pricing: poolReadPrice(root)};
}

// 新增或恢复一个有稳定 ID 的子模型；最多三个槽位，提供方之间共用该提供方的安全凭据。
function poolAddChild(profile = {}) {
  const list = document.getElementById("poolChildren");
  if (!list || list.children.length >= 3) return;
  const root = document.createElement("fieldset"); root.className = "pool-child";
  root.dataset.poolId = profile.id || "child-" + crypto.randomUUID().slice(0, 8);
  root.pendingThinking = profile.thinking ?? null;
  root.setAttribute("aria-label", "子模型配置");
  list.append(root);
  const basic = document.createElement("div"); basic.className = "two-fields"; root.append(basic);
  poolField(basic, "状态", "enabled", String(profile.enabled ?? true), {true: "启用", false: "停用"});
  const provider = poolField(basic, "提供方", "provider", profile.provider || document.getElementById("provider")?.value || "ollama", poolProviders);
  const model = poolField(basic, "模型名称", "model", profile.model || "");
  const catalog = document.createElement("datalist"); catalog.id = root.dataset.poolId + "-models"; model.setAttribute("list", catalog.id); root.append(catalog);
  poolField(basic, "初始能力", "tier", profile.tier || 1, {1: "基础", 2: "较强", 3: "很强"});
  const actions = document.createElement("div"); actions.className = "button-row"; root.append(actions);
  const check = document.createElement("button"); check.type = "button"; check.className = "secondary"; check.textContent = "检查连接"; actions.append(check);
  const remove = document.createElement("button"); remove.type = "button"; remove.className = "text-button"; remove.textContent = "移除"; actions.append(remove);
  const status = document.createElement("p"); status.className = "field-meta"; status.setAttribute("role", "status"); root.append(status);
  const advanced = document.createElement("details"); advanced.className = "pool-advanced";
  const summary = document.createElement("summary"); summary.textContent = "更多设置"; advanced.append(summary); root.append(advanced);
  const options = document.createElement("div"); options.className = "two-fields"; advanced.append(options);
  poolField(options, "备注名称（可选）", "label", profile.label || "");
  poolField(options, "子任务步骤上限", "max_steps", profile.max_steps ?? 4, null, "number");
  const tasks = document.createElement("fieldset"); tasks.className = "pool-task-types";
  const tasksLegend = document.createElement("legend"); tasksLegend.textContent = "适用任务（不选则适用全部）"; tasks.append(tasksLegend); advanced.append(tasks);
  Object.entries({general:"通用", extract:"信息提取", summarize:"摘要", code:"编程", reason:"推理", review:"复核"}).forEach(([value, text]) => {
    const label = document.createElement("label"); label.className = "pool-toggle";
    const box = document.createElement("input"); box.type = "checkbox"; box.value = value; box.dataset.taskType = value; box.checked = (profile.task_types || []).includes(value);
    label.append(box, document.createTextNode(text)); tasks.append(label);
  });
  poolField(options, "输出 Token 上限", "max_output_tokens", profile.max_output_tokens ?? 2048, null, "number");
  const contextWindow = poolField(options, "上下文窗口 / Token", "num_ctx", profile.num_ctx ?? 8192, null, "number");
  const serverAddress = poolField(options, "服务地址", "ollama_url", profile.ollama_url || "http://127.0.0.1:11434");
  const thinking = poolField(options, "推理强度 · Thinking", "thinking", "default", {default: "默认 · 由模型决定"});
  const reasoningMeta = document.createElement("small"); thinking.parentElement.append(reasoningMeta);
  const temp = poolField(options, "采样温度", "temperature", profile.temperature ?? 0, null, "number");
  const temperatureMeta = document.createElement("small"); temp.parentElement.append(temperatureMeta);
  poolPriceFields(root, profile.pricing);
  const auth = document.createElement("details"); auth.className = "pool-advanced"; root.append(auth);
  const authSummary = document.createElement("summary"); authSummary.textContent = "连接此提供方的 API Key"; auth.append(authSummary);
  const keyLabel = document.createElement("label"); keyLabel.textContent = "API Key";
  const key = document.createElement("input"); key.type = "password"; key.autocomplete = "off";
  key.id = root.dataset.poolId + "-credential"; keyLabel.htmlFor = key.id; auth.append(keyLabel, key);
  const connect = document.createElement("button"); connect.type = "button"; connect.className = "secondary"; connect.textContent = "验证并保存凭据"; auth.append(connect);
  // 配置变更使旧检查失效；异步响应只能更新发起时对应的槽位。
  // num_ctx/本地地址是 Ollama 的可调参数；远端模型使用能力报告，不显示无效配置。
  const changed = () => {
    key.value = ""; status.textContent = ""; auth.hidden = ["ollama", "chatgpt", "claude_oauth"].includes(provider.value);
    contextWindow.closest(".pool-field").hidden = provider.value !== "ollama";
    serverAddress.closest(".pool-field").hidden = provider.value !== "ollama";
    delete root.connectionDetails; delete root.querySelector('[data-pool-field="max_output_tokens"]').dataset.catalogMax;
    poolChildLimits(root); poolRefreshPrices();
  };
  provider.addEventListener("change", () => { delete root.pendingThinking; changed(); }); changed();
  model.addEventListener("input", () => { delete root.pendingThinking; poolChildLimits(root); clearTimeout(root.priceTimer); root.priceTimer = setTimeout(poolRefreshPrices, 350); });
  model.addEventListener("change", () => { delete root.pendingThinking; poolChildLimits(root); poolRefreshPrices(); });
  remove.onclick = () => { root.remove(); document.getElementById("poolAdd").disabled = false; };
  check.onclick = async () => {
    const config = poolReadChild(root), signature = JSON.stringify([config.provider, config.model, config.ollama_url]); check.disabled = true; status.textContent = "正在检查…";
    check.replaceChildren(taijiMark(true), document.createTextNode("检查中"));
    try {
      const result = await api("/connection", config);
      if (!root.isConnected || signature !== JSON.stringify([poolValue(root, "provider"), poolValue(root, "model").trim(), poolValue(root, "ollama_url")])) return;
      status.textContent = result.ready ? "连接正常 · 生成能力需以任务结果确认" : "连接失败，请检查地址或凭据";
      catalog.replaceChildren();
      (result.details?.models || []).forEach(name => { const option = document.createElement("option"); option.value = name; catalog.append(option); });
      poolChildLimits(root, result.details);
    } catch (error) { if (root.isConnected) status.textContent = error.message; }
    finally { check.disabled = false; check.textContent = "检查连接"; }
  };
  connect.onclick = async () => {
    const selected = provider.value; connect.disabled = true;
    connect.replaceChildren(taijiMark(true), document.createTextNode("验证中"));
    try { await providerAuthApi("/connect", {provider: selected, api_key: key.value}); if (root.isConnected && provider.value === selected) status.textContent = "凭据已验证并保存，同提供方的槽位共用此连接"; }
    catch (error) { if (root.isConnected) status.textContent = error.message; }
    finally { key.value = ""; connect.disabled = false; connect.textContent = "验证并保存凭据"; }
  };
  document.getElementById("poolAdd").disabled = list.children.length >= 3;
  window.MythChoices?.sync();
}

// 只在明确加载设置时重建表单，轮询不会覆盖用户尚未保存的输入。
function loadModelPool(pool = {}) {
  const list = document.getElementById("poolChildren"); if (!list) return;
  list.replaceChildren();
  document.getElementById("poolEnabled").checked = pool.enabled ?? true;
  document.getElementById("poolAdaptive").checked = pool.adaptive ?? true;
  const price = document.getElementById("poolMainPricing"); price.replaceChildren(); poolPriceFields(price, pool.main_pricing);
  document.getElementById("poolAdd").disabled = false;
  (pool.children || []).forEach(poolAddChild);
  document.getElementById("poolAdd").onclick = () => poolAddChild();
}

// 收集当前表单，后端再次验证上限/价格/配置，不接受前端自行授予能力。
function modelPoolPayload() {
  const list = document.getElementById("poolChildren");
  if (!list) return {children: []};
  return {enabled: document.getElementById("poolEnabled").checked, adaptive: document.getElementById("poolAdaptive").checked,
    main_pricing: poolReadPrice(document.getElementById("poolMainPricing")), children: Array.from(list.children).map(poolReadChild)};
}
