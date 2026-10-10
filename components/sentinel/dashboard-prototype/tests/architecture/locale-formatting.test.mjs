import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { parseSync } from "@babel/core";
import { test } from "node:test";

const sourceRoot = path.resolve("src");

function sourceFiles(directory) {
  return readdirSync(directory).flatMap((entry) => {
    const file = path.join(directory, entry);
    return statSync(file).isDirectory() ? sourceFiles(file) : /\.tsx?$/.test(file) ? [file] : [];
  });
}

function isOptionalResolvedLanguage(expression) {
  return (
    expression?.type === "MemberExpression" &&
    expression.object?.type === "Identifier" &&
    expression.object.name === "i18n" &&
    expression.property?.type === "Identifier" &&
    expression.property.name === "resolvedLanguage"
  );
}

function findUnsafeIntlLocaleArguments(source) {
  const tree = parseSync(source, {
    babelrc: false,
    configFile: false,
    parserOpts: { plugins: ["typescript", "jsx"] },
  });
  const unsafe = [];
  function visit(node) {
    if (!node || typeof node !== "object") return;
    if (
      node.type === "NewExpression" &&
      node.callee?.type === "MemberExpression" &&
      node.callee.object?.type === "Identifier" &&
      node.callee.object.name === "Intl" &&
      ["NumberFormat", "DateTimeFormat"].includes(node.callee.property?.name) &&
      isOptionalResolvedLanguage(node.arguments?.[0])
    )
      unsafe.push(node.arguments[0]);
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(visit);
      else if (value && typeof value === "object") visit(value);
    }
  }
  visit(tree);
  return unsafe;
}

test("F5.2 Intl formatters never receive unresolved i18n.resolvedLanguage without fallback", () => {
  const violations = sourceFiles(sourceRoot).flatMap((file) => {
    const source = readFileSync(file, "utf8");
    return findUnsafeIntlLocaleArguments(source).map(
      (node) => `${path.relative(process.cwd(), file)}:${node.loc?.start.line ?? "?"}`,
    );
  });
  assert.deepEqual(violations, [], "use the active i18n language as the formatter fallback");
});
