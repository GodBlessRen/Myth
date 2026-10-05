// 三栏视图行为的浏览器回归：验证折叠、恢复、目录定位与无业务副作用。
// 只在固定 Provider 验收服务运行，新增一个会话问题以验证真实消息身份定位。
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const base = process.env.MYTH_UI_BASE_URL || "http://127.0.0.1:8772";
const output = path.resolve(__dirname, "../output/playwright");
const review = path.resolve(__dirname, "../.impeccable/review");
const report = { checks: [], errors: [], screenshots: [], boundary: "固定 Provider；布局偏好与公开持久事实" };

// 截图等待本地字体与有限过渡完成；暗色与手机使用相同真实数据。
async function capture(page, name) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(350);
  const file = path.join(output, `studio-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  fs.copyFileSync(file, path.join(review, `studio-${name}.png`));
  report.screenshots.push(file);
}
async function main() {
  fs.mkdirSync(output, { recursive: true }); fs.mkdirSync(review, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  page.on("pageerror", error => report.errors.push(error.message));
  try {
    await page.goto(base, { waitUntil: "networkidle" });
    const workspace = await (await page.request.get(base + "/api/workspace")).json();
    let session;
    for (const candidate of workspace.sessions) {
      const detail = await (await page.request.get(base + "/api/workspace/sessions/" + candidate.id)).json();
      if (detail.messages.some(message => message.role === "user")) { session = candidate; break; }
    }
    assert.ok(session, "Run existing workspace browser acceptance first");
    await page.evaluate(id => { location.hash = "chat/" + id; }, session.id);
    await page.locator("#thread .message").first().waitFor();
    if (await page.locator("#thread .message.user").count() < 2) {
      await page.locator("#prompt").fill("再核对这份工作台记录，只做总结。");
      await page.locator("#send").click();
      await page.waitForFunction(() => document.querySelectorAll("#thread .message.assistant").length >= 2 &&
        !document.querySelector("#send").classList.contains("hidden"));
    }
    await page.waitForFunction(() => !document.querySelector("#thread .typing"));
    const before = await (await page.request.get(base + "/api/workspace/sessions/" + session.id)).json();
    await page.locator("#prompt").fill("保留在输入框的未发送草稿");
    await page.locator('[data-nav-group="library"] > summary').click();
    assert.equal(await page.locator('[data-nav-group="library"]').getAttribute("open"), null);
    await page.locator("#sidebarCollapse").click();
    assert.equal(await page.locator('[data-page="projects"]').isVisible(), true, "rail preserves primary routes");
    await page.locator("#sidebarCollapse").click();
    assert.equal(await page.locator('[data-nav-group="library"]').getAttribute("open"), null, "rail restores folded group");
    report.checks.push("navigation folds survive rail expansion");
    await page.locator("#inspectorDock").click();
    await page.locator("#focusMode").click();
    await page.locator("#focusMode").click();
    assert.equal(await page.locator("body").evaluate(node => node.classList.contains("sidebar-collapsed")), false);
    assert.equal(await page.locator("body").evaluate(node => node.classList.contains("inspector-collapsed")), true);
    assert.equal(await page.locator("#prompt").inputValue(), "保留在输入框的未发送草稿");
    report.checks.push("focus restores both previous columns and draft");
    await page.locator("#inspectorDock").click();
    await page.locator("#focusMode").click();
    await page.locator("#sessionMenu").click();
    await page.locator("#sessionDialog").waitFor({ state: "visible" });
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#focusMode").getAttribute("aria-pressed"), "true", "modal owns the first Escape");
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#focusMode").getAttribute("aria-pressed"), "false");
    report.checks.push("modal Escape preserves focus layout; next Escape restores columns");
    await page.locator('[data-inspector-lens="execution"]').click();
    await page.locator('[data-inspector-lens="execution"]').press("ArrowRight");
    assert.equal(await page.locator('[data-inspector-lens="resources"]').getAttribute("aria-selected"), "true");
    assert.equal(await page.locator("#lens-resources").isVisible(), true);
    assert.equal(await page.locator("#lens-execution").isVisible(), false);
    report.checks.push("lens keyboard navigation and inactive focus exclusion");
    await page.reload({ waitUntil: "networkidle" });
    assert.equal(await page.locator('[data-inspector-lens="resources"]').getAttribute("aria-selected"), "true");
    await page.locator("#conversationIndex > summary").click();
    await page.locator("#conversationLinks button").first().click();
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains("user")), true);
    report.checks.push("directory returns focus to original persisted question");
    await page.locator("#conversationIndex > summary").click();
    await page.locator('[data-inspector-lens="overview"]').click();
    await capture(page, "directory-light");
    await page.locator("#conversationIndex > summary").click();
    await page.locator('[data-inspector-lens="execution"]').click();
    await capture(page, "execution-light");
    await page.locator("#themeToggle").click();
    await capture(page, "execution-dark");
    await page.locator("#focusMode").click();
    await capture(page, "focus-dark");
    await page.setViewportSize({ width: 1024, height: 768 });
    assert.equal(await page.locator("#focusMode").getAttribute("aria-pressed"), "false");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("#inspectorToggle").click();
    await capture(page, "inspector-mobile-dark");
    await page.locator("#inspectorClose").click();
    await page.locator("#menuToggle").click();
    await capture(page, "navigation-mobile-dark");
    await page.locator("#menuToggle").press("Escape");
    report.checks.push("focus exits at drawer breakpoint; phone retains all lenses and groups");
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.locator('[data-inspector-lens="overview"]').click();
    assert.equal(await page.locator("#lens-overview").evaluate(node => node.getAnimations().length), 0);
    report.checks.push("reduced motion skips lens animation");
    const after = await (await page.request.get(base + "/api/workspace/sessions/" + session.id)).json();
    assert.deepEqual(after.turns.map(turn => [turn.run_id, turn.status]), before.turns.map(turn => [turn.run_id, turn.status]));
    assert.deepEqual(after.messages, before.messages);
    assert.deepEqual(report.errors, []);
    report.checks.push("all layout operations preserve Runtime and messages");
    console.log(JSON.stringify({ passed: true, checks: report.checks.length }, null, 2));
  } finally {
    fs.writeFileSync(path.join(output, "studio-browser-report.json"), JSON.stringify(report, null, 2));
    await browser.close();
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
