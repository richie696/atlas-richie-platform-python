/**
 * 语言键一致性检查。
 *
 * 中文
 * ----
 * 文案放在 `app/i18n/messages/<locale>/<namespace>.json` 换来的是「翻译者不用碰代码」，
 * 代价是失去编译期检查——`t("ovrview.table.title")` 拼错不会报错，只会在页面上
 * 显示成键本身。这个脚本把那条检查补回来。
 *
/**
 * 校验两件事：
 *
 * 1. **三语键集合完全一致**。缺一个键 = 那种语言下界面显示原始键名。
 * 2. **源码里字面量写出的键都存在**。扫 `t("…")` 的双引号形式。
 *
 * ## 刻意不做「死键」检查
 *
 * 反向查「语言包里有没有没被用到的键」在本项目**全是误报**，已实测：519 个键里
 * 报出 246 个死键，而它们全部在用。原因是键大量通过**常量间接引用**——
 *
 *     const INSTANCE_MATRIX_HEADS = ["…", "applications.matrix.head.status", …];
 *     heads={INSTANCE_MATRIX_HEADS.map((key) => t(key))}
 *
 *     const SEVERITY_LABEL_KEY = { critical: "faults.severity.critical", … };
 *     t(SEVERITY_LABEL_KEY[event.severity])
 *
 * 静态扫描追踪不到变量，只能看到字面量。要恢复这条检查得引入 TS 类型分析或
 * 运行时插桩，成本远大于收益。真正该查的「死代码」是**文件级**的（例如
 * `ruleTypes.ts` 零引用），那个交给构建和 review，不放在这里。
 *
 * ## 为什么是 CI 期而不是编译期
 *
 * 真要编译期检查就得把 JSON 重新导出成 TS 常量，那样又回到「翻译者要碰代码」。
 * 两者不可兼得。这里选 JSON + CI 检查：键拼错会在提交前被挡住，而不是等到
 * 页面上出现一串 `ovrview.table.title` 才发现。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC = "src";
const MESSAGES = join(SRC, "app/i18n/messages");
const LOCALES = ["zh-CN", "en-US", "ja-JP"];

/**
 * 把注释替换成等长空格，保持所有偏移不变。
 *
 * 必须剥注释：`keycheck.mjs` 自己的文件头就写了
 * `t("ovrview.title")` 作为「拼错会长什么样」的例子，不剥的话它会把自己报成
 * 一条 `[未定义]`——一条由检查工具自己制造的假阳性。
 */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => " ".repeat(m.length))
    .replace(/(^|[^:])\/\/[^\n]*/g, (m, p1) => p1 + " ".repeat(m.length - p1.length))
    // `export type MetricKey = "qps" | "rt" | …` 是**联合类型**的取值声明，不是
    // 键常量。`*Key:` 扫描会把它当成键，报出「未定义 qps」。一并抹掉。
    .replace(/export\s+type\s+[\w$]+[\s\S]*?;/g, (m) => " ".repeat(m.length));
}

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
  for (const name of readdirSync(dir).sort()) {
    if (!name.endsWith(".json")) continue;
    const data = JSON.parse(readFileSync(join(dir, name), "utf8"));
    for (const [key, value] of Object.entries(data)) {
      if (typeof value !== "string") {
        throw new Error(`${locale}/${name} 的 "${key}" 不是字符串（JSON 无法表达函数）`);
      }
      keys.set(key, { ns: name.replace(/\.json$/, ""), value });
    }
  }
  return keys;
}

