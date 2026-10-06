// Contrast math and alpha composition are tested without claiming browser rendering.
const test = require('node:test');
const assert = require('node:assert/strict');
const {rgba, over, contrast} = require('./browser_accessibility.cjs');

test('computed RGB and RGBA preserve channels and alpha', () => {
  assert.deepEqual(rgba('rgb(10, 20, 30)'), [10, 20, 30, 1]);
  assert.deepEqual(rgba('rgba(10, 20, 30, 0.25)'), [10, 20, 30, 0.25]);
  assert.deepEqual(rgba('rgb(10 20 30 / 0.5)'), [10, 20, 30, 0.5]);
});
test('unsupported and malformed colors fail closed', () => {
  for (const value of ['red', 'color(display-p3 1 0 0)', 'rgb(256,0,0)', 'rgba(0,0,0,2)', 'rgb(NaN,0,0)', 'rgb(0,0)']) {
    assert.throws(() => rgba(value));
  }
});
test('alpha composition retains the visible background', () => {
  assert.deepEqual(over([0, 0, 0, 0], [255, 255, 255, 1]), [255, 255, 255, 1]);
  assert.deepEqual(over([0, 0, 0, 0.5], [255, 255, 255, 1]), [127.5, 127.5, 127.5, 1]);
  assert.deepEqual(over([20, 30, 40, 0], [0, 0, 0, 0]), [0, 0, 0, 0]);
});
test('black and white have the exact WCAG endpoints', () => {
  assert.equal(contrast([0, 0, 0], [255, 255, 255]), 21);
  assert.equal(contrast([42, 42, 42], [42, 42, 42]), 1);
});
test('contrast is symmetric and does not round into a pass', () => {
  const a = [119, 119, 119], b = [255, 255, 255];
  assert.equal(contrast(a, b), contrast(b, a));
  assert.ok(contrast(a, b) < 4.5);
  assert.ok(contrast([118, 118, 118], b) >= 4.5);
});
test('translucent foreground has lower contrast than opaque text', () => {
  const black = [0, 0, 0, 1], white = [255, 255, 255, 1];
  assert.ok(contrast(over([0, 0, 0, 0.4], white), white) < contrast(black, white));
});
