// 新配置界面回归：通过真实控件、HTTP 和目录替身验证主题菜单、键盘、参数边界与自动价格。
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const base = process.env.MYTH_UI_BASE_URL || "http://127.0.0.1:8776";
const output = path.resolve(__dirname, "../output/playwright");
const review = path.resolve(__dirname, "../.impeccable/review");
const report = {checks: [], screenshots: [], errors: [], boundary: "真实公开 API 和 Runtime；价格/模型均为固定传输夹具，不代表远端服务"};
fs.mkdirSync(output, {recursive: true}); fs.mkdirSync(review, {recursive: true});

// 截图只在字体、异步报价与布局稳定后发生；一次批次覆盖双主题和手机。
async function capture(page, name) {
  await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(350);
  const file = path.join(output, `ink-${name}.png`);
  await page.screenshot({path: file, fullPage: true}); fs.copyFileSync(file, path.join(review, `ink-${name}.png`));
  report.screenshots.push(file);
}
async function main() {
  const browser = await chromium.launch({channel: "chrome", headless: true});
  const page = await browser.newPage({viewport: {width: 1440, height: 960}});
  page.on("pageerror", error => report.errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") report.errors.push(message.text()); });
  try {
    await page.goto(base + "/#settings", {waitUntil: "networkidle"});
    const provider = page.locator("#provider + .choice-trigger");
    await provider.click();
    await provider.press("Home"); await provider.press("ArrowDown"); await provider.press("Enter");
    assert.equal(await page.locator("#provider").inputValue(), "openai");
    assert.equal(await provider.getAttribute("aria-expanded"), "false");
    await page.locator("#model").fill("review-model");
    // 温度上限不同的提供方切换后，停用字段不能留下用户无法修复的旧值。
    await page.locator("#provider").selectOption("ollama");
    await page.locator("#temperature").fill("2");
    await page.locator("#provider").selectOption("anthropic");
    assert.equal(await page.locator("#temperature").inputValue(), "0");
    assert.equal(await page.locator("#temperature").isDisabled(), true);
    await page.locator("#model").fill("review-model");
    const switched = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/api/workspace/settings"));
    await page.locator("#saveSettings").click(); assert.equal((await switched).status(), 200);
    await page.locator("#provider").selectOption("openai"); await page.locator("#model").fill("review-model");
    await page.locator("#checkConnection").click();
    await page.waitForFunction(() => document.querySelector("#connectionResult").textContent.includes("2 个可用模型"));
    await page.waitForFunction(() => document.querySelector("#poolMainPricing .price-quote").textContent.includes("输入 $1"));
    assert.equal(await page.locator("#poolMainPricing [data-price-override]").isChecked(), false);
    report.checks.push("provider keyboard and automatic exact-model pricing");
    await page.locator("#checkConnection").click();
    await page.waitForFunction(() => document.querySelector("#modelOptions").children.length === 2);
    await page.locator("#model").fill("review-");
    const suggestions = page.locator(".choice-menu:popover-open");
    await suggestions.waitFor();
    assert.equal(await suggestions.locator('[role="option"]').count(), 2);
    await page.locator("#model").press("ArrowDown"); await page.locator("#model").press("Enter");
    assert.ok(["review-model", "review-reasoning"].includes(await page.locator("#model").inputValue()));
    report.checks.push("editable model suggestions use themed listbox");
    await page.locator("#model").fill("review-model");
    await page.locator("#poolAdd").click();
    const child = page.locator("#poolChildren .pool-child").last();
    await child.locator('[data-pool-field="model"]').fill("review-reasoning");
    await child.locator(".button-row button").first().click();
    await page.waitForFunction(() => document.querySelector('#poolChildren [data-pool-field="thinking"] option[value="high"]'));
    await child.locator(".pool-advanced > summary").first().click();
    const thinking = child.locator('[data-pool-field="thinking"] + .choice-trigger');
    await thinking.click(); await thinking.press("End"); await thinking.press("Enter");
    assert.equal(await child.locator('[data-pool-field="thinking"]').inputValue(), "high");
    const steps = child.locator('[data-pool-field="max_steps"]');
    await steps.fill("100000"); assert.equal(await steps.evaluate(node => node.checkValidity()), false);
    await steps.fill("4");
    await child.locator('[data-pool-field="provider"]').selectOption("ollama");
    const temperature = child.locator('[data-pool-field="temperature"]');
    await temperature.fill("100000"); assert.equal(await temperature.evaluate(node => node.checkValidity()), false);
    await temperature.fill("0.3");
    await temperature.fill("2");
    await child.locator('[data-pool-field="provider"]').selectOption("anthropic");
    assert.equal(await temperature.inputValue(), "0"); assert.equal(await temperature.isDisabled(), true);
    await child.locator('[data-pool-field="provider"]').selectOption("openai");
    await child.locator(".button-row button").first().click();
    await page.waitForFunction(() => document.querySelector('#poolChildren [data-pool-field="thinking"] option[value="high"]'));
    report.checks.push("child native thinking and independent numeric bounds");
    report.checks.push("temperature 2 to Claude resets inactive default in main and child");
    await page.waitForFunction(() => document.querySelector('#poolChildren .price-quote').textContent.includes("输入 $1"));
    for (const size of [{width: 1440, height: 960}, {width: 390, height: 844}, {width: 320, height: 740}]) {
      await page.setViewportSize(size);
      for (const mode of ["light", "dark"]) {
        if (await page.locator("html").getAttribute("data-theme") !== mode) await page.locator("#themeToggle").click();
        await provider.scrollIntoViewIfNeeded(); await provider.click();
        const popup = page.locator(".choice-menu:popover-open");
        const bounds = await popup.boundingBox();
        assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= size.width + 1 && bounds.y + bounds.height <= size.height + 1);
        const ground = await popup.evaluate(node => getComputedStyle(node).backgroundColor);
        assert.equal(ground, mode === "light" ? "rgb(248, 244, 237)" : "rgb(14, 16, 15)");
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        if (size.width !== 320) await capture(page, `settings-${size.width}-${mode}`);
        await provider.press("Escape"); assert.equal(await provider.getAttribute("aria-expanded"), "false");
      }
    }
    report.checks.push("popup palette and viewport containment at 1440/390/320 in both themes");
    for (const size of [{width: 1440, height: 960}, {width: 390, height: 844}]) {
      await page.setViewportSize(size);
      for (const mode of ["light", "dark"]) {
        if (await page.locator("html").getAttribute("data-theme") !== mode) await page.locator("#themeToggle").click();
        await page.locator("#poolMainPricing").scrollIntoViewIfNeeded();
        await capture(page, `pricing-${size.width}-${mode}`);
      }
    }
    await page.setViewportSize({width: 1440, height: 960});
    await page.evaluate(() => { location.hash = "chat"; });
    await page.locator("#prompt").waitFor();
    for (const mode of ["light", "dark"]) {
      if (await page.locator("html").getAttribute("data-theme") !== mode) await page.locator("#themeToggle").click();
      await capture(page, `home-${mode}`);
      assert.equal(await page.locator(".brand-symbol .ink-mark").evaluate(img => img.complete && img.naturalWidth > 0), true);
    }
    const composerChoice = page.locator("#chatProject + .choice-trigger");
    await composerChoice.click(); await composerChoice.press("Escape");
    report.checks.push("brush asset and composer selector");
    await page.evaluate(() => { location.hash = "knowledge"; });
    await page.locator("#importKnowledge").click();
    const dialog = page.locator("#knowledgeDialog");
    const dialogChoice = dialog.locator(".choice-trigger").first();
    await dialogChoice.click(); await dialogChoice.press("Escape");
    assert.equal(await dialog.evaluate(node => node.open), true);
    await dialogChoice.press("Escape"); assert.equal(await dialog.evaluate(node => node.open), false);
    report.checks.push("Escape dismisses menu before its owning dialog");
    const response = await page.request.post(base + "/api/workspace/settings", {data: {provider: "openai", model: "review-model", temperature: 100000}});
    assert.equal(response.status(), 400);
    assert.deepEqual(report.errors, []);
    console.log(JSON.stringify({passed: true, checks: report.checks.length, screenshots: report.screenshots.length}));
  } finally {
    fs.writeFileSync(path.join(output, "ink-settings-browser-report.json"), JSON.stringify(report, null, 2));
    await browser.close();
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
