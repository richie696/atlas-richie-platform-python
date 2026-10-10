import { parseSync, traverse } from "@babel/core";
export { interpolationNames } from "../../src/app/i18n/catalog.ts";

/** Explicit presentation hints only. A *Key suffix alone also includes business/form/session identities. */
const TRANSLATION_KEY_NAMES = new Set([
  "i18nKey",
  "translationKey",
  "labelKey",
  "descriptionKey",
  "titleKey",
  "nameKey",
  "messageKey",
  "captionKey",
  "feedbackKey",
  "errorKey",
  "detailKey",
  "roleKey",
  "statusLabelKey",
  "valueKey",
]);

/** Inspect key-producing branches, never conditions/options/comments/types as translation keys. */
export function scanTranslationKeys(source, { resolveImportedKeys = () => undefined } = {}) {
  const tree = parseSync(source, {
    babelrc: false,
    configFile: false,
    parserOpts: { plugins: ["typescript", "jsx"] },
  });
  const keys = new Set(),
    templates = [],
    variable = [];
  function visit(node) {
    if (!node || typeof node !== "object") return;
    if (
      node.type === "ObjectProperty" &&
      node.key.type === "Identifier" &&
      TRANSLATION_KEY_NAMES.has(node.key.name) &&
      node.value.type === "StringLiteral"
    )
      keys.add(node.value.value);
    if (
      node.type === "VariableDeclarator" &&
      node.id.type === "Identifier" &&
      TRANSLATION_KEY_NAMES.has(node.id.name) &&
      node.init?.type === "StringLiteral"
    )
      keys.add(node.init.value);
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach(visit);
      else if (value && typeof value === "object") visit(value);
    }
  }
  visit(tree);

  /** Resolve only finite, source-local key expressions; never infer a key from a comparison value. */
  function addImportedKeys(binding, propertyName) {
    const specifier = binding.path;
    if (!specifier.isImportSpecifier()) return false;
    const declaration = specifier.findParent((parent) => parent.isImportDeclaration());
    if (!declaration) return false;
    const importedName = specifier.node.imported.name ?? specifier.node.imported.value;
    const values = resolveImportedKeys(declaration.node.source.value, importedName, propertyName);
    if (!values?.length) return false;
    values.forEach((key) => keys.add(key));
    return true;
  }

  /** Locate the finite iterable that supplies a map callback or for-of binding. */
  function iterationSource(binding) {
    const callback = binding.path.getFunctionParent?.();
    const mapCall = callback?.parentPath;
    if (
      callback &&
      mapCall?.isCallExpression() &&
      mapCall.get("callee").isMemberExpression() &&
      mapCall.get("callee.property").isIdentifier({ name: "map" }) &&
      mapCall.get("arguments.0").node === callback.node
    )
      return mapCall.get("callee.object");
    if (binding.path.isVariableDeclarator()) {
      const declaration = binding.path.parentPath;
      const loop = declaration?.parentPath;
      if (loop?.isForOfStatement() && loop.get("left").node === declaration.node)
        return loop.get("right");
    }
    return null;
  }

  /** Resolve a destructured translation field from every row of a finite map input. */
  function destructuredMapProperty(binding, visitedBindings) {
    if (!binding.path.isObjectPattern()) return false;
    const callback = binding.path.getFunctionParent?.();
    const mapCall = callback?.parentPath;
    if (
      !callback ||
      !mapCall?.isCallExpression() ||
      !mapCall.get("callee").isMemberExpression() ||
      !mapCall.get("callee.property").isIdentifier({ name: "map" }) ||
      mapCall.get("arguments.0").node !== callback.node
    )
      return false;
    const property = binding.path.get("properties").find((candidate) => {
      if (!candidate.isObjectProperty() || !candidate.get("value").isIdentifier()) return false;
      return candidate.get("value").node.name === binding.identifier.name;
    });
    if (!property || property.node.computed) return false;
    const fieldName = property.get("key").isIdentifier()
      ? property.get("key").node.name
      : property.get("key").isStringLiteral()
        ? property.get("key").node.value
        : null;
    return (
      fieldName !== null &&
      collectMappedValues(mapCall.get("callee.object"), fieldName, visitedBindings)
    );
  }

  function collect(path, visitedBindings = new Set()) {
    const expression = path?.node;
    if (!expression) return false;
    if (expression.type === "StringLiteral") {
      keys.add(expression.value);
      return true;
    }
    if (expression.type === "ConditionalExpression")
      return (
        collect(path.get("consequent"), visitedBindings) &&
        collect(path.get("alternate"), visitedBindings)
      );
    if (expression.type === "LogicalExpression")
      return (
        collect(path.get("left"), visitedBindings) && collect(path.get("right"), visitedBindings)
      );
    if (expression.type === "ArrayExpression")
      return path.get("elements").every((element) => collect(element, visitedBindings));
    if (
      [
        "TSAsExpression",
        "TSSatisfiesExpression",
        "TSNonNullExpression",
        "ParenthesizedExpression",
      ].includes(expression.type)
    )
      return collect(path.get("expression"), visitedBindings);
    if (expression.type === "TemplateLiteral") {
      if (expression.expressions.length) {
        templates.push(source.slice(expression.start, expression.end));
        return false;
      }
      keys.add(expression.quasis.map((part) => part.value.cooked).join(""));
      return true;
    }
    if (expression.type === "Identifier") {
      const binding = path.scope.getBinding(expression.name);
      if (!binding || visitedBindings.has(binding)) return false;
      visitedBindings.add(binding);
      if (binding.path.isVariableDeclarator() && binding.path.get("init").node)
        return collect(binding.path.get("init"), visitedBindings);
      if (destructuredMapProperty(binding, visitedBindings)) return true;
      const source = iterationSource(binding);
      if (source) return collect(source, visitedBindings);
      if (binding.path.isVariableDeclarator()) return false;
      return addImportedKeys(binding);
    }
    if (
      expression.type === "CallExpression" &&
      expression.callee.type === "MemberExpression" &&
      expression.callee.object.type === "Identifier" &&
      expression.callee.object.name === "Object" &&
      expression.callee.property.type === "Identifier" &&
      expression.callee.property.name === "freeze"
    )
      return collect(path.get("arguments.0"), visitedBindings);
    if (expression.type === "MemberExpression") {
      const objectPath = path.get("object");
      let binding = objectPath.isIdentifier()
        ? objectPath.scope.getBinding(objectPath.node.name)
        : null;
      if (!binding) return false;
      const selected = expression.computed
        ? expression.property.type === "StringLiteral"
          ? expression.property.value
          : null
        : expression.property.name;
      if (binding.path.isImportSpecifier()) {
        return addImportedKeys(binding, selected);
      }
      if (visitedBindings.has(binding)) return false;
      if (!binding.path.isVariableDeclarator()) {
        const collection = iterationSource(binding);
        if (!collection) return false;
        if (collection.isIdentifier()) {
          const collectionBinding = collection.scope.getBinding(collection.node.name);
          if (!collectionBinding) return false;
          if (collectionBinding.path.isImportSpecifier()) {
            const imported = collectionBinding.path;
            const declaration = imported.findParent((parent) => parent.isImportDeclaration());
            if (!declaration) return false;
            const importedName = imported.node.imported.name ?? imported.node.imported.value;
            const importedKeys = resolveImportedKeys(
              declaration.node.source.value,
              importedName,
              selected,
            );
            if (!importedKeys?.length) return false;
            importedKeys.forEach((key) => keys.add(key));
            return true;
          }
          if (!collectionBinding.path.isVariableDeclarator()) return false;
          return collectMappedValues(collectionBinding.path.get("init"), selected, visitedBindings);
        }
        return collectMappedValues(collection, selected, visitedBindings);
      }
      let initializer = binding.path.isVariableDeclarator() ? binding.path.get("init") : null;
      visitedBindings.add(binding);
      while (initializer?.isIdentifier()) {
        binding = initializer.scope.getBinding(initializer.node.name);
        if (!binding || visitedBindings.has(binding) || !binding.path.isVariableDeclarator())
          return false;
        visitedBindings.add(binding);
        initializer = binding.path.get("init");
      }
      while (
        initializer?.isTSAsExpression() ||
        initializer?.isTSSatisfiesExpression() ||
        initializer?.isTSNonNullExpression() ||
        initializer?.isParenthesizedExpression()
      )
        initializer = initializer.get("expression");
      if (
        initializer?.isCallExpression() &&
        initializer.get("callee").isMemberExpression() &&
        initializer.get("callee.object").isIdentifier({ name: "Object" }) &&
        initializer.get("callee.property").isIdentifier({ name: "freeze" })
      )
        initializer = initializer.get("arguments.0");
      while (
        initializer?.isTSAsExpression() ||
        initializer?.isTSSatisfiesExpression() ||
        initializer?.isTSNonNullExpression() ||
        initializer?.isParenthesizedExpression()
      )
        initializer = initializer.get("expression");
      if (initializer?.isMemberExpression() && initializer.get("object").isIdentifier()) {
        const mapBinding = initializer
          .get("object")
          .scope.getBinding(initializer.get("object").node.name);
        if (!mapBinding || visitedBindings.has(mapBinding)) return false;
        if (mapBinding.path.isImportSpecifier()) return addImportedKeys(mapBinding, selected);
        if (!mapBinding.path.isVariableDeclarator()) return false;
        visitedBindings.add(mapBinding);
        let mapInitializer = mapBinding.path.get("init");
        while (
          mapInitializer?.isTSAsExpression() ||
          mapInitializer?.isTSSatisfiesExpression() ||
          mapInitializer?.isTSNonNullExpression() ||
          mapInitializer?.isParenthesizedExpression()
        )
          mapInitializer = mapInitializer.get("expression");
        if (
          mapInitializer?.isCallExpression() &&
          mapInitializer.get("callee").isMemberExpression() &&
          mapInitializer.get("callee.object").isIdentifier({ name: "Object" }) &&
          mapInitializer.get("callee.property").isIdentifier({ name: "freeze" })
        )
          mapInitializer = mapInitializer.get("arguments.0");
        if (!mapInitializer?.isObjectExpression()) return false;
        const rows = mapInitializer.get("properties").filter((row) => row.isObjectProperty());
        return (
          rows.length > 0 &&
          rows.every((row) => collectMappedValues(row.get("value"), selected, visitedBindings))
        );
      }
      if (!initializer?.isObjectExpression()) return false;
      const properties = initializer.get("properties").filter((property) => {
        if (!property.isObjectProperty()) return false;
        if (selected === null) return true;
        if (property.node.computed) return false;
        const name =
          property.node.key.type === "Identifier"
            ? property.node.key.name
            : property.node.key.value;
        return selected === null || name === selected;
      });
      return (
        properties.length > 0 &&
        properties.every((property) => collect(property.get("value"), visitedBindings))
      );
    }
    return false;
  }

  /** Resolve only literal translation values on every row of a finite map input. */
  function collectMappedValues(path, propertyName, visitedBindings) {
    const node = path?.node;
    if (!node) return false;
    if (node.type === "Identifier") {
      const binding = path.scope.getBinding(node.name);
      if (!binding || visitedBindings.has(binding)) return false;
      if (binding.path.isImportSpecifier()) return addImportedKeys(binding, propertyName);
      if (!binding.path.isVariableDeclarator() || !binding.path.get("init").node) return false;
      visitedBindings.add(binding);
      return collectMappedValues(binding.path.get("init"), propertyName, visitedBindings);
    }
    if (
      [
        "TSAsExpression",
        "TSSatisfiesExpression",
        "TSNonNullExpression",
        "ParenthesizedExpression",
      ].includes(node.type)
    )
      return collectMappedValues(path.get("expression"), propertyName, visitedBindings);
    if (
      node.type === "CallExpression" &&
      path.get("callee").isMemberExpression() &&
      path.get("callee.object").isIdentifier({ name: "Object" }) &&
      path.get("callee.property").isIdentifier({ name: "freeze" })
    )
      return collectMappedValues(path.get("arguments.0"), propertyName, visitedBindings);
    if (node.type === "ArrayExpression") {
      const elements = path.get("elements").filter((element) => element.node);
      return (
        elements.length > 0 &&
        elements.every((element) =>
          propertyName === null
            ? collect(element, visitedBindings)
            : collectMappedValues(element, propertyName, visitedBindings),
        )
      );
    }
    if (propertyName === null) return collect(path, visitedBindings);
    if (node.type !== "ObjectExpression") return false;
    const properties = path.get("properties");
    const selectedProperties = properties.filter((property) => {
      if (!property.isObjectProperty() || property.node.computed) return false;
      const name =
        property.node.key.type === "Identifier"
          ? property.node.key.name
          : String(property.node.key.value);
      return name === propertyName;
    });
    return (
      selectedProperties.length === 1 &&
      selectedProperties.every((property) => collect(property.get("value"), visitedBindings))
    );
  }
  traverse(tree, {
    CallExpression(path) {
      if (!path.get("callee").isIdentifier({ name: "t" })) return;
      if (!collect(path.get("arguments.0")))
        variable.push(source.slice(path.node.start, path.node.end));
    },
  });
  return { keys: [...keys], templates, variable };
}

