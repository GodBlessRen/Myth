// 静态页面身份解析仅服务 Node 合同测试；真实布局、原生校验与焦点仍由 Chromium 验收。
// 扫描完整标签和独立属性，排除注释与 raw-text 脚本，避免 data-id/字符串伪造节点。
function shellNodes(html, create) {
  const nodes = new Map(), stack = [];
  const clean = html.replace(/<!--[\s\S]*?-->/g, '').replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '');
  const tokens = /<\/?[a-z][\w-]*(?:\s+[^<>]*?)?\s*\/?>|[^<]+/gi;
  const voids = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr']);
  for (const match of clean.matchAll(tokens)) {
    const token = match[0];
    if (!token.startsWith('<')) { if (stack.at(-1)?.tagName === 'OPTION') stack.at(-1).textContent += token.trim(); continue; }
    const tag = /^<\/?([\w-]+)/.exec(token)[1].toLowerCase();
    if (token.startsWith('</')) { while (stack.length && stack.pop().tagName.toLowerCase() !== tag) {} continue; }
    const node = create(tag);
    const attributes = token.slice(token.indexOf(tag) + tag.length, token.lastIndexOf('>')).replace(/\/$/, '');
    for (const attr of attributes.matchAll(/(?:^|\s)([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)) {
      const name = attr[1].toLowerCase(), value = attr[2] ?? attr[3] ?? attr[4] ?? '';
      node.setAttribute(name, value);
      if (['id', 'value', 'class'].includes(name)) node[name === 'class' ? 'className' : name] = value;
      if (['disabled', 'required', 'checked', 'selected', 'hidden'].includes(name)) node[name] = true;
      if (name.startsWith('data-')) node.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
    }
    if (node.id) { if (nodes.has(node.id)) throw new Error('duplicate DOM id: ' + node.id); nodes.set(node.id, node); }
    if (stack.length) { stack.at(-1).append(node); node.parentElement = stack.at(-1); }
    if (!voids.has(tag) && !token.endsWith('/>')) stack.push(node);
    if (tag === 'option') { const select = [...stack].reverse().find(parent => parent.tagName === 'SELECT'); if (select && (!select.value || node.selected)) select.value = node.value; }
  }
  return nodes;
}
module.exports = {shellNodes};
