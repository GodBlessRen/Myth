// 首屏主题初始化：仅投影浏览器偏好，在样式加载前执行，避免刷新闪白。
// 外部脚本遵循 script-src self；失败退回系统主题，不读写任何业务状态。
"use strict";
(() => {
  let saved = null;
  try {
    saved = localStorage.getItem("myth-theme");
  } catch (_) {
    // 隐私模式可能禁用存储，当前页面仍可正常显示。
  }
  const theme = saved === "light" || saved === "dark"
    ? saved
    : (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
})();
