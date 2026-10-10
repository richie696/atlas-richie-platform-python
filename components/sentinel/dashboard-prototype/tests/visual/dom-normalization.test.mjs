import assert from "node:assert/strict";
import { test } from "node:test";
import { normalizeDom, normalizeLegacyDom } from "./dom-normalization.mjs";

const source = '<section id="accounts"><label id="_r_a_" for="_r_b_">Name</label><input id="_r_b_" aria-labelledby="_r_a_" class="x1" style="color:red"></section>';
test("generated IDs are stable without destroying targets or their relationships", () => {
  const normalized = normalizeDom(source);
  assert.equal(normalizeDom(source.replaceAll('_r_a_', '_r_x_').replaceAll('_r_b_', '_r_y_')), normalized);
  assert.equal(normalizeDom(normalized), normalized);
  assert.match(normalized, /id="accounts"/);
  assert.match(normalized, /input id="_react_id_1_" aria-labelledby="_react_id_0_"/);
});
test("real IDs, broken references, class/style and visible copy remain detectable", () => {
  for(const [before,after] of [['accounts','other'], ['aria-labelledby="_r_a_"','aria-labelledby="_r_missing_"'], ['class="x1"','class="x2"'], ['color:red','color:blue'], ['Name','Password']]) {
    assert.notEqual(normalizeDom(source.replace(before, after)), normalizeDom(source));
  }
});
test("HMR/pressable noise does not change canonical numbering", () => {
  assert.equal(normalizeDom('<script>"_r_noise_"</script>' + source.replace('class="x1"', 'class="x1" data-pressable-container="pending"')), normalizeDom(source));
});
test("legacy compatibility is isolated; the default never erases arbitrary IDs or SVG links", () => {
  assert.notEqual(normalizeDom('<svg><clipPath id="cut1"/><g clip-path="url(#cut1)"/></svg>'), normalizeDom('<svg><clipPath id="cut2"/><g clip-path="url(#cut2)"/></svg>'));
  assert.match(normalizeLegacyDom(source), /input id="_"/);
  assert.doesNotMatch(normalizeDom(source), /input id="_"/);
});
