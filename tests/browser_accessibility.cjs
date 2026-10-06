// 浏览器可读性守卫：只测当前已显示的纯色表面，不改业务状态或替代人工视觉审阅。
// 对比度采用 WCAG 2.2 sRGB；图片/渐变背景明确记为未测，不猜测可读性。

// 只接受浏览器计算出的 sRGB/RGBA；未知色空间必须显式暴露。
function rgba(value) {
  const match = /^rgba?\(([^)]+)\)$/.exec(value);
  if (!match) throw new Error(`unsupported computed color: ${value}`);
  const parts = match[1].split(/[, /]+/).filter(Boolean).map(Number);
  if (parts.length === 3) parts.push(1);
  if (parts.length !== 4 || parts.some(x => !Number.isFinite(x)) ||
      parts.slice(0, 3).some(x => x < 0 || x > 255) || parts[3] < 0 || parts[3] > 1) {
    throw new Error(`invalid computed color: ${value}`);
  }
  return parts;
}

// 前景覆盖背景，保留 alpha；祖先 opacity 通过每一层合成而不是忽略。
function over(front, back) {
  const alpha = front[3] + back[3] * (1 - front[3]);
  if (!alpha) return [0, 0, 0, 0];
  return [...front.slice(0, 3).map((v, i) =>
    (v * front[3] + back[i] * back[3] * (1 - front[3])) / alpha), alpha];
}

// 计算未取整的相对亮度比；4.499 不会因展示四舍五入被判通过。
function contrast(first, second) {
  const luminance = color => color.slice(0, 3).reduce((sum, value, index) => {
    const channel = value / 255;
    return sum + (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4) * [0.2126, 0.7152, 0.0722][index];
  }, 0);
  const values = [luminance(first), luminance(second)].sort((a, b) => a - b);
  return (values[1] + 0.05) / (values[0] + 0.05);
}

// 从当前 DOM 测文本、placeholder、实际字重和触控框；关闭面板不冒充已测。
function auditSurface() {
  const report = {text_count: 0, control_count: 0, minimum_contrast: null, minimum_weight: null,
    contrast_failures: [], weight_failures: [], target_failures: [], boundary_failures: [], icon_failures: [], unmeasured: []};
  const modal = document.querySelector('dialog[open]');
  const root = modal || document.body;
  const visible = element => {
    if (!element.getClientRects().length || element.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
    for (let node = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility !== 'visible' || Number(style.opacity) === 0) return false;
    }
    return true;
  };
  const identity = element => element.id ? `#${element.id}` :
    `${element.tagName.toLowerCase()}.${String(element.className || '').trim().replace(/\s+/g, '.')}`;
  // 纯色逐层覆盖，分别计算字形前景和底色；系统画布仅在根透明时按白色处理。
  const pixel = (element, initial) => {
    let result = initial;
    for (let node = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.backgroundImage !== 'none') throw new Error('background image requires visual review');
      result = over(result, rgba(style.backgroundColor));
      result[3] *= Number(style.opacity);
    }
    return over(result, [255, 255, 255, 1]);
  };
  // 已停用控件仍检查字重，但不要求文本对比度；禁用状态的理由应由相邻文案说明。
  const text = (element, color, weight, kind) => {
    const id = identity(element);
    report.text_count++;
    report.minimum_weight = Math.min(report.minimum_weight ?? Infinity, weight);
    if (!Number.isFinite(weight) || weight < 400) report.weight_failures.push({id, kind, weight});
    if (element.closest(':disabled, [aria-disabled="true"]')) return;
    try {
      const ratio = contrast(pixel(element, rgba(color)), pixel(element, [0, 0, 0, 0]));
      const minimum = element.closest('.message-content') && kind !== 'placeholder' ? 7 : 4.5;
      report.minimum_contrast = Math.min(report.minimum_contrast ?? Infinity, ratio);
      if (ratio < minimum) report.contrast_failures.push({id, kind, ratio, minimum});
    } catch (error) {
      report.unmeasured.push({id, kind, reason: error.message});
    }
  };
  const controls = 'button, a[href], summary, input, textarea, select, [role="combobox"], [role="button"], [role="option"], [role="tab"], [role="checkbox"], [role="radio"], [role="switch"]';
  // 控件边界和语义图标要求3:1；装饰分隔线不承担操作识别，不纳入边界阈值。
  const nontext = (element, color, kind, adjacent = element) => {
    try {
      if (rgba(color)[3] === 0) return;
      const ratio = contrast(pixel(element, rgba(color)), pixel(adjacent, [0, 0, 0, 0]));
      if (ratio < 3) report[kind + '_failures'].push({id: identity(element), ratio, minimum: 3});
    } catch (error) { report.unmeasured.push({id: identity(element), kind, reason: error.message}); }
  };
  for (const element of root.querySelectorAll('*')) {
    if (!visible(element) || element.matches('script, style, option, path')) continue;
    const style = getComputedStyle(element);
    if (element.matches('svg.icon')) {
      nontext(element, style.stroke === 'none' ? style.color : style.stroke, 'icon');
      continue;
    }
    const hasText = [...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim());
    if (hasText || element.matches('input:not([type="checkbox"]):not([type="radio"]), textarea, select')) {
      text(element, style.color, Number(style.fontWeight), 'text');
    }
    if (element.matches('input[placeholder], textarea[placeholder]') && !element.value) {
      const placeholder = getComputedStyle(element, '::placeholder');
      const color = rgba(placeholder.color);
      color[3] *= Number(placeholder.opacity);
      text(element, `rgba(${color.join(',')})`, Number(placeholder.fontWeight), 'placeholder');
    }
    if (element.matches(controls + ', .composer, .search-field') && !element.matches(':disabled') && !element.closest('[aria-disabled="true"]')) {
      for (const edge of ['Top', 'Right', 'Bottom', 'Left']) {
        if (Number.parseFloat(style['border' + edge + 'Width']) > 0 && style['border' + edge + 'Style'] !== 'none')
          nontext(element, style['border' + edge + 'Color'], 'boundary', element.parentElement);
      }
    }
    if (!element.matches(controls) ||
        element.matches(':disabled') || element.closest('[aria-disabled="true"]')) continue;
    const rect = element.getBoundingClientRect();
    // 原生复选框的可操作外框由 label 提供；短图标必须有独立的四十像素目标。
    const labels = element.matches('input[type="checkbox"], input[type="radio"]') ? [...element.labels || []] : [];
    const bounds = labels.length ? labels[0].getBoundingClientRect() : rect;
    report.control_count++;
    if (bounds.width < 39.5 || bounds.height < 39.5) {
      report.target_failures.push({id: identity(element), width: bounds.width, height: bounds.height});
    }
  }
  return report;
}

// Node 单元测试只检查纯计算，不声称测试了真实浏览器布局。
if (typeof module !== 'undefined') module.exports = {rgba, over, contrast, auditSurface};
