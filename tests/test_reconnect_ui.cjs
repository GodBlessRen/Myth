// 固定时钟执行真实前端控制器；覆盖首次加载失败、完整退避、恢复重置及停止后晚到响应。
const test = require("node:test");
const assert = require("node:assert/strict");
const {createReadReconnector} = require("../src/myth/webui/reconnect.js");

test("initial failure retries reads at 1/2/4/8/16/32/60 seconds and resets after recovery", async () => {
  let online = false, reads = 0, restored = 0, time = 0;
  const queue = [], delays = [];
  const client = createReadReconnector({
    read: async () => { reads++; if (!online) throw new TypeError("offline"); },
    normalDelay: () => 3000,
    onRestored: () => restored++,
    schedule: (fn, ms) => { delays.push(ms); queue.push(fn); return queue.length; },
    cancel: () => {}, now: () => time,
  });
  await client.start();
  await client.start();
  assert.equal(reads, 1);
  for (let i = 0; i < 8; i++) { time += delays.at(-1); await queue.shift()(); }
  assert.deepEqual(delays, [1000, 2000, 4000, 8000, 16000, 32000, 60000, 60000, 60000]);
  online = true;
  await queue.shift()();
  assert.equal(restored, 1);
  assert.equal(client.snapshot().failures, 0);
  assert.equal(delays.at(-1), 3000);
  online = false;
  await queue.shift()();
  assert.equal(delays.at(-1), 1000);
  client.stop();
});

test("slow read remains single-flight and stopping cannot rearm a timer", async () => {
  let complete, reads = 0, schedules = 0;
  const client = createReadReconnector({
    read: () => { reads++; return new Promise(resolve => { complete = resolve; }); },
    normalDelay: () => 1000, schedule: () => schedules++, cancel: () => {},
  });
  const first = client.start();
  client.start();
  assert.equal(reads, 1);
  client.stop();
  complete();
  await first;
  assert.equal(schedules, 0);
  assert.equal(client.snapshot().stopped, true);
});
