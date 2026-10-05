// 实际浏览器验收：真实 HTTP、SQLite 与 Runtime；Provider 目录和回答由专用服务固定。
// 本脚本通过可见操作创建唯一命名的资料，不写产品状态内部字段，不代表远端模型或 OAuth 联调。
// 运行：NODE_PATH 指向带 playwright 的 node_modules，再执行 node tests/check_workspace_browser.cjs。
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

// 每次运行拥有独立内容身份；截图文件代表最近一次运行，完整步骤和异常写入同目录 JSON。
const runId = new Date().toISOString().replace(/[:.]/g, "-") + "-" + Math.random().toString(16).slice(2, 8);
const baseURL = process.env.MYTH_UI_BASE_URL || "http://127.0.0.1:8770";
const outputDir = path.resolve(__dirname, "../output/playwright");
const report = { runId, baseURL, boundary: "真实 HTTP、持久 Runtime；固定 Provider 传输，不验证远端模型、OAuth 或模型质量", steps: [], screenshots: [], console: [], pageErrors: [], httpErrors: [], requestFailures: [], overflows: [] };
fs.mkdirSync(outputDir, { recursive: true });

// 断言只读取 DOM 或服务端公开投影；由轮询等待异步提交，避免把固定延时当完成证据。
async function visible(page, selector) {
  await page.locator(selector).waitFor({ state: "visible" });
}
async function value(page, selector, expected) {
  await page.waitForFunction(({ selector, expected }) => document.querySelector(selector)?.value === expected, { selector, expected });
}
async function textContains(page, selector, expected) {
  await page.waitForFunction(({ selector, expected }) => document.querySelector(selector)?.textContent.includes(expected), { selector, expected });
}
async function focusIs(page, selector) {
  try {
    await page.waitForFunction(selector => document.activeElement === document.querySelector(selector), selector);
  } catch (error) {
    const diagnostic = await page.evaluate(selector => {
      const node = document.querySelector(selector), panel = node?.closest("dialog, aside");
      return { activeTag: document.activeElement.tagName, activeId: document.activeElement.id,
        visibility: node && getComputedStyle(node).visibility, display: node && getComputedStyle(node).display,
        panelInert: panel?.inert, inertAncestor: node?.closest("[inert]")?.id,
        rectangle: node?.getBoundingClientRect().toJSON() };
    }, selector);
    throw new Error(`${selector} 焦点不匹配：${JSON.stringify(diagnostic)}`, { cause: error });
  }
}
async function dialogClosed(page, selector) {
  await page.waitForFunction(selector => !document.querySelector(selector)?.open, selector);
}

// 业务写入必须经过产品表单；响应提供持久对象身份，失败保留实际 HTTP 诊断。
async function submitAndRead(page, action, urlPath) {
  const responsePromise = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === urlPath);
  await action();
  const response = await responsePromise;
  const body = await response.json();
  assert.equal(response.ok(), true, `${response.status()} ${JSON.stringify(body)}`);
  return body;
}

// 导航等待当前页面可见；hash 页面是产品正常入口，不访问离线对比文件。
async function navigate(page, route) {
  await page.evaluate(route => { location.hash = route; }, route);
  const root = route.split("/")[0];
  const view = root === "projects" && route.includes("/") ? "project" : root;
  await visible(page, `#${view}Page`);
  if (view === "goals") await textContains(page, "#schedulerStatus", "定时唤醒");
}

// 截图在主题与布局过渡结束后保存；画面证据与行为步骤分别记录。
async function screenshot(page, name) {
  // 截图必须等待本机字体完成加载；系统回退字体不能作为本次视觉验收证据。
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(350);
  // 代表性画面等待短暂成功提示自然消失；失败截图保留提示便于定位。
  if (!name.startsWith("failure-")) await page.locator("#toast").waitFor({ state: "hidden", timeout: 6500 });
  const filename = `qa-${name}.png`;
  await page.screenshot({ path: path.join(outputDir, filename), fullPage: true });
  report.screenshots.push(filename);
}

