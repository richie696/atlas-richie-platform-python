/** Locale parity/interpolation and AST-based translation-key checks. Dynamic calls are also constrained by the i18next TypeScript key contract. */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { collectExportedTranslationMaps, scanTranslationKeys } from "./source-keys.mjs";
import { assembleMessageCatalog, validateCatalogTranslations } from "../../src/app/i18n/catalog.ts";

const SRC = "src";
const MESSAGES = join(SRC, "app/i18n/messages");
const LOCALES = ["zh-CN", "en-US", "ja-JP"];

function collectFiles(dir, exts) {
  const out = [];
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...collectFiles(full, exts));
    else if (exts.some((ext) => entry.name.endsWith(ext))) out.push(full);
  }
  return out;
}

/** 读某个 locale 下的全部 namespace 文件。 */
function readMessages(locale) {
  const dir = join(MESSAGES, locale);
  const keys = new Map();
  const bundles = Object.fromEntries(
    readdirSync(dir)
      .filter((name) => name.endsWith(".json"))
      .map((name) => [
        name.replace(/\.json$/, ""),
        JSON.parse(readFileSync(join(dir, name), "utf8")),
      ]),
  );
  assembleMessageCatalog(locale, bundles);
  for (const name of readdirSync(dir).sort()) {
    if (!name.endsWith(".json")) continue;
    const data = JSON.parse(readFileSync(join(dir, name), "utf8"));
    for (const [key, value] of Object.entries(data)) {
      if (typeof value !== "string") {
        throw new Error(`${locale}/${name} 的 "${key}" 不是字符串（JSON 无法表达函数）`);
      }
      if (keys.has(key)) throw new Error(locale + "/" + name + " 重复定义国际化键 " + key);
      keys.set(key, { ns: name.replace(/\.json$/, ""), value });
    }
  }
  return keys;
}

function scanUsedKeys() {
  const files = collectFiles(SRC, [".ts", ".tsx"]);
  const sources = new Map(files.map((file) => [file, readFileSync(file, "utf8")]));
  const exportedMaps = new Map(
    [...sources].map(([file, source]) => [file, collectExportedTranslationMaps(source)]),
  );
  function resolveImportedKeys(fromFile, importSource, importedName, propertyName) {
    if (!importSource.startsWith(".")) return undefined;
    const base = join(dirname(fromFile), importSource);
    const target = [
      base,
      `${base}.ts`,
      `${base}.tsx`,
      join(base, "index.ts"),
      join(base, "index.tsx"),
    ].find((candidate) => sources.has(candidate));
    const entries = target ? exportedMaps.get(target)?.get(importedName) : undefined;
    if (!entries) return undefined;
    if (propertyName !== null && entries.has(propertyName)) return entries.get(propertyName);
    return entries.get("*") ?? [...entries.values()].flat();
  }
  const used = new Map(),
    template = [],
    variable = [];
  for (const [file, source] of sources) {
    const rel = relative(".", file),
      result = scanTranslationKeys(source, {
        resolveImportedKeys: (importSource, importedName, propertyName) =>
          resolveImportedKeys(file, importSource, importedName, propertyName),
      });
    for (const key of result.keys) if (!used.has(key)) used.set(key, rel);
    for (const snippet of result.templates) template.push({ file: rel, snippet });
    for (const snippet of result.variable) variable.push({ file: rel, snippet });
  }
  return { used, template, variable };
}

const messages = Object.fromEntries(LOCALES.map((locale) => [locale, readMessages(locale)]));
validateCatalogTranslations(
  Object.fromEntries(
    Object.entries(messages).map(([locale, keys]) => [
      locale,
      Object.fromEntries([...keys].map(([key, entry]) => [key, entry.value])),
    ]),
  ),
);
const FALLBACK = "zh-CN";
const base = messages[FALLBACK];
const { used, template, variable } = scanUsedKeys();

const errors = [];

// 2) 用到的键都存在
for (const [key, file] of used) {
  if (!base.has(key)) errors.push(`[未定义] ${file} 用了 "${key}"，但语言包里没有`);
}

const label = FALLBACK + " 为基准";
console.log(`消息总数: ${LOCALES.map((l) => `${l}=${messages[l].size}`).join(" ")} · ${label}`);
console.log(`静态可校验的键: ${used.size}`);

// 3) 模板拼键：键空间无法枚举，是真缺口。判为错误。
for (const item of template) {
  errors.push(`[动态拼键] ${item.file} 的 t(${item.snippet}) 拼出的键无法枚举，请改成显式键映射`);
}

// 未解析调用单独报告；部分映射的 *Key 值可提取，但不声称所有变量已静态穷尽。
if (variable.length > 0) {
  console.log(
    `\n${variable.length} 处 t() 调用无法由 AST 枚举；它们受 i18next JSON 派生的 TypeScript key 类型约束，` +
      "真实 producer 的三语行为仍需 runtime 测试覆盖:",
  );
  for (const item of variable) console.log(`  · ${item.file}  ${item.snippet}`);
}

if (errors.length === 0) {
  console.log("\n三语键/插值一致 · 已提取键校验通过 · 无模板拼键");
  process.exit(0);
}
console.log(`\n发现 ${errors.length} 个问题:`);
for (const line of errors) console.log(`  ✗ ${line}`);
process.exit(1);