/** Collect exported, finite presentation-key maps for imports in the source audit. */
export function collectExportedTranslationMaps(source) {
  const tree = parseSync(source, {
    babelrc: false,
    configFile: false,
    parserOpts: { plugins: ["typescript", "jsx"] },
  });
  const maps = new Map();
  const unwrap = (node) => {
    let current = node;
    while (true) {
      if (
        [
          "TSAsExpression",
          "TSSatisfiesExpression",
          "TSNonNullExpression",
          "ParenthesizedExpression",
        ].includes(current?.type)
      ) {
        current = current.expression;
        continue;
      }
      if (
        current?.type === "CallExpression" &&
        current.callee.type === "MemberExpression" &&
        current.callee.object.type === "Identifier" &&
        current.callee.object.name === "Object" &&
        current.callee.property.type === "Identifier" &&
        current.callee.property.name === "freeze"
      ) {
        current = current.arguments[0];
        continue;
      }
      break;
    }
    return current;
  };
  for (const statement of tree.program.body) {
    const declaration = statement.type === "ExportNamedDeclaration" ? statement.declaration : null;
    if (declaration?.type !== "VariableDeclaration") continue;
    for (const item of declaration.declarations) {
      if (item.id.type !== "Identifier") continue;
      const initializer = unwrap(item.init);
      if (initializer?.type === "StringLiteral" && initializer.value.includes(".")) {
        if (/(KEY|LABEL|COPY|I18N|MESSAGE)/i.test(item.id.name))
          maps.set(item.id.name, new Map([["*", [initializer.value]]]));
        continue;
      }
      const entries = new Map();
      if (
        initializer?.type === "ArrayExpression" &&
        /(KEY|LABEL|COPY|I18N|MESSAGE|HEADER)/i.test(item.id.name)
      ) {
        const values = initializer.elements
          .filter((element) => element?.type === "StringLiteral" && element.value.includes("."))
          .map((element) => element.value);
        if (values.length) entries.set("*", values);
      }
      const candidates =
        initializer?.type === "ArrayExpression"
          ? initializer.elements.filter(Boolean)
          : initializer?.type === "ObjectExpression"
            ? [initializer]
            : [];
      for (const candidate of candidates) {
        if (candidate.type !== "ObjectExpression") continue;
        for (const property of candidate.properties) {
          if (property.type !== "ObjectProperty" || property.value.type !== "StringLiteral")
            continue;
          const fieldName = property.computed
            ? property.key.type === "StringLiteral"
              ? property.key.value
              : null
            : property.key.type === "Identifier"
              ? property.key.name
              : String(property.key.value);
          const isTranslationField = fieldName !== null && TRANSLATION_KEY_NAMES.has(fieldName);
          const isNamedMap = /(KEY|LABEL|COPY|I18N|MESSAGE)/i.test(item.id.name);
          if (
            initializer?.type === "ArrayExpression"
              ? !isTranslationField
              : !isNamedMap && !isTranslationField
          )
            continue;
          const value = property.value.value;
          if (!value.includes(".")) continue;
          const name = isTranslationField ? fieldName : (fieldName ?? "*");
          const values = entries.get(name) ?? [];
          values.push(value);
          entries.set(name, values);
        }
      }
      if (entries.size) maps.set(item.id.name, entries);
    }
  }
  return maps;
}