// 检查 document 的实际横向宽度，并记录可见越界节点用于精确复现。
async function noOverflow(page, label) {
  const measurement = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    return {
      width, scrollWidth: document.documentElement.scrollWidth,
      // 手机短标签应完整单行呈现；document 不溢出仍可能把两字按钮压成纵向文字。
      modelShortLabel: (() => {
        const label = document.querySelector(".model-short-label");
        if (!label?.getClientRects().length) return null;
        const style = getComputedStyle(label);
        return { height: label.getBoundingClientRect().height,
          lineHeight: Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.6,
          text: label.textContent };
      })(),
      offenders: [...document.querySelectorAll("body *")].filter(node => {
        const rect = node.getBoundingClientRect();
        return rect.width && rect.height && (rect.right > width + 1 || rect.left < -1) &&
          getComputedStyle(node).visibility !== "hidden" &&
          !node.closest(".sidebar:not(.open), .inspector:not(.open)");
      }).slice(0, 12).map(node => ({ tag: node.tagName, id: node.id, class: node.className, right: node.getBoundingClientRect().right })),
    };
  });
  report.overflows.push({ label, ...measurement });
  assert.ok(measurement.scrollWidth <= measurement.width + 1, `${label}: ${JSON.stringify(measurement)}`);
  if (measurement.modelShortLabel)
    assert.ok(measurement.modelShortLabel.height <= measurement.modelShortLabel.lineHeight + 1,
      `${label}: 模型短标签被挤成多行 ${JSON.stringify(measurement.modelShortLabel)}`);
}

// 单个失败不会吞掉独立页面检查；每次失败保存当前画面和可阅读的异常，最终进程明确失败。
async function step(page, name, action) {
  const started = Date.now();
  try {
    await action();
    report.steps.push({ name, status: "PASS", durationMs: Date.now() - started });
    console.log(`PASS ${name}`);
    return true;
  } catch (error) {
    const entry = { name, status: "FAIL", durationMs: Date.now() - started, error: error.stack || String(error) };
    report.steps.push(entry);
    console.error(`FAIL ${name}\n${entry.error}`);
    await screenshot(page, `failure-${report.steps.length}`).catch(() => {});
    // 失败后使用真实关闭手势释放当前模态，避免遮罩让独立步骤产生连锁超时。
    for (let index = 0; index < 3; index++) await page.keyboard.press("Escape").catch(() => {});
    return false;
  }
}

// 原生对话框及抽屉必须圈定键盘焦点；直接读可见控件集合，不调用产品内部控制函数。
async function focusTrap(page, selector) {
  const last = page.locator(selector).locator("a[href], button, input, select, textarea, summary, [tabindex]").filter({ visible: true });
  const controls = await last.evaluateAll(nodes => nodes.filter(node => !node.disabled && node.tabIndex >= 0).map(node => node.id || null));
  assert.ok(controls.length > 0, `${selector} has focusable controls`);
  await page.locator(selector).evaluate(panel => {
    const nodes = [...panel.querySelectorAll("a[href], button, input, select, textarea, summary, [tabindex]")].filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
    nodes.at(-1).focus();
  });
  await page.keyboard.press("Tab");
  assert.equal(await page.locator(selector).evaluate(panel => panel.contains(document.activeElement)), true, `${selector} forward focus stays inside`);
  await page.locator(selector).evaluate(panel => {
    const nodes = [...panel.querySelectorAll("a[href], button, input, select, textarea, summary, [tabindex]")].filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
    nodes[0].focus();
  });
  await page.keyboard.press("Shift+Tab");
  assert.equal(await page.locator(selector).evaluate(panel => panel.contains(document.activeElement)), true, `${selector} reverse focus stays inside`);
}

