import assert from "node:assert/strict";
import { test } from "node:test";
import { resolveChoiceValue } from "../../src/shared/ui/valueSelection";

test("F1 UI selection resolves only actual catalog identities without casts, mutation or translated-label matching", () => {
  const options = Object.freeze([Object.freeze({ value: "admin", label: "管理者" }), Object.freeze({ value: "view", label: "閲覧者" })]);
  for (const value of ["admin", "view"]) assert.equal(resolveChoiceValue(options, value), value);
  for (const value of ["管理者", "閲覧者", "owner", "__proto__", "constructor", "toString", ""]) assert.equal(resolveChoiceValue(options, value), undefined);
  assert.equal(resolveChoiceValue(["", "one"], ""), "");
  assert.equal(resolveChoiceValue([], "view"), undefined);
  assert.equal(JSON.stringify(options), '[{"value":"admin","label":"管理者"},{"value":"view","label":"閲覧者"}]');
});
