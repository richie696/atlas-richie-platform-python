/**
 * 界面文案 i18n 覆盖审计。
 *
 * 为什么需要这个工具
 * ------------------
 * 迁移规模曾经被数错过两次：
 *
 * 1. 只 grep **带引号的中文字符串字面量**，漏掉 JSX 裸文本（`<h3>观测事实</h3>`）
 *    和模板字符串（`` `${n} 个应用` ``）。overview 因此被报成 5 条，实际 18 条。
 * 2. 把 `i18n/locales.ts` 和 `fixtures/*.ts` 也算进去。前者中文本该存在，
 *    后者是**演示数据内容**（事件标题、观测事实），按 `core/i18n/types.ts` 的
 *    归属规则**有意不迁**。
 *
 * 两个错误方向相反，抵消之后总数看着"差不多"，于是没人发现。
 *
 * 本工具的口径
 * ------------
 * 分两级，因为两级的确定性不同：
 *
 * - **视图层**（各 feature 的 `ui` 目录，加上 `shared/ui` 与 `app`）里的中文
 *   **确定**是界面文案。排除项：注释行、行尾注释。
 * - **model / state 层**里的中文**需要人工判定**。判别联合的标签、表头、
 *   枚举的中文形态是界面文案；而自由叙述（事件标题、观测结论）是数据。
 *   两者在源码里长得一模一样，只能逐条看。
 *
 * 排除的目录：`fixtures/`（演示数据，按 `core/i18n/types.ts` 的归属规则有意不译）
 * 与 `i18n/`（语言包本身，中文本该在那里）。
 *
 * 排除的注释行：strip 后以 `*`、`//`、`/*`、`/**` 开头。行尾注释会被剥掉。
 *
 * 它是**线索生成器，不是判据**。真正的判据是 `test:i18n:probe`——切到 en-US 后
 * 扫运行时 DOM；静态扫描回答不了「界面上还有没有中文」。
 *
 * 用法：
 *   npm run i18n:audit            # 分级列出
 *   npm run i18n:audit -- --summary
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC = "src";
const CJK = /[\u4e00-\u9fff]/;
/**
 * 是否注释行。
 *
 * 逐个前缀匹配是错的两次：
 * 1. 只认星号、斜杠、星斜杠，会把 JSX 注释（行首是花括号）报成界面文案。
 * 2. 把花括号也当通用前缀，会把 `{cond ? "甲" : "乙"}` 这种**表达式**当成注释——
 *    rules 从 15 处掉到 3 处、identity 从 66 掉到 62，两处都是被误杀的文案。
 *
 * 所以花括号必须与星号**紧邻**才算 JSX 注释。
 *
 * 注意：本文件（以及任何 `.mjs`）的块注释里**不能**出现闭合注释的字符序列，
 * 即使它被反引号包着。JS 解析器不管它出现在什么位置，会就地结束块注释。
 */
function isComment(trimmed) {
  return (
    trimmed.startsWith("*") ||
    trimmed.startsWith("//") ||
    trimmed.startsWith("/*")
  );
  // 注意：JSX 块注释（`{/*`）**故意不在这里处理**——它需要跨行状态，
  // 而 `isComment` 是单行判断。先在这里返回的话，状态机永远设不上，
  // 多行注释的中间行就会被当成界面文案报出来。
}

const featureDirs = readdirSync(join(SRC, "features"))
  .filter((name) => statSync(join(SRC, "features", name)).isDirectory())
  .map((name) => join(SRC, "features", name));

/** 视图层：中文一定是界面文案。 */
const VIEW_ROOTS = [
  join(SRC, "app"),
  join(SRC, "shared", "ui"),
  ...featureDirs.map((dir) => join(dir, "ui")),
];

/** 视图层之下的读模型与状态：中文可能是枚举标签（要迁），也可能是数据（不迁）。 */
const MODEL_LAYERS = ["model", "state"];

function collectFiles(dir) {
  const out = [];
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...collectFiles(full));
    else if (/\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

/** 去掉行尾注释，避免 `const a = 1; // 说明` 里的中文被当成界面文案。 */
function stripTrailingComment(line) {
  // 不处理字符串内的 `//`（如 "https://…"）：只砍掉引号外的注释。
  let inQuote = null;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (inQuote) {
      if (ch === "\\") i += 1;
      else if (ch === inQuote) inQuote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") {
      inQuote = ch;
      continue;
    }
    if (ch === "/" && line[i + 1] === "/") return line.slice(0, i);
  }
  return line;
}

