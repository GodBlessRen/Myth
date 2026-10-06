// 真实浏览器负探针：守卫必须拒绝已知缺陷，否则矩阵通过没有保护意义。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
async function verifyAuditProbes(browser) {
  const page = await browser.newPage();
  const source = fs.readFileSync(path.join(__dirname, 'browser_accessibility.cjs'), 'utf8');
  const cases = [
    ['native-select', '<select id="bad" style="width:10px;height:10px;color:white;background:white"><option>选项</option></select>', ['contrast_failures', 'target_failures']],
    ['role-button', '<div id="bad" role="button" style="width:10px;height:10px">操作</div>', ['target_failures']],
    ['role-option', '<div id="bad" role="option" style="width:10px;height:10px">选项</div>', ['target_failures']],
    ['border', '<input id="bad" value="值" style="height:44px;border:1px solid white;color:black;background:white">', ['boundary_failures']],
    ['icon', '<button style="width:44px;height:44px"><svg id="bad" class="icon" style="width:18px;height:18px;stroke:white;fill:none" viewBox="0 0 24 24"><path d="M4 4h16v16H4Z"/></svg></button>', ['icon_failures']],
    ['opacity', '<p id="bad" style="opacity:.3">不可读的字</p>', ['contrast_failures']],
  ];
  try {
    for (const [name, html, expected] of cases) {
      await page.setContent('<body style="color:black;background:white;font:400 16px sans-serif">' + html + '</body>');
      const result = await page.evaluate(source + '\nauditSurface()');
      for (const key of expected) assert.ok(result[key]?.some(failure => failure.id === '#bad'), `${name}: missing ${key}`);
    }
    await page.setContent('<body style="color:black;background:white;font:400 16px sans-serif"><select id="good" style="height:44px;width:100px;border:1px solid black;color:black;background:white"><option>可读</option></select><div role="button" style="height:44px;width:100px">操作</div></body>');
    const result = await page.evaluate(source + '\nauditSurface()');
    assert.equal(result.control_count, 2);
    assert.ok(result.text_count >= 2);
    for (const key of ['contrast_failures', 'target_failures', 'boundary_failures', 'icon_failures']) assert.deepEqual(result[key], []);
    return {negative: cases.length, positive: 1};
  } finally { await page.close(); }
}
module.exports = {verifyAuditProbes};
