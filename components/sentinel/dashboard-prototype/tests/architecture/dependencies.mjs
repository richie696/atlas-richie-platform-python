import { parseSync } from "@babel/core";
import path from "node:path";

/** Parse static/type/dynamic imports, including multiline statements; no grep-based bypass. */
export function dependencySpecifiers(source) {
  const tree = parseSync(source, {
    babelrc: false,
    configFile: false,
    parserOpts: { plugins: ["typescript", "jsx"] },
  });
  const dependencies = new Set();
  function visit(node) {
    if (!node || typeof node !== "object") return;
    if (
      [
        "ImportDeclaration",
        "ExportNamedDeclaration",
        "ExportAllDeclaration",
        "ImportExpression",
      ].includes(node.type) &&
      node.source?.value
    )
      dependencies.add(node.source.value);
    if (node.type === "TSImportType" && node.source?.value) dependencies.add(node.source.value);
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(visit);
      else if (value && typeof value === "object") visit(value);
    }
  }
  visit(tree);
  return [...dependencies];
}

/** Resolve source-relative or root alias references; package imports stay external. */
export function resolveDependency(source, specifier) {
  if (specifier.startsWith("@/")) return specifier.slice(2);
  if (specifier.startsWith("."))
    return path.posix.normalize(path.posix.join(path.posix.dirname(source), specifier));
  return null;
}

/** Stable, testable dependency policy, separate from the temporary migration allowlist. */
export function classifyDependency(source, target) {
  const [layer, feature, role] = source.split("/");
  const [targetLayer, targetFeature, ...targetPrivate] = target
    .replace(/\.(tsx?|jsx?)$/, "")
    .split("/");
  if (layer === "core" && ["app", "shared", "features"].includes(targetLayer))
    return "core-reverse";
  if (layer === "shared" && ["app", "features"].includes(targetLayer)) return "shared-reverse";
  if (layer === "features" && targetLayer === "app") return "feature-app";
  if (layer === "app" && targetLayer === "features" && targetPrivate.length > 1)
    return "app-feature-private";
  if (
    layer === "features" &&
    role === "ui" &&
    targetLayer === "core" &&
    target.startsWith("core/api/transport/")
  )
    return "feature-ui-transport";
  if (
    layer === "features" &&
    targetLayer === "features" &&
    feature !== targetFeature &&
    targetPrivate.length > 0 &&
    targetPrivate.join("/") !== "index"
  )
    return "feature-private";
  if (
    layer === "features" &&
    role === "model" &&
    ((targetLayer === "features" &&
      ["ui", "state", "api", "i18n", "fixtures", "presentation", "editor", "forms"].includes(
        targetPrivate[0],
      )) ||
      target === "react" ||
      target.startsWith("react/") ||
      target.includes("/ui/"))
  )
    return targetLayer === "features" && ["editor", "forms"].includes(targetPrivate[0])
      ? "model-form"
      : "model-effect-or-ui";
  if (
    layer === "features" &&
    role === "presentation" &&
    targetLayer === "shared" &&
    target.startsWith("shared/ui/")
  )
    return "presentation-ui-token";
  if (
    layer === "features" &&
    role === "api" &&
    targetLayer === "features" &&
    feature === targetFeature &&
    ["editor", "forms"].includes(targetPrivate[0])
  )
    return "wire-form";
  return null;
}
