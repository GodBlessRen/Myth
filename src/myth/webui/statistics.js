// 会话统计的纯展示规则；服务端拥有计量/身份，浏览器只格式化公开数值，不估算缺测 Token 或时间。
"use strict";

// 实测毫秒转成人可读单位；保留零，拒绝缺失、NaN、负数及隐式布尔/文本转换。
function statisticsDuration(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "未报告";
  if (value < 1000) return `${Math.round(value)}毫秒`;
  if (value < 60000) return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}秒`;
  const seconds = Math.floor(value / 1000);
  return `${Math.floor(seconds / 60)}分${seconds % 60}秒`;
}

// 构造同一会话的四项统计；部分耗时显示测量覆盖，TPS 明确使用端到端口径。
function sessionStatisticsRows(stats = {}) {
  // 已报告部分可以相加，但不能让旧数据缺测看上去像完整累计。
  const coverage = (samples, total) => Number.isInteger(samples) && Number.isInteger(total) && samples < total
    ? ` · ${samples}/${total}` : "";
  const tps = typeof stats.output_tps === "number" && Number.isFinite(stats.output_tps) && stats.output_tps >= 0
    ? `${stats.output_tps.toFixed(1).replace(/\.0$/, "")} tok/s` : "未报告";
  return [
    {label: "模型用时", value: statisticsDuration(stats.model_wall_ms) + coverage(stats.model_timing_samples, stats.model_attempts),
      title: "会话内已记录的模型调用累计用时，包含网络/认证等待与已知失败；并发调用分别累加。"},
    {label: "工具调用用时", value: statisticsDuration(stats.tool_wall_ms) + coverage(stats.tool_timing_samples, stats.tool_calls),
      title: "会话内已记录的真实工具执行累计用时；复用收据不重复计时，旧数据缺测不估算。"},
    {label: "首 token 平均（TTFT）", value: statisticsDuration(stats.average_ttft_ms),
      title: `从模型调用开始到首个非空文本增量，按有效调用平均；已报告 ${stats.ttft_samples || 0} 次。非流式调用不估算。`},
    {label: "输出速度（TPS）", value: tps,
      title: `端到端：成功调用的输出 Token 总量 ÷ 同一批调用总用时，包含首 token 等待；已报告 ${stats.tps_samples || 0} 次。`},
  ];
}

// Node 回归与浏览器使用同一格式化实现；无 DOM/I/O/持久业务状态。
if (typeof module !== "undefined") module.exports = {statisticsDuration, sessionStatisticsRows};
