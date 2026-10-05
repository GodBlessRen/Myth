// 模型池设置只编辑公开配置；密钥单独提交凭据接口，执行与评分事实由后端返回。
const poolProviders = {ollama: "Ollama", openai: "OpenAI", chatgpt: "ChatGPT OAuth", deepseek: "DeepSeek", anthropic: "Claude", kimi: "Kimi"};

// 使用 DOM/textContent 构建表单，模型名称和标签不会成为 HTML。
function poolField(parent, labelText, key, value, options = null, type = "text") {
  const wrapper = document.createElement("div");
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
  if (type === "number") { input.min = "0"; input.step = "any"; }
  input.value = value ?? "";
  wrapper.append(label, input); parent.append(wrapper);
  return input;
}

// 价格空白保持未知，不把未填写的金额转换成零。
function poolPriceFields(parent, rates) {
  const row = document.createElement("div"); row.className = "two-fields pool-pricing";
  parent.append(row);
  poolField(row, "输入单价 / 百万 Token", "price-input", rates?.input, null, "number");
  poolField(row, "输出单价 / 百万 Token", "price-output", rates?.output, null, "number");
  poolField(row, "计价币种", "price-currency", rates?.currency || "USD", {USD: "USD", CNY: "CNY"});
}

// 读取指定区域的公开字段；认证输入不属于配置字段集合。
function poolValue(root, key) { return root.querySelector(`[data-pool-field="${key}"]`)?.value ?? ""; }

// 两个单价都未填则不估价；单边缺失交给后端明确拒绝。
function poolReadPrice(root) {
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
    thinking: thinking === "true" ? true : thinking === "false" ? false : thinking || null, pricing: poolReadPrice(root)};
}

// 新增或恢复一个有稳定 ID 的子模型；最多三个槽位，提供方之间共用该提供方的安全凭据。
function poolAddChild(profile = {}) {
  const list = document.getElementById("poolChildren");
  if (!list || list.children.length >= 3) return;
  const root = document.createElement("fieldset"); root.className = "pool-child";
  root.dataset.poolId = profile.id || "child-" + crypto.randomUUID().slice(0, 8);
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
  poolField(options, "Thinking（默认留空）", "thinking", profile.thinking == null ? "" : String(profile.thinking));
  poolField(options, "采样温度", "temperature", profile.temperature ?? 0, null, "number");
  poolPriceFields(advanced, profile.pricing);
  const auth = document.createElement("details"); auth.className = "pool-advanced"; root.append(auth);
  const authSummary = document.createElement("summary"); authSummary.textContent = "连接此提供方的 API Key"; auth.append(authSummary);
  const keyLabel = document.createElement("label"); keyLabel.textContent = "API Key";
  const key = document.createElement("input"); key.type = "password"; key.autocomplete = "off";
  key.id = root.dataset.poolId + "-credential"; keyLabel.htmlFor = key.id; auth.append(keyLabel, key);
  const connect = document.createElement("button"); connect.type = "button"; connect.className = "secondary"; connect.textContent = "验证并保存凭据"; auth.append(connect);
  // 配置变更使旧检查失效；异步响应只能更新发起时对应的槽位。
  // num_ctx/本地地址是 Ollama 的可调参数；远端模型使用能力报告，不显示无效配置。
  const changed = () => {
    key.value = ""; status.textContent = ""; auth.hidden = ["ollama", "chatgpt"].includes(provider.value);
    contextWindow.parentElement.hidden = provider.value !== "ollama";
    serverAddress.parentElement.hidden = provider.value !== "ollama";
  };
  provider.addEventListener("change", changed); changed();
  remove.onclick = () => { root.remove(); document.getElementById("poolAdd").disabled = false; };
  check.onclick = async () => {
    const config = poolReadChild(root), signature = JSON.stringify(config); check.disabled = true; status.textContent = "正在检查…";
    check.replaceChildren(taijiMark(true), document.createTextNode("检查中"));
    try {
      const result = await api("/connection", config);
      if (!root.isConnected || signature !== JSON.stringify(poolReadChild(root))) return;
      status.textContent = result.ready ? "连接正常 · 生成能力需以任务结果确认" : "连接失败，请检查地址或凭据";
      catalog.replaceChildren();
      (result.details?.models || []).forEach(name => { const option = document.createElement("option"); option.value = name; catalog.append(option); });
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