/** 收集一个目录下的 CJK 命中，按「视图层 / 读模型层」两级归类。 */
function scan(roots, layer) {
  for (const root of roots) {
    for (const file of collectFiles(root)) {
      const rel = relative(SRC, file).replaceAll("\\", "/");
      const feature = rel.startsWith("app/")
        ? "app"
        : rel.startsWith("shared/")
          ? "shared"
          : rel.split("/")[1];
      const hits = [];
      // 每个文件重置：JSX 块注释不跨文件。
      let inJsxBlock = false;
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((raw, index) => {
          if (inJsxBlock) {
            if (raw.includes("*/")) inJsxBlock = false;
            return;
          }
          const trimmed = raw.trim();
          if (isComment(trimmed) || isLocaleDisplayName(trimmed)) return;
          // JSX 注释可以**出现在行中间**（`...</h1> {/* 说明 */}`）且跨多行。
          // 只判行首会漏掉起始标记；只判单行会把延续行报成界面文案。
          // 因此切掉注释部分，注释**之前**的代码仍要检查。
          let code = raw;
          const start = raw.indexOf("{/*");
          if (start >= 0) {
            if (!raw.includes("*/", start)) inJsxBlock = true;
            code = raw.slice(0, start);
          }
          if (CJK.test(stripTrailingComment(code))) {
            hits.push({ line: index + 1, text: trimmed });
          }
        });
      if (!hits.length) continue;
      if (!byFeature.has(feature)) {
        byFeature.set(feature, { view: { hits: 0, lines: [] }, model: { hits: 0, lines: [] } });
      }
      const bucket = byFeature.get(feature)[layer];
      bucket.hits += hits.length;
      for (const hit of hits) bucket.lines.push(`  ${rel}:${hit.line}  ${hit.text}`);
    }
  }
}

/**
 * 语言下拉的显示名**故意不翻译**：用户按母语认它（"简体中文"/"English"/"日本語"）。
 * 它们不是可翻译文案，留在源码里，审计不该把它们当成遗漏。
 */
function isLocaleDisplayName(trimmed) {
  return trimmed === '{ code: "zh-CN", label: "简体中文" },'
    || trimmed === '{ code: "en-US", label: "English" },'
    || trimmed === '{ code: "ja-JP", label: "日本語" },';
}

const byFeature = new Map();
scan(VIEW_ROOTS, "view");
scan(featureDirs.flatMap((dir) => MODEL_LAYERS.map((l) => join(dir, l))), "model");

const order = [...byFeature.keys()].sort((a, b) => {
  const x = byFeature.get(a);
  const y = byFeature.get(b);
  return y.view.hits + y.model.hits - (x.view.hits + x.model.hits);
});
const totalView = order.reduce((s, k) => s + byFeature.get(k).view.hits, 0);
const totalModel = order.reduce((s, k) => s + byFeature.get(k).model.hits, 0);

if (process.argv.includes("--summary")) {
  console.log(
    `${"feature".padEnd(14)}${"视图层".padStart(7)}${"读模型层".padStart(10)}   说明`,
  );
  console.log("─".repeat(56));
  for (const key of order) {
    const { view, model } = byFeature.get(key);
    console.log(
      `${key.padEnd(14)}${String(view.hits).padStart(7)}${String(model.hits).padStart(10)}` +
        (view.hits || model.hits ? "" : "   （已清零）"),
    );
  }
  console.log("─".repeat(56));
  console.log(
    `${"合计".padEnd(14)}${String(totalView).padStart(7)}${String(totalModel).padStart(10)}` +
      `   共 ${totalView + totalModel} 处`,
  );
  console.log("\n视图层 = 一定是界面文案；读模型层 = 需人工判定（枚举标签要迁，自由叙述是数据）");
  process.exit(totalView + totalModel === 0 ? 0 : 1);
}

for (const key of order) {
  const { view, model } = byFeature.get(key);
  if (view.hits === 0 && model.hits === 0) continue;
  console.log(`\n━━ ${key} ━━ 视图层 ${view.hits} · 读模型层 ${model.hits}`);
  if (view.hits) {
    console.log("  [视图层 · 一定迁]");
    for (const line of view.lines) console.log(line);
  }
  if (model.hits) {
    console.log("  [读模型层 · 逐条判定：枚举标签要迁，自由叙述是数据不迁]");
    for (const line of model.lines) console.log(line);
  }
}
console.log(
  `\n合计 ${totalView + totalModel} 处（视图层 ${totalView} + 读模型层 ${totalModel}）`,
);
console.log("fixtures/ 与 i18n/ 不计入：前者是演示数据，后者是文案包本身。");