// 窄屏导航与 Runtime 使用真实入口验证 inert、Escape、遮罩及断点释放，确保关闭后可继续操作。
async function drawers(page, viewport, sessionId) {
  await page.setViewportSize(viewport);
  const chatRoute = sessionId ? `chat/${sessionId}` : "chat";
  await navigate(page, chatRoute);
  if (viewport.width <= 800) {
    await page.locator("#menuToggle").click();
    await page.waitForFunction(() => document.querySelector("#sidebar").classList.contains("open"));
    assert.equal(await page.locator("#sidebar").getAttribute("aria-modal"), "true");
    assert.equal(await page.locator("#mainContent").evaluate(node => node.inert), true);
    await focusTrap(page, "#sidebar");
    await screenshot(page, `navigation-${viewport.width}`);
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.querySelector("#sidebar").classList.contains("open"));
    await focusIs(page, "#menuToggle");
    assert.equal(await page.locator("#mainContent").evaluate(node => node.inert), false);
    await page.locator("#menuToggle").click();
    await page.locator('#sidebar [data-page="knowledge"]').click();
    await visible(page, "#knowledgePage");
    assert.equal(await page.locator("#sidebar").evaluate(node => node.inert), true);
    await page.locator("#menuToggle").click();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.waitForFunction(() => !document.querySelector("#sidebar").classList.contains("open") && !document.querySelector("#mainContent").inert);
    assert.equal(await page.locator("#sidebar").evaluate(node => node.inert), false);
    await page.setViewportSize(viewport);
  }
  await navigate(page, chatRoute);
  if (sessionId) {
  await page.locator("#thread .assistant").first().waitFor({ state: "visible" });
    await textContains(page, "#inspectorState", "已完成");
    await textContains(page, "#inspectorDelivery", "已保存");
  }
  await page.locator("#inspectorToggle").click();
  await page.waitForFunction(() => document.querySelector("#runtimeInspector").classList.contains("open"));
  assert.equal(await page.locator("#runtimeInspector").getAttribute("aria-modal"), "true");
  assert.equal(await page.locator("#mainContent").evaluate(node => node.inert), true);
  await focusIs(page, "#inspectorClose");
  await focusTrap(page, "#runtimeInspector");
  await screenshot(page, `runtime-${viewport.width}`);
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.querySelector("#runtimeInspector").classList.contains("open"));
  await focusIs(page, "#inspectorToggle");
  assert.equal(await page.locator("#mainContent").evaluate(node => node.inert), false);
  assert.equal(await page.locator("#runtimeInspector").evaluate(node => node.inert), true);
  await page.locator("#inspectorToggle").click();
  await page.locator("#inspectorClose").click();
  await focusIs(page, "#inspectorToggle");
  await page.locator("#inspectorToggle").click();
  await page.locator(".inspector-shade").click({ position: { x: 2, y: 2 } });
  await focusIs(page, "#inspectorToggle");
  await page.locator("#inspectorToggle").click();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForFunction(() => !document.querySelector("#runtimeInspector").classList.contains("open") && !document.querySelector("#mainContent").inert);
  assert.equal(await page.locator("#runtimeInspector").evaluate(node => node.inert), false);
  await page.setViewportSize(viewport);
}

