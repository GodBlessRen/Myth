// 两次异步跳转都需要表单所有权；服务端已保存事实不能反向覆盖用户的新输入。
const test = require('node:test');
const assert = require('node:assert/strict');
const {boot, deferred} = require('./ui_app_harness.cjs');

for (const change of ['provider', 'model', 'temperature']) {
  test(`automatic default model save preserves a newer ${change} edit`, async () => {
    const h = boot(), saved = deferred(), calls = [];
    h.state.data.settings = {provider: 'ollama', model: '', ollama_url: 'http://127.0.0.1:11434'};
    h.context.loadSettings();
    h.context.api = async (url) => {
      calls.push(url);
      return url === '/connection' ? {ready: true, details: {models: ['old-default']}} : saved.promise;
    };
    const pending = h.context.checkConnection(true);
    await new Promise(setImmediate);
    assert.deepEqual(calls, ['/connection', '/settings']);
    const next = {provider: 'deepseek', model: 'new-user-model', temperature: '0.8'}[change];
    h.$(change).value = next;
    if (change === 'provider') h.context.invalidateConnection();
    saved.resolve({provider: 'ollama', model: 'old-default', ollama_url: 'http://127.0.0.1:11434'});
    await pending;
    assert.equal(h.$(change).value, next);
    assert.equal(h.state.data.settings.model, 'old-default', 'server-saved fact remains accurate');
    assert.match(h.$('settingsSaved').textContent, /未保存/);
  });
}
