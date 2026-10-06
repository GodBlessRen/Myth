// 用户修订验收：精确色板、中央边线、提供方专用字段与真实等待品牌笔势。
// 仅使用专用固定 Provider 服务；输入/配置都通过可见控件，不改内部状态。
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
const base = process.env.MYTH_UI_BASE_URL || "http://127.0.0.1:8772";
const output = path.resolve(__dirname, "../output/playwright");
const review = path.resolve(__dirname, "../.impeccable/review");
const report = { alignment: [], checks: [], screenshots: [], errors: [], boundary: "真实 Runtime；固定 Provider 延长至1.8秒，只证明在途 UI" };

async function capture(page, name) {
  await page.evaluate(() => document.fonts.ready);
  // 在途反馈保留真实时间窗口；普通画面等布局过渡完成，避免捕捉窄轨道中间帧。
  if (!name.startsWith("waiting")) await page.waitForTimeout(350);
  const file = path.join(output, `brand-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  fs.copyFileSync(file, path.join(review, `brand-${name}.png`));
  report.screenshots.push(file);
}
async function align(page, label) {
  await page.waitForTimeout(320);
  const rectangles = await page.evaluate(() => {
    const thread = document.querySelector("#thread");
    const content = document.querySelector("#thread .assistant .message-main").getBoundingClientRect();
    const composer = document.querySelector("#composer").getBoundingClientRect();
    const box = thread.getBoundingClientRect(), style = getComputedStyle(thread);
    return { contentLeft: content.left, contentRight: content.right,
      composerLeft: composer.left, composerRight: composer.right,
      laneLeft: box.left + parseFloat(style.paddingLeft), laneRight: box.right - parseFloat(style.paddingRight) };
  });
  report.alignment.push({ label, ...rectangles });
  assert.ok(Math.abs(rectangles.contentLeft - rectangles.composerLeft) <= 1, label + " left");
  assert.ok(Math.abs(rectangles.contentRight - rectangles.composerRight) <= 1, label + " right");
}
async function main() {
  fs.mkdirSync(output, { recursive: true }); fs.mkdirSync(review, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  page.on("pageerror", error => report.errors.push(error.message));
  try {
    await page.goto(base, { waitUntil: "networkidle" });
    const data = await (await page.request.get(base + "/api/workspace")).json();
    let session;
    for (const candidate of data.sessions) {
      const detail = await (await page.request.get(base + "/api/workspace/sessions/" + candidate.id)).json();
      if (detail.messages.some(message => message.role === "assistant")) { session = candidate; break; }
    }
    assert.ok(session, "Run workspace browser acceptance first");
    const oldImage = await page.request.get(base + "/images/paper-study.png");
    assert.equal(oldImage.status(), 404);
    assert.equal(await page.locator(".welcome-art").count(), 0);
    assert.equal(await page.locator(".brand-symbol .brand-mark").evaluate(img => img.complete && img.naturalWidth > 0), true);
    report.checks.push("paper asset retired; shared brand mark SVG loads");
    await page.evaluate(id => { location.hash = "chat/" + id; }, session.id);
    await page.locator("#thread .assistant").first().waitFor();
    for (const size of [{width:1440,height:960},{width:1280,height:900},{width:1024,height:768},{width:390,height:844},{width:320,height:740}]) {
      await page.setViewportSize(size);
      for (const mode of ["light", "dark"]) {
        if (await page.locator("html").getAttribute("data-theme") !== mode) await page.locator("#themeToggle").click();
        assert.equal(await page.locator("body").evaluate(node => getComputedStyle(node).backgroundColor), mode === "light" ? "rgb(255, 254, 248)" : "rgb(14, 16, 15)");
        assert.equal(await page.locator('meta[name="theme-color"]').getAttribute("content"), mode === "light" ? "#FFFEF8" : "#0E100F");
        await align(page, size.width + "/" + mode);
        if (size.width > 1120) {
          await page.locator("#focusMode").click();
          await align(page, size.width + "/" + mode + "/focus");
          await page.locator("#focusMode").click();
        }
        if ([1440,390,320].includes(size.width)) await capture(page, `chat-${size.width}-${mode}`);
      }
    }
    report.checks.push("exact theme ground and meta; aligned lane at five widths and focus");
    await page.setViewportSize({width:1440,height:960});
    await page.evaluate(() => { location.hash = "settings"; });
    await page.locator("#settingsPage").waitFor();
    await page.locator("#provider").selectOption("anthropic");
    await page.locator("#poolAdd").click();
    const child = page.locator("#poolChildren .pool-child").last();
    const provider = child.locator('[data-pool-field="provider"]');
    assert.equal(await provider.inputValue(), "anthropic");
    await child.locator(".pool-advanced > summary").first().click();
    const context = child.locator('[data-pool-field="num_ctx"]');
    const address = child.locator('[data-pool-field="ollama_url"]');
    assert.equal(await context.isVisible(), false); assert.equal(await address.isVisible(), false);
    await provider.selectOption("ollama");
    assert.equal(await context.isVisible(), true); assert.equal(await address.isVisible(), true);
    await context.fill("16384");
    await provider.selectOption("openai");
    assert.equal(await context.isVisible(), false);
    await provider.selectOption("ollama");
    assert.equal(await context.inputValue(), "16384");
    await provider.selectOption("anthropic");
    await capture(page, "provider-fields-dark");
    report.checks.push("child inherits main provider; local fields hide and retain value across switches");
    // 未保存的表单不影响 Run；回到既有会话发送固定验收问题。
    await page.evaluate(id => { location.hash = "chat/" + id; }, session.id);
    await page.locator("#thread .assistant").first().waitFor();
    await page.locator("#prompt").fill("核对品牌笔势等待反馈。");
    await page.locator("#send").click();
    const spinner = page.locator(".typing .brand-wait");
    await spinner.waitFor({ state: "visible" });
    const active = await (await page.request.get(base + "/api/workspace/sessions/" + session.id)).json();
    assert.equal(active.turns.at(-1).status, "RUNNING");
    assert.equal(active.turns.at(-1).driver_active, true);
    assert.match(await page.locator("#inspectorState").innerText(), /运行/);
    await capture(page, "waiting-dark");
    // 旋转后 DOM boundingBox 包含透明角，使用原始 CSS 尺寸衡量14px符号。
    const size = await spinner.evaluate(node => ({width: parseFloat(getComputedStyle(node).width), height: parseFloat(getComputedStyle(node).height)}));
    assert.equal(size.width, 14); assert.equal(size.height, 14);
    await page.emulateMedia({ reducedMotion: "reduce" });
    assert.equal(await spinner.evaluate(node => getComputedStyle(node).animationName), "none");
    await spinner.waitFor({ state: "hidden" });
    report.checks.push("14px brand mark accompanies real active Driver, stops on completion, respects reduced motion");
    assert.deepEqual(report.errors, []);
    console.log(JSON.stringify({ passed: true, checks: report.checks.length, alignmentChecks: report.alignment.length }, null, 2));
  } finally {
    fs.writeFileSync(path.join(output,"brand-browser-report.json"),JSON.stringify(report,null,2));
    await browser.close();
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
