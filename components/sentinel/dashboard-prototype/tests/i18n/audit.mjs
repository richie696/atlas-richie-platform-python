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
 * 只统计**渲染层**（各 feature 的 `ui` 目录、`shared/ui/`、`app/`）里含 CJK 的
 * 非注释行。
 * fixtures / model / i18n 全部排除：前者是数据，后两者不是界面文案。
 *
 * 排除的注释行：strip 后以 `*`、`//`、`/*`、`/**` 开头。行尾注释不做处理——
 * 一行里既有代码又有中文时（例如 `const label = "详情"; // 详情`），本工具
 * 保守地报出来，由人判断。
 *
 * 它是**线索生成器，不是判据**。真正的判据是 `test:e2e` 里切 en-US/ja-JP
 * 后扫 DOM —— 静态扫描回答不了「界面上还有没有中文」。
 *
 * 用法：
 *   node tests/i18n/audit.mjs           # 按 feature 分组列出
 *   node tests/i18n/audit.mjs --summary  # 只出行数汇总
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC = "src";
const CJK = /[\u4e00-\u9fff]/;
const COMMENT_PREFIX = ["*", "//", "/*"];

/** 需要审计的目录：只覆盖渲染层。 */
const RENDER_ROOTS = [
  join(SRC, "app"),
  join(SRC, "shared", "ui"),
  ...readdirSync(join(SRC, "features"))
    .filter((name) => statSync(join(SRC, "features", name)).isDirectory())
    .map((name) => join(SRC, "features", name, "ui")),
];

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

const byFeature = new Map();
for (const root of RENDER_ROOTS) {
  for (const file of collectFiles(root)) {
    const rel = relative(SRC, file).replaceAll("\\", "/");
    const feature = rel.startsWith("app/") ? "app" : rel.startsWith("shared/") ? "shared" : rel.split("/")[1];
    const hits = [];
    readFileSync(file, "utf8")
      .split("\n")
      .forEach((raw, index) => {
        const trimmed = raw.trim();
        if (COMMENT_PREFIX.some((p) => trimmed.startsWith(p))) return;
        const line = stripTrailingComment(raw);
        if (CJK.test(line)) hits.push({ line: index + 1, text: trimmed });
      });
    if (hits.length) {
      if (!byFeature.has(feature)) byFeature.set(feature, { files: 0, hits: 0, lines: [] });
      const bucket = byFeature.get(feature);
      bucket.files += 1;
      bucket.hits += hits.length;
      for (const hit of hits) bucket.lines.push(`  ${rel}:${hit.line}  ${hit.text}`);
    }
  }
}

const order = [...byFeature.keys()].sort((a, b) => byFeature.get(b).hits - byFeature.get(a).hits);
const total = order.reduce((sum, key) => sum + byFeature.get(key).hits, 0);

if (process.argv.includes("--summary")) {
  for (const key of order) {
    const { files, hits } = byFeature.get(key);
    console.log(`${key.padEnd(14)}${String(hits).padStart(4)} 处 / ${files} 文件`);
  }
  console.log("─".repeat(34));
  console.log(`${"合计".padEnd(14)}${String(total).padStart(4)} 处`);
  process.exit(total === 0 ? 0 : 1);
}

for (const key of order) {
  const { files, lines } = byFeature.get(key);
  console.log(`\n── ${key} ── ${lines.length} 处 / ${files} 文件`);
  for (const line of lines) console.log(line);
}
console.log(`\n合计 ${total} 处待迁（仅渲染层；fixtures / model / i18n 不计入）`);
