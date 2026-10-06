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

test('data-id, comments and raw script strings cannot create a DOM identity', () => {
  for (const substitute of ['data-id="themeToggle"', 'id="removed"']) {
    const missing = html.replace('id="themeToggle"', substitute) + '<!-- <button id="themeToggle"></button> --><script>const sample = \'<button id="themeToggle">\';</script>';
    assert.throws(() => boot({}, {strictDOM: true, html: missing}), /null/);
  }
});

test('native provider options and execution parameter bounds match the API contract', () => {
  const h = boot({}, {strictDOM: true});
  assert.equal(h.$('provider').tagName, 'SELECT');
  assert.deepEqual(h.$('provider').options.map(option => option.value), ['ollama', 'openai', 'deepseek', 'anthropic', 'claude_oauth', 'kimi', 'chatgpt']);
  assert.equal(h.$('prompt').tagName, 'TEXTAREA');
  for (const [id, min, max] of [['maxSteps', '2', '32'], ['maxTokens', '128', '393216'], ['numCtx', '2048', '262144'], ['temperature', '0', '2']]) {
    assert.equal(h.$(id).tagName, 'INPUT');
    assert.equal(h.$(id).getAttribute('type'), 'number');
    assert.equal(h.$(id).getAttribute('min'), min);
    assert.equal(h.$(id).getAttribute('max'), max);
    assert.ok(h.$(id).getAttribute('required') !== undefined);
  }
});

test('a changed native option remains observable rather than becoming a fake valid provider', () => {
  const changed = html.replace('value="anthropic"', 'value="claude"');
  const h = boot({}, {strictDOM: true, html: changed});
  assert.equal(h.$('provider').options.some(option => option.value === 'anthropic'), false);
  assert.equal(h.$('provider').options.some(option => option.value === 'claude'), true);
});
