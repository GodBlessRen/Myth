// Atelier UI 资源合同：新增只读视图不得削弱离线白名单或覆盖既有状态节点。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = path.join(__dirname, '../src/myth/webui');
const html = fs.readFileSync(path.join(base, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(base, 'atelier.css'), 'utf8');
const js = fs.readFileSync(path.join(base, 'atelier.js'), 'utf8');
const assets = fs.readFileSync(path.join(__dirname, '../src/myth/web_assets.py'), 'utf8');

test('atelier assets are declared exactly once and loaded after original UI', () => {
  for (const name of ['atelier.css', 'atelier.js']) {
    assert.equal(html.split('/' + name).length - 1, 1);
    assert.equal(assets.split('"/' + name + '":').length - 1, 1);
  }
  assert.ok(html.indexOf('/atelier.css') > html.indexOf('/app.css'));
  assert.ok(html.indexOf('/atelier.js') > html.indexOf('/studio.js'));
});

test('workbench preserves existing business-owned DOM identities', () => {
  for (const id of ['prompt', 'composer', 'thread', 'inspectorState', 'inspectorPulse',
    'inspectorTokens', 'executionSpine', 'inspectorTools', 'turnNotice', 'stopTurn',
    'lens-tab-overview', 'lens-tab-execution', 'lens-tab-resources']) {
    assert.match(html, new RegExp('id="' + id + '"'));
  }
});

test('view controls are accessible and do not post backend commands', () => {
  for (const id of ['densityToggle', 'runIndicator', 'sidebarResize', 'inspectorResize']) {
    assert.match(html, new RegExp('id="' + id + '"'));
  }
  assert.equal((html.match(/role="separator"/g) || []).length, 2);
  assert.match(js, /MutationObserver/);
  assert.match(js, /aria-valuenow/);
  assert.doesNotMatch(js, /fetch\s*\(|XMLHttpRequest|\/api\/|localStorage\.setItem\("token"/);
});

test('compact density and resize degrade on narrow screens and reduced motion', () => {
  assert.match(css, /data-density="compact"/);
  assert.match(css, /@media \(max-width: 1120px\)/);
  assert.match(css, /split-handle \{ display: none; \}/);
  assert.match(css, /prefers-reduced-motion: reduce/);
});
