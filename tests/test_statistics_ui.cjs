// 使用生产展示规则验证单位/覆盖/缺测；不启动 UI 或模拟远端供应商速度。
const test = require("node:test");
const assert = require("node:assert/strict");
const {statisticsDuration, sessionStatisticsRows} = require("../src/myth/webui/statistics.js");

// 图示四项使用同一格式：长用时保留总分钟，TTFT 与 TPS 不由浏览器再平均。
test("session statistics render minutes, measured TTFT and end-to-end TPS", () => {
  const rows = sessionStatisticsRows({model_wall_ms: 2023000, tool_wall_ms: 9293000,
    average_ttft_ms: 2100, output_tps: 280, model_timing_samples: 5, model_attempts: 5,
    tool_timing_samples: 20, tool_calls: 20, ttft_samples: 5, tps_samples: 5});
  assert.deepEqual(rows.map(row => row.value), ["33分43秒", "154分53秒", "2.1秒", "280 tok/s"]);
  assert.match(rows[3].title, /端到端/);
});

// 缺测、负数及坏值不能显示伪造零或 NaN；已测零仍是零。
test("missing and invalid observations stay unreported while zero is preserved", () => {
  for (const value of [null, undefined, true, "100", -1, NaN, Infinity]) {
    assert.equal(statisticsDuration(value), "未报告");
  }
  assert.equal(statisticsDuration(0), "0毫秒");
  const rows = sessionStatisticsRows({output_tps: Infinity});
  assert.deepEqual(rows.map(row => row.value), ["未报告", "未报告", "未报告", "未报告"]);
});

// 老调用没有计量时显示覆盖，不把已知部分伪装成完整会话累计。
test("partial timing coverage remains visible", () => {
  const rows = sessionStatisticsRows({model_wall_ms: 1500, model_timing_samples: 1, model_attempts: 3,
    tool_wall_ms: null, tool_timing_samples: 0, tool_calls: 2});
  assert.equal(rows[0].value, "1.5秒 · 1/3");
  assert.equal(rows[1].value, "未报告 · 0/2");
});
