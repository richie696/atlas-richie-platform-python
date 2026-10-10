import assert from "node:assert/strict";
import { test } from "node:test";
import { scopedClasses } from "../../src/shared/ui/styles/scopedClasses.ts";

test("F3 scoped classes preserve semantic hooks and resolve only owned module properties", () => {
  const feature = { row: "row_feature", selected: "selected_feature" };
  const shared = { row: "row_shared", muted: "muted_shared" };
  assert.equal(scopedClasses([feature, shared], " row selected muted "),
    "row row_feature row_shared selected selected_feature muted muted_shared");
  assert.equal(scopedClasses([feature], "row row row_feature"), "row row_feature");
  assert.equal(scopedClasses([feature], "toString unknown"), "toString unknown");
  assert.equal(scopedClasses([feature], undefined), "");
  assert.equal(scopedClasses([feature], ""), "");
  assert.deepEqual(feature, { row: "row_feature", selected: "selected_feature" });
});
