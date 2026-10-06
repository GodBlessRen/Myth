// 门禁自身的合同：防漏发现、零测试和子进程失败被吞。
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {discover, check} = require('../scripts/check_web.cjs');
const root = path.resolve(__dirname, '..');

test('new production scripts and rendering regressions are discovered without a CI name list', () => {
  const catalog = discover(root);
  assert.ok(catalog.scripts.includes('src/myth/webui/app.js'));
  assert.ok(catalog.tests.includes('tests/test_workspace_rendering_ui.cjs'));
  assert.ok(catalog.tests.includes('tests/test_web_gate_ui.cjs'));
  assert.deepEqual(catalog.tests, [...catalog.tests].sort());
});

test('an empty UI test directory cannot produce a successful gate', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'myth-web-gate-'));
  try {
    fs.mkdirSync(path.join(dir, 'src/myth/webui'), {recursive: true});
    fs.mkdirSync(path.join(dir, 'tests'));
    fs.writeFileSync(path.join(dir, 'src/myth/webui/app.js'), 'void 0;');
    assert.throws(() => discover(dir), /requires/);
  } finally { fs.rmSync(dir, {recursive: true, force: true}); }
});

test('every discovered script and test reaches the bounded child-process entrypoint', () => {
  const calls = [];
  const catalog = check(root, (command, args, options) => {
    calls.push(args);
    assert.equal(command, process.execPath);
    assert.equal(options.cwd, root);
    assert.equal(options.timeout, 120000);
    assert.equal(options.shell, undefined);
    return {status: 0};
  });
  assert.deepEqual(calls.slice(0, -1), catalog.scripts.map(file => ['--check', file]));
  assert.deepEqual(calls.at(-1), ['--test', ...catalog.tests]);
});

test('syntax failure, process errors and termination are never reported as passes', () => {
  for (const outcome of [{status: 1}, {status: null, signal: 'SIGTERM'}, {error: new Error('spawn failure')}]) {
    let calls = 0;
    assert.throws(() => check(root, () => { calls++; return outcome; }), /failed|failure/);
    assert.equal(calls, 1);
  }
});