// 主流程只持有浏览器与公开对象身份；最后统一写证据，即使中途异常也保留错误和截图清单。
async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.MYTH_CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe" });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, timezoneId: "Asia/Shanghai", colorScheme: "light" });
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  let captureActive = true;
  page.on("console", message => report.console.push({ type: message.type(), text: message.text(), location: message.location() }));
  page.on("pageerror", error => { report.pageErrors.push(error.stack || String(error)); console.error("PAGEERROR", error.message); });
  page.on("response", response => {
    if (captureActive && response.status() >= 400) {
      const entry = { status: response.status(), method: response.request().method(), url: response.url() };
      report.httpErrors.push(entry); console.error("HTTPERROR", JSON.stringify(entry));
    }
  });
  page.on("requestfailed", request => {
    if (captureActive) {
      const entry = { method: request.method(), url: request.url(), error: request.failure()?.errorText };
      report.requestFailures.push(entry); console.error("REQUESTFAILED", JSON.stringify(entry));
    }
  });
  let projectId, documentId, sessionId, secondSessionId, goalId, scheduleId;
  const token = `QABROWSER${runId.replace(/[^a-zA-Z0-9]/g, "")}`;
  const projectName = `浏览器验收项目 ${runId}`;
  const editedProjectName = `纸面工作台项目 ${runId}`;
  const sessionTitle = `验收会话 ${runId}`;
  const documentTitle = `资料-${runId}.md`;
  const documentContent = `# 工作台验收资料\n\n唯一检索词：${token}\n\n这份长中文资料用于验证真实导入、索引、检索与预览。\n${"应当让用户读懂当前工作状态、证据与下一步。".repeat(25)}\n\n长标识符：${"verification_".repeat(25)}\n<script>window.untrustedDocumentExecuted=true</script>`;
  try {
    await step(page, "启动真实工作台", async () => {
      await page.goto(baseURL, { waitUntil: "networkidle" });
      await visible(page, "#chatPage");
      await page.waitForFunction(() => document.querySelector('#provider option[value="chatgpt"]') && document.querySelector("#modelLabel").textContent !== "连接 Ollama");
      await noOverflow(page, "desktop initial");
    });

    await step(page, "四种 Provider 与双模型自适应参数", async () => {
      await navigate(page, "settings");
      for (const provider of ["ollama", "openai", "deepseek", "chatgpt"]) {
        await page.locator("#provider").selectOption(provider);
        assert.equal(await page.locator("#ollamaEndpointField").isVisible(), provider === "ollama");
        assert.equal(await page.locator("#providerKeyPanel").isVisible(), ["openai", "deepseek"].includes(provider));
        assert.equal(await page.locator("#chatgptAuthPanel").isVisible(), provider === "chatgpt");
        await page.locator("#checkConnection").click();
        await textContains(page, "#connectionResult", "2 个可用模型");
        assert.deepEqual(await page.locator("#modelOptions option").evaluateAll(nodes => nodes.map(node => node.value)), ["review-model", "review-reasoning"]);
        await page.locator("#model").fill("review-model");
        assert.equal(await page.locator("#reasoningField").isVisible(), false);
        await page.locator("#model").fill("review-reasoning");
        await visible(page, "#reasoningField");
        const options = await page.locator("#reasoningSetting option").evaluateAll(nodes => nodes.map(node => node.textContent));
        for (const level of ["low", "medium", "high"]) assert.ok(options.some(text => text.includes(level)), `${provider} exposes ${level}`);
        // 与用户选择路径一致：先离开模型文本框完成 change，再选择 reasoning，避免工具直接改值跳过焦点事件。
        await page.locator("#reasoningSetting").focus();
        await page.locator("#reasoningSetting").selectOption("high");
        await submitAndRead(page, () => page.locator("#saveSettings").click(), "/api/workspace/settings");
        await textContains(page, "#settingsSaved", "已保存");
        const saved = (await (await context.request.get(`${baseURL}/api/workspace`)).json()).settings;
        assert.equal(saved.provider, provider);
        assert.equal(saved.model, "review-reasoning");
        assert.equal(saved.thinking, "high");
      }
      await page.locator("#provider").selectOption("ollama");
      await page.locator("#checkConnection").click();
      await textContains(page, "#connectionResult", "2 个可用模型");
      await page.locator("#model").fill("review-model");
      await submitAndRead(page, () => page.locator("#saveSettings").click(), "/api/workspace/settings");
      const plainSettings = (await (await context.request.get(`${baseURL}/api/workspace`)).json()).settings;
      assert.equal(plainSettings.thinking, null, "model without reasoning clears selected effort");
      await screenshot(page, "settings-light");
    });

    await step(page, "主题持久化与跟随系统", async () => {
      await page.locator('[data-theme-choice="dark"]').click();
      await page.waitForFunction(() => document.documentElement.dataset.theme === "dark");
      await screenshot(page, "settings-dark");
      await page.reload({ waitUntil: "networkidle" });
      await page.waitForFunction(() => document.documentElement.dataset.theme === "dark" && localStorage.getItem("myth-theme") === "dark");
      await navigate(page, "settings");
      await page.locator('[data-theme-choice="system"]').click();
      await page.emulateMedia({ colorScheme: "dark" });
      await page.waitForFunction(() => document.documentElement.dataset.theme === "dark" && localStorage.getItem("myth-theme") === null);
      await page.emulateMedia({ colorScheme: "light" });
      await page.waitForFunction(() => document.documentElement.dataset.theme === "light");
      await page.locator('[data-theme-choice="light"]').click();
    });

    await step(page, "原生弹窗键盘焦点边界", async () => {
      await navigate(page, "projects");
      await page.locator("#createProject").click();
      await focusIs(page, "#projectNameInput");
      await focusTrap(page, "#projectDialog");
      await page.keyboard.press("Escape");
      await dialogClosed(page, "#projectDialog");
      await focusIs(page, "#createProject");
    });

    await step(page, "新建与编辑项目及关闭焦点恢复", async () => {
      await navigate(page, "projects");
      await page.locator("#createProject").click();
      await focusIs(page, "#projectNameInput");
      await page.keyboard.press("Escape");
      await dialogClosed(page, "#projectDialog");
      await focusIs(page, "#createProject");
      await page.locator("#createProject").click();
      await page.locator("#projectNameInput").fill(projectName);
      await page.locator("#projectDescriptionInput").fill("真实表单创建，长中文简介验证布局与编辑保存。");
      await page.locator("#projectInstructionsInput").fill("使用简体中文；先读资料，再给出可验证的下一步。".repeat(8));
      const project = await submitAndRead(page, () => page.locator('#projectForm [type="submit"]').click(), "/api/workspace/projects");
      projectId = project.id;
      assert.ok(projectId);
      await textContains(page, "#projectName", projectName);
      await page.locator("#editProject").click();
      await page.locator("#projectNameInput").fill(editedProjectName);
      await page.locator("#projectDescriptionInput").fill("项目已编辑；持续推进产品基线与浏览器可用性。");
      await submitAndRead(page, () => page.locator('#projectForm [type="submit"]').click(), `/api/workspace/projects/${projectId}`);
      await textContains(page, "#projectName", editedProjectName);
      await screenshot(page, "project-light");
    });

    await step(page, "项目资料文件导入、检索与安全预览", async () => {
      assert.ok(projectId, "requires created project");
      await navigate(page, `projects/${projectId}`);
      await page.locator("#projectImport").click();
      await focusIs(page, "#documentTitle");
      await page.locator("#knowledgeFile").setInputFiles({ name: documentTitle, mimeType: "text/markdown", buffer: Buffer.from(documentContent, "utf8") });
      await value(page, "#documentTitle", documentTitle);
      await value(page, "#documentContent", documentContent);
      await value(page, "#documentProject", projectId);
      const imported = await submitAndRead(page, () => page.locator('#knowledgeForm [type="submit"]').click(), "/api/workspace/documents");
      documentId = imported.id;
      assert.ok(documentId);
      await textContains(page, "#projectDocuments", documentTitle);
      await page.locator("#projectDocuments button").filter({ hasText: documentTitle }).click();
      await visible(page, "#documentDialog");
      await textContains(page, "#previewContent", token);
      assert.equal(await page.evaluate(() => window.untrustedDocumentExecuted), undefined);
      await screenshot(page, "document-preview-light");
      await page.keyboard.press("Escape");
      await dialogClosed(page, "#documentDialog");
      await navigate(page, "knowledge");
      await page.locator("#knowledgeProject").selectOption(projectId);
      await page.locator("#knowledgeSearch").fill(token);
      await page.locator("#searchKnowledge").click();
      await textContains(page, "#searchResults", token);
      await screenshot(page, "knowledge-light");
      await page.locator("#searchResults button").filter({ hasText: documentTitle }).first().click();
      await visible(page, "#documentDialog");
      await textContains(page, "#previewTitle", documentTitle);
      await textContains(page, "#previewContent", "<script>");
      await page.keyboard.press("Escape");
      await dialogClosed(page, "#documentDialog");
    });

    await step(page, "晚到资料预览释放 Runtime 抽屉并接管焦点", async () => {
      assert.ok(projectId && documentId, "requires imported project document");
      for (const viewport of [{ width: 1024, height: 768 }, { width: 390, height: 844 }]) {
        await page.setViewportSize(viewport);
        await navigate(page, `projects/${projectId}`);
        await textContains(page, "#projectDocuments", documentTitle);
        let releaseResponse, resolveSeen, rejectSeen;
        const released = new Promise(resolve => { releaseResponse = resolve; });
        const requestSeen = new Promise((resolve, reject) => { resolveSeen = resolve; rejectSeen = reject; });
        const previewURL = `${baseURL}/api/workspace/documents/${documentId}`;
        // 保留真实 GET 响应，仅把浏览器收到响应的时间交给门闩；不伪造资料或绕过服务端读取。
        const delayedPreview = async route => {
          try {
            const response = await route.fetch();
            assert.equal(response.ok(), true, "real document GET succeeds before delaying delivery");
            resolveSeen();
            await released;
            await route.fulfill({ response });
          } catch (error) { rejectSeen(error); throw error; }
        };
        await page.route(previewURL, delayedPreview);
        try {
          await page.locator("#projectDocuments button").filter({ hasText: documentTitle }).click();
          await requestSeen;
          assert.equal(await page.locator("#documentDialog").evaluate(node => node.open), false);
          await page.locator("#inspectorToggle").click();
          await focusIs(page, "#inspectorClose");
          assert.equal(await page.locator("#mainContent").evaluate(node => node.inert), true);
          releaseResponse();
          await visible(page, "#documentDialog");
          await focusIs(page, '#documentDialog [data-close="documentDialog"]');
          await textContains(page, "#previewContent", token);
          assert.equal(await page.locator("#runtimeInspector").evaluate(node => node.classList.contains("open")), false);
          assert.equal(await page.locator("#runtimeInspector").evaluate(node => node.inert), true);
          assert.equal(await page.locator("#mainContent").evaluate(node => node.inert), false);
          assert.equal(await page.locator("#sidebar").evaluate(node => node.inert), viewport.width <= 800);
          assert.equal(await page.locator("body").evaluate(node => node.classList.contains("inspector-open")), false);
          await focusTrap(page, "#documentDialog");
          await noOverflow(page, `late preview modal/${viewport.width}`);
          await screenshot(page, `late-preview-${viewport.width}`);
          await page.keyboard.press("Escape");
          await dialogClosed(page, "#documentDialog");
          await focusIs(page, "#inspectorToggle");
          await page.locator("#editProject").click();
          await focusIs(page, "#projectNameInput");
          await page.keyboard.press("Escape");
          await dialogClosed(page, "#projectDialog");
          await focusIs(page, "#editProject");
        } finally {
          // 无论哪个断言失败都交付已读取响应并移除延迟，避免污染后续真实操作链。
          releaseResponse();
          await page.unroute(previewURL, delayedPreview);
        }
      }
      await page.setViewportSize({ width: 1440, height: 900 });
    });

    await step(page, "对话发送、执行完成与刷新持久化", async () => {
      await page.locator("#newChat").click();
      await visible(page, "#chatPage");
      if (projectId) await page.locator("#chatProject").selectOption(projectId);
      await page.locator("#prompt").fill(`请梳理工作台验收结果 ${runId}`);
      await page.locator("#send").click();
      await page.waitForFunction(() => location.hash.startsWith("#chat/") && document.querySelector("#thread .assistant"));
      sessionId = decodeURIComponent(new URL(page.url()).hash.split("/")[1]);
      await textContains(page, "#thread", "已收到你的任务");
      await page.waitForFunction(() => !document.querySelector("#prompt").disabled && !document.querySelector("#stopTurn").getClientRects().length);
      const before = await (await context.request.get(`${baseURL}/api/workspace/sessions/${sessionId}`)).json();
      assert.equal(before.turns.at(-1).status, "COMPLETED");
      assert.ok(before.turns.at(-1).run_id);
      // 观测台按独立读取节奏投影；代表性截图等待同一轮的完成状态，避免把短暂读取滞后定格。
      await textContains(page, "#inspectorState", "已完成");
      await textContains(page, "#inspectorDelivery", "已保存");
      await textContains(page, "#inspectorDelivery", "未验收");
      await screenshot(page, "desktop-chat-light");
      await page.locator("#themeToggle").click();
      await screenshot(page, "desktop-chat-dark");
      await page.reload({ waitUntil: "networkidle" });
      await textContains(page, "#thread", "已收到你的任务");
      const after = await (await context.request.get(`${baseURL}/api/workspace/sessions/${sessionId}`)).json();
      assert.equal(after.turns.length, before.turns.length);
      assert.equal(after.turns.at(-1).run_id, before.turns.at(-1).run_id);
    });

    await step(page, "会话编辑、置顶、搜索与导出", async () => {
      assert.ok(sessionId, "requires completed chat");
      await page.locator("#sessionMenu").click();
      await focusIs(page, "#sessionTitleInput");
      await page.locator("#sessionTitleInput").fill(sessionTitle);
      await page.locator("#sessionPinned").check();
      await submitAndRead(page, () => page.locator('#sessionForm [type="submit"]').click(), `/api/workspace/sessions/${sessionId}`);
      await dialogClosed(page, "#sessionDialog");
      await navigate(page, "sessions");
      await page.locator("#sessionSearch").fill(runId);
      await page.waitForFunction(title => [...document.querySelectorAll("#sessionCards .session-card")].some(node => node.textContent.includes(title)), sessionTitle);
      const card = page.locator("#sessionCards .session-card").filter({ hasText: sessionTitle });
      assert.equal(await card.count(), 1);
      await card.locator("button").click();
      assert.equal(await page.locator("#sessionPinned").isChecked(), true);
      const downloadPromise = page.waitForEvent("download");
      await page.locator("#sessionExport").click();
      const download = await downloadPromise;
      assert.equal(await download.failure(), null);
      const downloadedPath = await download.path();
      assert.ok(fs.readFileSync(downloadedPath, "utf8").includes("已收到你的任务"));
      await page.keyboard.press("Escape");
      await dialogClosed(page, "#sessionDialog");
      await screenshot(page, "sessions-dark");
    });

    await step(page, "会话草稿隔离、附件与 IME 防误发", async () => {
      assert.ok(sessionId, "requires completed chat");
      await navigate(page, `chat/${sessionId}`);
      const firstDraft = `第一会话未发草稿 ${runId}`;
      await page.locator("#prompt").fill(firstDraft);
      await page.locator("#chatFiles").setInputFiles({ name: `附件-${runId}.txt`, mimeType: "text/plain", buffer: Buffer.from(`仅用于草稿隔离 ${token}`) });
      await textContains(page, "#attachmentChips", `附件-${runId}.txt`);
      await page.keyboard.press("Control+Shift+O");
      await focusIs(page, "#prompt");
      await value(page, "#prompt", "");
      assert.equal(await page.locator("#attachmentChips").textContent(), "");
      await page.locator("#prompt").fill(`第二会话 ${runId}`);
      await page.locator("#send").click();
      await page.waitForFunction(first => location.hash.startsWith("#chat/") && !location.hash.endsWith(first) && document.querySelector("#thread .assistant"), sessionId);
      secondSessionId = decodeURIComponent(new URL(page.url()).hash.split("/")[1]);
      await page.waitForFunction(() => !document.querySelector("#stopTurn").getClientRects().length && document.querySelector("#thread .assistant").getClientRects().length);
      const secondDraft = `第二会话未发草稿 ${runId}`;
      await page.locator("#prompt").fill(secondDraft);
      await navigate(page, `chat/${sessionId}`);
      await value(page, "#prompt", firstDraft);
      await textContains(page, "#attachmentChips", `附件-${runId}.txt`);
      await navigate(page, `chat/${secondSessionId}`);
      await value(page, "#prompt", secondDraft);
      assert.equal(await page.locator("#attachmentChips").textContent(), "");
      const before = await (await context.request.get(`${baseURL}/api/workspace/sessions/${secondSessionId}`)).json();
      await page.locator("#prompt").dispatchEvent("compositionstart", { data: "中文" });
      assert.equal(await page.locator("#send").isDisabled(), true);
      await page.locator("#prompt").dispatchEvent("keydown", { key: "Enter", code: "Enter", keyCode: 229, isComposing: true });
      const during = await (await context.request.get(`${baseURL}/api/workspace/sessions/${secondSessionId}`)).json();
      assert.equal(during.turns.length, before.turns.length);
      await value(page, "#prompt", secondDraft);
      await page.locator("#prompt").dispatchEvent("compositionend", { data: "中文" });
      assert.equal(await page.locator("#send").isDisabled(), false);
      await page.locator("#prompt").focus();
      await page.keyboard.press("Shift+Enter");
      assert.ok((await page.locator("#prompt").inputValue()).includes("\n"));
      const after = await (await context.request.get(`${baseURL}/api/workspace/sessions/${secondSessionId}`)).json();
      assert.equal(after.turns.length, before.turns.length);
    });

    await step(page, "Goal 创建、明日计划、暂停与重新读取", async () => {
      assert.ok(sessionId, "requires created session");
      await navigate(page, "goals");
      await page.locator("#createGoal").click();
      await focusIs(page, "#goalTitleInput");
      const goalTitle = `浏览器长期目标 ${runId}`;
      await page.locator("#goalTitleInput").fill(goalTitle);
      await page.locator("#goalDescriptionInput").fill("仅验证创建、计划与状态持久化。验收：明日计划保留且暂停，不触发工作。".repeat(4));
      const goal = await submitAndRead(page, () => page.locator('#goalForm [type="submit"]').click(), "/api/workspace/goals");
      goalId = goal.goal_id;
      const card = page.locator("#goalCards .goal-list-item").filter({ hasText: goalTitle });
      await card.getByRole("button", { name: "安排工作", exact: true }).click();
      await focusIs(page, "#schedulePrompt");
      await page.locator("#scheduleSession").selectOption(sessionId);
      const prompt = `明日工作计划 ${runId}：检查资料并给出验收证据。`;
      await page.locator("#schedulePrompt").fill(prompt);
      const due = await page.evaluate(() => {
        const date = new Date(Date.now() + 24 * 60 * 60 * 1000);
        return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      });
      await page.locator("#scheduleDue").fill(due);
      const plan = await submitAndRead(page, () => page.locator('#scheduleForm [type="submit"]').click(), `/api/workspace/goals/${goalId}/schedules`);
      scheduleId = plan.schedule_id;
      assert.ok(scheduleId);
      await card.locator(".goal-schedules summary").click();
      await textContains(page, "#goalCards", prompt);
      await card.getByRole("button", { name: "暂停计划", exact: true }).click();
      await textContains(page, "#goalCards", "已暂停");
      await card.getByRole("button", { name: "暂停目标", exact: true }).click();
      await card.getByRole("button", { name: "恢复目标", exact: true }).waitFor();
      await screenshot(page, "goals-dark");
      await page.reload({ waitUntil: "networkidle" });
      await navigate(page, "goals");
      const reread = await (await context.request.get(`${baseURL}/api/workspace/schedules`)).json();
      const stored = reread.schedules.find(item => item.schedule_id === scheduleId);
      assert.equal(stored.enabled, false);
      assert.equal(stored.prompt, prompt);
      assert.ok(new Date(stored.due_at).getTime() > Date.now() + 20 * 60 * 60 * 1000);
      assert.deepEqual(stored.wakeups || [], []);
      await page.locator("#goalCards .goal-list-item").filter({ hasText: goalTitle }).getByRole("button", { name: "恢复目标", exact: true }).waitFor();
    });

    await step(page, "快捷命令、键盘选择及焦点恢复", async () => {
      await navigate(page, "chat");
      await page.locator("#prompt").focus();
      await page.keyboard.press("Control+k");
      await focusIs(page, "#commandSearch");
      await page.locator("#commandSearch").fill("知识库");
      await page.keyboard.press("ArrowDown");
      assert.ok(await page.locator("#commandSearch").getAttribute("aria-activedescendant"));
      await page.keyboard.press("Enter");
      await dialogClosed(page, "#commandPalette");
      await visible(page, "#knowledgePage");
      await page.locator("#commandToggle").click();
      await focusIs(page, "#commandSearch");
      await page.keyboard.press("Escape");
      await focusIs(page, "#commandToggle");
    });

    // 两套主题、四种尺寸逐页测量，长中文资料与真实对象共同参与布局，不只测空态。
    for (const viewport of [{ width: 1440, height: 900 }, { width: 1024, height: 768 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
      await step(page, `双主题全部页面无横向溢出 ${viewport.width}×${viewport.height}`, async () => {
        await page.setViewportSize(viewport);
        for (const theme of ["light", "dark"]) {
          await navigate(page, "settings");
          await page.locator(`[data-theme-choice="${theme}"]`).click();
          await page.waitForTimeout(350);
          for (const route of [sessionId ? `chat/${sessionId}` : "chat", "sessions", "projects", ...(projectId ? [`projects/${projectId}`] : []), "knowledge", "goals", "runtime", "settings"]) {
            await navigate(page, route);
            await noOverflow(page, `${viewport.width}x${viewport.height}/${theme}/${route.split("/")[0]}`);
          }
          await navigate(page, sessionId ? `chat/${sessionId}` : "chat");
          if (viewport.width === 390 || viewport.width === 320) await screenshot(page, `chat-${viewport.width}-${theme}`);
          if (viewport.width === 1024) await screenshot(page, `tablet-${theme}`);
        }
      });
      if (viewport.width <= 1120) await step(page, `导航与 Runtime 抽屉焦点及断点恢复 ${viewport.width}`, () => drawers(page, viewport, sessionId));
    }

    await step(page, "手机 Runtime 打开后切平板关闭不残留导航 inert", async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await navigate(page, "chat");
      await page.locator("#inspectorToggle").click();
      await page.waitForFunction(() => document.querySelector("#runtimeInspector").classList.contains("open"));
      await page.setViewportSize({ width: 1024, height: 768 });
      await page.locator("#inspectorClose").click();
      await page.waitForFunction(() => !document.querySelector("#runtimeInspector").classList.contains("open"));
      assert.equal(await page.locator("#sidebar").evaluate(node => node.inert), false, "desktop navigation must be released");
      await page.locator('#sidebar [data-page="projects"]').click();
      await visible(page, "#projectsPage");
      assert.equal(await page.locator("#mainContent").evaluate(node => node.inert), false);
    });

    await step(page, "标准服务实际页面加载", async () => {
      const standard = process.env.MYTH_UI_STANDARD_URL || "http://127.0.0.1:8769";
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(standard, { waitUntil: "networkidle" });
      await visible(page, "#chatPage");
      await navigate(page, "runtime");
      await visible(page, "#runtimeCore");
      assert.ok(await page.locator("#runtimeCore > *").count());
      await noOverflow(page, "standard service Runtime");
      await screenshot(page, "standard-runtime");
    });
  } finally {
    captureActive = false;
    report.identities = { projectId, documentId, sessionId, secondSessionId, goalId, scheduleId };
    report.unexpectedErrors = { console: report.console.filter(item => item.type === "error"), page: report.pageErrors, http: report.httpErrors, request: report.requestFailures };
    report.passed = report.steps.every(item => item.status === "PASS") && Object.values(report.unexpectedErrors).every(items => items.length === 0);
    fs.writeFileSync(path.join(outputDir, "qa-browser-report.json"), JSON.stringify(report, null, 2), "utf8");
    console.log(JSON.stringify({ passed: report.passed, steps: report.steps.length, failedSteps: report.steps.filter(item => item.status === "FAIL").map(item => item.name), unexpectedErrors: Object.fromEntries(Object.entries(report.unexpectedErrors).map(([key, items]) => [key, items.length])), report: path.join(outputDir, "qa-browser-report.json") }, null, 2));
    await browser.close();
    if (!report.passed) process.exitCode = 1;
  }
}

main().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
