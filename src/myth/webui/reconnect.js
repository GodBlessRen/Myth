// 浏览器只读轮询的重连控制器；断连保留已显示数据，只重复 read 回调，不重发任务、工具或登录提交。
"use strict";

// 连续失败后的等待毫秒数；指数先封顶，第七次及以后保持一分钟。
function reconnectDelayMs(failures) {
  return Math.min(60000, 1000 * 2 ** Math.min(Math.max(0, failures - 1), 6));
}

// 单个控制器最多一个请求/计时器；依赖注入仅便于测试时间，业务 Run 状态仍归服务端。
function createReadReconnector({read, normalDelay, onWaiting = () => {}, onRestored = () => {},
  schedule = setTimeout, cancel = clearTimeout, now = Date.now}) {
  let stopped = true, running = false, timer = null, failures = 0, nextAt = null;
  // 每次完成读取后才安排下一次；stop 后的晚到响应不能重新启动循环。
  async function tick() {
    if (stopped || running) return;
    running = true;
    let delay;
    try {
      await read();
      if (failures && !stopped) onRestored();
      failures = 0;
      delay = normalDelay();
    } catch (error) {
      failures = Math.min(1000000, failures + 1);
      delay = reconnectDelayMs(failures);
      if (!stopped) onWaiting({failures, delayMs: delay, nextAt: now() + delay});
    } finally {
      running = false;
      if (!stopped) {
        nextAt = now() + delay;
        timer = schedule(tick, delay);
      }
    }
  }
  return {
    // 开始一次读取；重复 start 不形成平行轮询。
    start() { if (stopped) { stopped = false; return tick(); } },
    // 停止未来读取；不会把浏览器退出映射为 Run 终止。
    stop() { stopped = true; cancel(timer); timer = null; nextAt = null; },
    // 公开连接观察用于展示；不包含请求正文、认证或持久业务控制权。
    snapshot() { return {failures, nextAt, running, stopped}; },
  };
}
// 浏览器和 Node 固定夹具消费同一个实现；无额外依赖或服务启动。
if (typeof module !== "undefined") module.exports = {reconnectDelayMs, createReadReconnector};
