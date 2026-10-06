// 真实 HTML 身份与全部启动绑定共同验证；这不替代浏览器布局和焦点测试。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {boot} = require('./ui_app_harness.cjs');
const html = fs.readFileSync(path.join(__dirname, '../src/myth/webui/index.html'), 'utf8');

test('the production shell satisfies every synchronous app startup binding', () => {
  const h = boot({}, {strictDOM: true});
  assert.equal(h.document.getElementById('mobileMenu'), null);
  assert.equal(typeof h.$('menuToggle').onclick, 'function');
  assert.equal(h.$('send').disabled, true);
});

test('strict startup cannot invent a required element removed from the real HTML', () => {
  const missing = html.replace(/\bid="themeToggle"/, 'id="removed-theme-toggle"');
  assert.notEqual(missing, html);
  assert.throws(() => boot({}, {strictDOM: true, html: missing}), /null/);
});