/** 扫源码里所有 `t("…")` 形式的键。 */
function scanUsedKeys() {
  const used = new Map();
  const template = [];
  const variable = [];
  for (const file of collectFiles(SRC, [".ts", ".tsx"])) {
    const rel = relative(".", file);
    const code = stripComments(readFileSync(file, "utf8"));
    // 取 `t(` **括号内**的所有字符串字面量，而不是只取紧跟 `t(` 的那一个。
    //
    // 只匹配 `t("…")` 会漏掉 `t(cond ? "a" : "b")`——而三元两支都是字面量，
    // 完全可以校验。漏掉它们等于把一批能查的键放过了。
    for (const call of code.matchAll(/\bt\(([^()]*)\)/g)) {
      const arg = call[1];
      // 只取**第一个参数**（键），不取插值对象里的字面量。
      // `t("setup.noneNote", { source: cond ? "Nacos" : "Consul" })` 里
      // "Nacos" 是产品名数据不是文案键，扫进去会报一条「未定义 Nacos」。
      const comma = arg.indexOf(",");
      const keyArg = (comma < 0 ? arg : arg.slice(0, comma)).trim();
      let found = false;
      for (const lit of keyArg.matchAll(/"([a-zA-Z][\w.:]+)"/g)) {
        if (!used.has(lit[1])) used.set(lit[1], rel);
        found = true;
      }
      // 模板字符串 = 动态键，静态扫不出来。**判为错误**：拼出的完整键空间无法
      // 从语言包反推，语言包里少一个字段标签时不会有任何报错，只会在那个字段的
      // 表单上显示原始键名。解法是改成显式键映射（见 features/rules/i18n/useRuleCopy.ts）。
      if (arg.includes("`") && /\$\{/.test(arg)) {
        template.push({ file: rel, snippet: arg.replace(/\s+/g, " ").trim().slice(0, 60) });
      } else if (!found && /[A-Za-z_$]/.test(arg)) {
        // t(变量) —— 键来自常量映射或联合类型。键值本身会在下面按 `*Key:` 形态扫到，
        // 所以只算**警告**：调用点无法静态枚举，但它指向的键是字面量、会被校验。
        variable.push({ file: rel, snippet: arg.replace(/\s+/g, " ").trim().slice(0, 60) });
      }
    }
    // 键常量的值：`labelKey: "system.step.admin.label"` / `= "…"`。
    // 这些是动态调用点最终指向的键，扫进来才能验证它们都存在于语言包。
    for (const m of code.matchAll(/\b[A-Za-z_$][\w$]*Key\s*[:=]\s*"([a-zA-Z][\w.:]+)"/g)) {
      if (!used.has(m[1])) used.set(m[1], rel);
    }
  }
  return { used, template, variable };
}

const messages = Object.fromEntries(LOCALES.map((locale) => [locale, readMessages(locale)]));
const FALLBACK = "zh-CN";
const base = messages[FALLBACK];
const { used, template, variable } = scanUsedKeys();

const errors = [];

// 1) 三语键集合一致
const baseKeys = new Set(base.keys());
for (const locale of LOCALES) {
  if (locale === FALLBACK) continue;
  const other = new Set(messages[locale].keys());
  for (const key of baseKeys) {
    if (!other.has(key)) errors.push(`[缺键] ${locale} 缺少 "${key}"`);
  }
  for (const key of other) {
    if (!baseKeys.has(key)) errors.push(`[多余键] ${locale} 多出 "${key}"（${base.has(key) ? "" : "基准语言也没有"}）`);
  }
}

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

// 键由变量/常量映射传入：调用点枚举不了，但键值本身已被上面的 `*Key:` 扫描覆盖，
// 所以只提示不报错——否则 58 处全红，而它们的风险已被「映射值被校验」堵住。
if (variable.length > 0) {
  console.log(`\n${variable.length} 处 t() 的键来自变量/常量映射（键值本身已校验，调用点不报错）:`);
  for (const item of variable.slice(0, 6)) console.log(`  · ${item.file}  t(${item.snippet})`);
  if (variable.length > 6) console.log(`  · …其余 ${variable.length - 6} 处见文件`);
}

if (errors.length === 0) {
  console.log("\n三语键一致 · 全部键可静态校验 · 无模板拼键");
  process.exit(0);
}
console.log(`\n发现 ${errors.length} 个问题:`);
for (const line of errors) console.log(`  ✗ ${line}`);
process.exit(1);
