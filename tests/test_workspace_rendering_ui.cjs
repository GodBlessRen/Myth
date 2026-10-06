// Real app.js functions with a lightweight DOM; no provider or browser-rendering claims.
const test = require('node:test');
const assert = require('node:assert/strict');
const {boot, session, deferred} = require('./ui_app_harness.cjs');

test('UNKNOWN is a warning with an actionable message and intact technical evidence', () => {
  const h = boot();
  for (const status of ['UNKNOWN', 'INTERRUPTED', 'FAILED']) {
    const value = session('one');
    value.turns = [{run_id: 'run', status, current_step: 0, activities: [], error: '<detail> original cause'}];
    h.state.session = value;
    h.context.renderChat(value);
    const notice = h.$('turnNotice');
    assert.equal(notice.classList.contains('error'), status === 'FAILED');
    assert.equal(notice.classList.contains('warning'), status !== 'FAILED');
    assert.match(notice.textContent, /<detail> original cause/);
    if (status !== 'FAILED') {
      const detail = notice.children.find(node => node.tagName === 'DETAILS');
      assert.ok(detail);
      assert.equal(detail.children[1].textContent, '<detail> original cause');
    }
  }
});

test('long tool results expand without discarding or mutating the original result', () => {
  const h = boot(), content = 'A'.repeat(3001) + 'END';
  const turn = {run_id: 'run', activities: [{step: 1, state: 'DONE', decision: {decision_type: 'tool_call', capability_id: 'file.read'}, result: Object.freeze({content})}]};
  const group = h.context.toolGroup(turn), item = group.children[1];
  const output = item.children.find(node => node.tagName === 'PRE');
  const more = item.children.find(node => node.tagName === 'BUTTON');
  assert.equal(output.textContent.length, 3000);
  assert.ok(more, 'truncated output needs an explicit expansion control');
  assert.equal(more.getAttribute('aria-expanded'), 'false');
  more.onclick();
  assert.equal(output.textContent, content);
  assert.equal(more.getAttribute('aria-expanded'), 'true');
  more.onclick();
  assert.equal(output.textContent.length, 3000);
  assert.equal(turn.activities[0].result.content, content);
});

test('short tool results do not add a pointless expansion control', () => {
  const h = boot();
  const turn = {run_id: 'run', activities: [{step: 1, state: 'DONE', decision: {decision_type: 'tool_call'}, result: {content: 'short'}}]};
  const item = h.context.toolGroup(turn).children[1];
  assert.equal(item.children.filter(node => node.tagName === 'BUTTON').length, 0);
  assert.equal(item.children.find(node => node.tagName === 'PRE').textContent, 'short');
});

test('thread indexes preserve first-match turns and original artifact order without mutation', () => {
  const h = boot();
  const first = Object.freeze({run_id: 'same'}), later = Object.freeze({run_id: 'same'});
  const a = Object.freeze({run_id: 'same', decision_id: 'a'}), b = Object.freeze({run_id: 'other', decision_id: 'b'}), c = Object.freeze({run_id: 'same', decision_id: 'c'});
  const value = Object.freeze({turns: Object.freeze([first, later]), artifacts: Object.freeze([a, b, c])});
  const indexed = h.context.indexThread(value);
  assert.equal(indexed.turns.get('same'), first);
  assert.deepEqual([...indexed.artifacts.get('same')], [a, c]);
  assert.deepEqual([...indexed.artifacts.get('other')], [b]);
  assert.equal(indexed.turns.get('absent'), undefined);
  assert.equal(value.artifacts.length, 3);
});

test('all four API namespaces keep request identity and the same bounded transport', async () => {
  const h = boot(), calls = [], timers = [], cleared = [];
  h.context.setTimeout = (callback, delay) => { timers.push({callback, delay}); return timers.length; };
  h.context.clearTimeout = id => cleared.push(id);
  h.context.fetch = async (url, request) => { calls.push({url, request}); return {ok: true, json: async () => ({accepted: true})}; };
  const prefixes = {api: '/api/workspace', authApi: '/api/auth/chatgpt', claudeAuthApi: '/api/auth/claude', providerAuthApi: '/api/auth/providers'};
  for (const [name, prefix] of Object.entries(prefixes)) {
    await h.context[name]('/status');
    await h.context[name]('/start', {request_id: 'fixed-id'});
    const [read, write] = calls.slice(-2);
    assert.equal(read.url, prefix + '/status');
    assert.equal(read.request.method, 'GET');
    assert.equal(read.request.body, undefined);
    assert.equal(write.url, prefix + '/start');
    assert.equal(write.request.method, 'POST');
    assert.equal(JSON.parse(write.request.body).request_id, 'fixed-id');
    assert.equal(write.request.headers['Content-Type'], 'application/json');
  }
  assert.equal(calls.length, 8);
  assert.ok(timers.every(timer => timer.delay === 20000));
  assert.equal(cleared.length, 8);
});

test('response-body parsing remains inside the timeout and failure never retries a write', async () => {
  const h = boot(), body = deferred();
  let fired, cleaned = 0, calls = 0, signal;
  h.context.setTimeout = callback => { fired = callback; return 1; };
  h.context.clearTimeout = () => cleaned++;
  h.context.fetch = async (url, request) => { calls++; signal = request.signal; return {ok: true, json: () => body.promise}; };
  const pending = h.context.api('/sessions', {request_id: 'fixed-id'});
  await Promise.resolve();
  assert.equal(cleaned, 0);
  fired();
  assert.equal(signal.aborted, true);
  const error = new Error('fixture abort'); error.name = 'AbortError';
  body.reject(error);
  await assert.rejects(pending, {name: 'AbortError'});
  assert.equal(calls, 1);
  assert.equal(cleaned, 1);
});

test('HTTP and malformed JSON failures release timers without suppressing their cause', async () => {
  const h = boot();
  let cleared = 0, calls = 0;
  h.context.clearTimeout = () => cleared++;
  h.context.fetch = async () => { calls++; return {ok: false, status: 409, json: async () => ({error: 'state conflict'})}; };
  await assert.rejects(h.context.claudeAuthApi('/start', {}), /state conflict/);
  h.context.fetch = async () => { calls++; return {ok: true, json: async () => { throw new SyntaxError('bad fixture'); }}; };
  await assert.rejects(h.context.providerAuthApi('/connect', {}), /bad fixture/);
  assert.equal(calls, 2);
  assert.equal(cleared, 2);
});

test('brand waiting state uses the current local asset and visible motion class', () => {
  const h = boot(), still = h.context.brandMark(), working = h.context.brandMark(true);
  assert.equal(still.src, '/myth-mark.svg');
  assert.equal(still.classList.contains('brand-wait'), false);
  assert.equal(working.classList.contains('brand-wait'), true);
  assert.equal(working.width, 16);
  assert.equal(working.height, 16);
});
