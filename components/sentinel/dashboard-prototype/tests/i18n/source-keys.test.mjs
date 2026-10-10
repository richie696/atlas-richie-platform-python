import { test } from "node:test";
import assert from "node:assert/strict";
import {
  collectExportedTranslationMaps,
  scanTranslationKeys,
  interpolationNames,
} from "./source-keys.mjs";

test("i18n AST: conditional keys exclude comparison literals and interpolation data", () => {
  const result = scanTranslationKeys(
    `const value = t(database.usage === "production" ? "setup.production" : "setup.local", {label: "Nacos"});`,
  );
  assert.deepEqual(result.keys, ["setup.production", "setup.local"]);
  assert.deepEqual(result.templates, []);
  assert.deepEqual(result.variable, []);
});
test("i18n AST: TS types/comments are not keys, named key constants and multiline fallbacks are checked", () => {
  const result = scanTranslationKeys(`// t("comment.missing")
  type SomeKey="type.not.translation";const labelKey="field.label";const object={descriptionKey:"field.description"};
  const labels=t(["first.key", "fallback.key"],{name:"business.data"});`);
  assert.deepEqual(result.keys, ["field.label", "field.description", "first.key", "fallback.key"]);
});
test("i18n AST: dynamic templates stay rejected and unresolved variable keys are explicitly reported", () => {
  const result = scanTranslationKeys('t(`field.${name}`); t(labelKey); t("static.key")');
  assert.deepEqual(result.templates, ["`field.${name}`"]);
  assert.equal(result.variable.length, 2);
  assert.deepEqual(result.keys, ["static.key"]);
});
test("i18n AST: finite local translation maps and aliases resolve all possible keys", () => {
  const result = scanTranslationKeys(`
    const labels = Object.freeze({ ready: "state.ready", failed: "state.failed" });
    const alias = labels;
    const fallback = true ? alias.ready : "state.unknown";
    t(alias[state]); t(fallback);
  `);
  assert.deepEqual(result.keys, ["state.ready", "state.failed", "state.unknown"]);
  assert.deepEqual(result.variable, []);
});
test("i18n AST: computed enum keys do not hide finite translation-map values", () => {
  const result = scanTranslationKeys(`
    const state = "active" as const;
    const labels = Object.freeze({ [state]: "state.active", inactive: "state.inactive" });
    t(labels[currentState]);
  `);
  assert.deepEqual(result.keys, ["state.active", "state.inactive"]);
  assert.deepEqual(result.variable, []);
});
test("i18n AST: imported finite translation maps resolve by their exported owner", () => {
  const maps = collectExportedTranslationMaps(`
    export const STATUS_LABEL_KEY = Object.freeze({
      ready: "status.ready",
      failed: "status.failed",
    });
  `);
  const result = scanTranslationKeys(
    `import { STATUS_LABEL_KEY as labels } from "./labels"; t(labels[state]); t(labels.ready);`,
    {
      resolveImportedKeys: (source, name, property) => {
        assert.equal(source, "./labels");
        assert.equal(name, "STATUS_LABEL_KEY");
        const entries = maps.get(name);
        return property === null ? [...entries.values()].flat() : entries.get(property);
      },
    },
  );
  assert.deepEqual(result.keys, ["status.ready", "status.failed"]);
  assert.deepEqual(result.variable, []);
});
test("i18n AST: translation fields on finite mapped rows resolve without hiding dynamic data", () => {
  const result = scanTranslationKeys(`
    const rows = Object.freeze([
      { id: "one", labelKey: "choice.one" },
      { id: "two", labelKey: "choice.two" },
    ]);
    rows.map((row) => t(row.labelKey));
  `);
  assert.deepEqual(result.keys, ["choice.one", "choice.two"]);
  assert.deepEqual(result.variable, []);
});
test("i18n AST: imported finite presentation arrays resolve only the selected translation field", () => {
  const maps = collectExportedTranslationMaps(`
    export const OPTIONS = Object.freeze([
      { id: "one", labelKey: "choice.one", descriptionKey: "choice.one.description" },
      { id: "two", labelKey: "choice.two", descriptionKey: "choice.two.description" },
    ]);
  `);
  const result = scanTranslationKeys(
    `import { OPTIONS as choices } from "./choices"; choices.map((choice) => t(choice.labelKey));`,
    {
      resolveImportedKeys: (source, name, property) => {
        assert.equal(source, "./choices");
        assert.equal(name, "OPTIONS");
        return property === null
          ? [...maps.get(name).values()].flat()
          : maps.get(name)?.get(property);
      },
    },
  );
  assert.deepEqual(result.keys, ["choice.one", "choice.two"]);
  assert.deepEqual(result.variable, []);
});
test("i18n AST: destructured map fields resolve only the selected field across literal rows", () => {
  const result = scanTranslationKeys(`
    const phases = [
      { labelKey: "publication.validation", state: "pending" },
      { labelKey: "publication.readback", state: "applied" },
    ];
    phases.map(({ labelKey, state }) => t(labelKey));
  `);
  assert.deepEqual(result.keys, ["publication.validation", "publication.readback"]);
  assert.deepEqual(result.variable, []);
});
test("i18n AST: destructured map fields fail closed for dynamic rows and computed fields", () => {
  const result = scanTranslationKeys(`
    const rows = getRows();
    rows.map(({ labelKey: key }) => t(key));
    const unsafe = [{ labelKey: "choice.safe" }, { [field]: "choice.unknown" }];
    unsafe.map(({ labelKey }) => t(labelKey));
  `);
  assert.equal(result.variable.length, 2);
  assert.ok(result.variable.includes("t(key)"));
  assert.ok(result.variable.includes("t(labelKey)"));
});
test("i18n AST: finite local record lookups resolve selected translation fields", () => {
  const result = scanTranslationKeys(`
    const messages = Object.freeze({
      flow: { label: "rules.flow.label", description: "rules.flow.description" },
      degrade: { label: "rules.degrade.label", description: "rules.degrade.description" },
    });
    const copy = messages[kind];
    t(copy.label);
    t(copy.description);
  `);
  assert.deepEqual(result.keys, [
    "rules.flow.label",
    "rules.degrade.label",
    "rules.flow.description",
    "rules.degrade.description",
  ]);
  assert.deepEqual(result.variable, []);
});
test("i18n AST: map rows with missing, computed, or non-literal translation values stay unresolved", () => {
  const result = scanTranslationKeys(`
    const label = "choice.one";
    const rows = [{ labelKey: "choice.one" }, { [field]: "choice.two" }];
    rows.map((row) => t(row.labelKey));
    const keys = ["choice.one", label];
    keys.map((key) => t(key));
  `);
  assert.equal(result.variable.length, 1);
  assert.match(result.variable[0], /t\(row\.labelKey\)/);
});
test("i18n AST: finite string lists consumed by map and for-of resolve every key", () => {
  const result = scanTranslationKeys(`
    const headers = ["table.name", "table.status"] as const;
    headers.map((key) => t(key));
    for (const key of headers) t(key);
  `);
  assert.deepEqual(result.keys, ["table.name", "table.status"]);
  assert.deepEqual(result.variable, []);
});
test("i18n AST: imported finite string lists resolve keys at the consumer", () => {
  const maps = collectExportedTranslationMaps(`
    export const APPLICATION_TABLE_HEADERS = Object.freeze(["table.name", "table.status"]);
  `);
  const result = scanTranslationKeys(
    `import { APPLICATION_TABLE_HEADERS } from "./headers"; APPLICATION_TABLE_HEADERS.map((key) => t(key));`,
    {
      resolveImportedKeys: (source, name, property) => {
        assert.equal(source, "./headers");
        assert.equal(property, undefined);
        return [...(maps.get(name)?.values() ?? [])].flat();
      },
    },
  );
  assert.deepEqual(result.keys, ["table.name", "table.status"]);
  assert.deepEqual(result.variable, []);
});
test("i18n interpolation: escaping/number formatting does not hide a missing translated parameter", () => {
  assert.deepEqual(interpolationNames("{{min}} – {{ max, number }} / {{- name}} {{min}}"), [
    "max",
    "min",
    "name",
  ]);
  assert.deepEqual(interpolationNames("no values"), []);
});
test("i18n AST: form, request and owner identities are not translation hints, even when dotted or empty", () => {
  const result = scanTranslationKeys(
    `const formKey="";const ownerKey="session.test";const object={formKey:"",requestKey:"operation.42",labelKey:"field.label",valueKey:"missing-value",statusLabelKey:"field.status"};t("actual.translation");`,
  );
  assert.deepEqual(result.keys, [
    "field.label",
    "missing-value",
    "field.status",
    "actual.translation",
  ]);
});
