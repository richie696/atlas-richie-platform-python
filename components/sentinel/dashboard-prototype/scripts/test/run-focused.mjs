import { readdirSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectDirectory = fileURLToPath(new URL("../../", import.meta.url));
const [suite, pattern] = process.argv.slice(2);
const suiteDirectory = path.join(projectDirectory, "tests", suite);

if (!new Set(["logic", "http"]).has(suite) || !pattern) {
  console.error("Usage: node scripts/test/run-focused.mjs <logic|http> <test-name-regexp>");
  process.exit(2);
}

let namePattern;
try {
  namePattern = new RegExp(pattern);
} catch (error) {
  console.error(`Invalid test-name regular expression: ${error.message}`);
  process.exit(2);
}

const testFiles = readdirSync(suiteDirectory).filter((name) => name.endsWith(".test.mjs"));
const matchingFiles = testFiles.flatMap((name) => {
  const source = readFileSync(path.join(suiteDirectory, name), "utf8");
  const names = [...source.matchAll(/\btest\(\s*(["'`])([^\n]*?)\1\s*,/g)].map((match) => match[2]);
  const matches = names.filter((testName) => namePattern.test(testName));
  return matches.length === 0 ? [] : [{ name, tests: matches }];
});

if (matchingFiles.length === 0) {
  console.error(`No ${suite} test title matches ${JSON.stringify(pattern)}; no tests were run.`);
  process.exit(2);
}

const suiteEntryFile = suite === "logic" ? "suite.mjs" : "transport.test.mjs";
const suiteSource = readFileSync(path.join(suiteDirectory, suiteEntryFile), "utf8");
const unregisteredFiles = matchingFiles
  .map(({ name }) => name)
  .filter((name) => name !== suiteEntryFile && !suiteSource.includes(`./${name}`));
if (unregisteredFiles.length > 0) {
  console.error(
    `Focused ${suite} test file(s) are not registered in tests/${suite}/${suiteEntryFile}: ${unregisteredFiles.join(", ")}; no tests were run.`,
  );
  process.exit(2);
}

const result = spawnSync(
  process.execPath,
  ["--test", `--test-name-pattern=${pattern}`, `tests/${suite}/run.mjs`],
  { cwd: projectDirectory, stdio: "inherit" },
);

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
