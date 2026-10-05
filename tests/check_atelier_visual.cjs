// 艺术机构工作台的实际浏览器验收；只读取公开 HTTP 投影和 DOM，不修改 Runtime 状态。
// 截图和 JSON 是当前实现证据；固定 Provider 数据不能证明真实模型能力。
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

// 仅在独立本机验收服务执行；产物不进入生产静态包。
const output = path.resolve(__dirname, "../output/playwright");
const review = path.resolve(__dirname, "../.impeccable/review");
const report = { matrix: [], fonts: [], errors: [], screenshots: [], externalRequests: [] };
fs.mkdirSync(output, { recursive: true });
fs.mkdirSync(review, { recursive: true });

// 等待布局、字体和抽屉转换全部稳定，防止把过渡中的画面交给独立评审。
async function settle(page) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
}

// 一次批量截图覆盖双主题、桌面、手机和有内容状态，文件身份在确认轮保持不变。
async function capture(page, name) {
  await settle(page);
  const file = path.join(output, `atelier-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  fs.copyFileSync(file, path.join(review, `${name}.png`));
  report.screenshots.push(file);
}

// 主题通过产品真实按钮切换，不伪造页面的主题内部状态。
async function theme(page, target) {
  if (await page.locator("html").getAttribute("data-theme") !== target)
    await page.locator("#themeToggle").click();
  await settle(page);
}

// 校验页面与控件可达性，滚动布局测量包含标题、输入框、动态列表及常驻观测台。
async function measure(page, label) {
  const result = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const body = getComputedStyle(document.body);
    const visible = [...document.querySelectorAll(".page:not(.hidden) *")].filter(node => {
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== "hidden";
    });
    return {
      width, scrollWidth: document.documentElement.scrollWidth,
      paper: body.backgroundColor,
      offenders: visible.filter(node => {
        const rect = node.getBoundingClientRect();
        return rect.left < -1 || rect.right > width + 1;
      }).slice(0, 12).map(node => ({ id: node.id, tag: node.tagName, class: node.className })),
    };
  });
  report.matrix.push({ label, ...result });
  assert.ok(result.scrollWidth <= result.width + 1, `${label}: document overflow`);
  assert.deepEqual(result.offenders, [], `${label}: clipped visible content`);
}

async function main() {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  page.on("pageerror", error => report.errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") report.errors.push(message.text()); });
  page.on("request", request => {
    if (!new URL(request.url()).hostname.match(/^(127\.0\.0\.1|localhost)$/)) report.externalRequests.push(request.url());
  });
  try {
    await page.goto("http://127.0.0.1:8773", { waitUntil: "networkidle" });
    await settle(page);
    report.fonts = await page.evaluate(() => [...document.fonts].map(font => ({ family: font.family, status: font.status })));
    assert.ok(report.fonts.every(font => font.status === "loaded"));
    for (const mode of ["light", "dark"]) {
      await theme(page, mode);
      await measure(page, `home/1440/${mode}`);
      const paper = await page.locator("body").evaluate(node => getComputedStyle(node).backgroundColor);
      assert.equal(paper, mode === "light" ? "rgb(247, 240, 229)" : "rgb(25, 23, 29)");
      await capture(page, `home-${mode}`);
    }
    for (const viewport of [{ width: 390, height: 844 }, { width: 320, height: 740 }]) {
      await page.setViewportSize(viewport);
      for (const mode of ["light", "dark"]) {
        await theme(page, mode);
        await measure(page, `home/${viewport.width}/${mode}`);
        await capture(page, `mobile-${viewport.width}-${mode}`);
        const input = await page.locator("#prompt").boundingBox();
        assert.ok(input.y >= 0 && input.y + input.height <= viewport.height, "home input must remain visible");
      }
    }
    await page.goto("http://127.0.0.1:8772", { waitUntil: "networkidle" });
    const data = await (await page.request.get("http://127.0.0.1:8772/api/workspace")).json();
    const session = data.sessions.find(item => item.message_count > 0) || data.sessions[0];
    const project = data.projects[0];
    const routes = ["chat", `chat/${session.id}`, "sessions", "projects", `projects/${project.id}`, "knowledge", "goals", "runtime", "settings"];
    // 确认轮只重拍独立评审指明的手机会话/项目操作，避免反复运行全站矩阵。
    if (process.argv.includes("--review-controls")) {
      for (const viewport of [{ width: 390, height: 844 }, { width: 320, height: 740 }]) {
        await page.setViewportSize(viewport);
        for (const mode of ["light", "dark"]) {
          await theme(page, mode);
          for (const route of [`chat/${session.id}`, `projects/${project.id}`]) {
            await page.evaluate(route => { location.hash = route; }, route);
            await settle(page);
            await measure(page, `review/${route}/${viewport.width}/${mode}`);
            if (route.startsWith("chat")) {
              for (const id of ["themeToggle", "attachButton", "quickGoal", "send", "chatProject", "chatGoal"]) {
                const rectangle = await page.locator(`#${id}`).boundingBox();
                assert.ok(rectangle.width >= 44 && rectangle.height >= 44, `${id} needs a 44px touch target`);
              }
            }
            await capture(page, `${route.startsWith("chat") ? "chat" : "project"}-${viewport.width}-${mode}`);
          }
        }
      }
      console.log(JSON.stringify({ passed: true, focusedChecks: report.matrix.length }, null, 2));
      return;
    }
    for (const viewport of [{ width: 1440, height: 960 }, { width: 1024, height: 768 }, { width: 390, height: 844 }, { width: 320, height: 740 }]) {
      await page.setViewportSize(viewport);
      for (const mode of ["light", "dark"]) {
        await theme(page, mode);
        for (const route of routes) {
          await page.evaluate(route => { location.hash = route; }, route);
          await settle(page);
          await measure(page, `${route}/${viewport.width}/${mode}`);
          if (viewport.width === 1440 && ["settings", "goals", "runtime", `chat/${session.id}`].includes(route))
            await capture(page, `${route.split("/")[0]}-${mode}`);
        }
      }
    }
    // 200% 缩放使用真实布局重排，页面响应断点仍以 CSS 视口为准。
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.evaluate(() => { document.body.style.zoom = "2"; location.hash = "settings"; });
    await settle(page);
    await measure(page, "settings/200-percent");
    await capture(page, "settings-zoom-200");
    assert.deepEqual(report.errors, []);
    assert.deepEqual(report.externalRequests, []);
    console.log(JSON.stringify({ passed: true, checks: report.matrix.length, fonts: report.fonts, errors: report.errors }, null, 2));
  } finally {
    fs.writeFileSync(path.join(output, process.argv.includes("--review-controls") ? "atelier-controls-report.json" : "atelier-visual-report.json"), JSON.stringify(report, null, 2));
    await browser.close();
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1; });
