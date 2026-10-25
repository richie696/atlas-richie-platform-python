import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { shouldKeepEdge } from "./edge-lifecycle.mjs";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const e2eDirectory = path.join(projectRoot, "tests/e2e");
const defaultEdge = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge";

function signalIsolatedBrowser(browser, signal) {
  try {
    process.kill(-browser.pid, signal);
  } catch (error) {
    if (error?.code === "ESRCH") return;
    // macOS can deny signaling a detached browser process group even though
    // this runner owns the Edge child. Fall back to the exact child PID; never
    // search for or signal unrelated browser processes.
    if (error?.code === "EPERM") {
      browser.kill(signal);
      return;
    }
    throw error;
  }
}

function edgeExecutable() {
  const executable = process.env.EDGE_BIN ?? defaultEdge;
  if (!existsSync(executable)) {
    throw new Error(`Microsoft Edge executable not found: ${executable}; set EDGE_BIN to its executable path`);
  }
  return executable;
}

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: "inherit", ...options });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (signal) reject(new Error(`${path.basename(command)} exited from ${signal}`));
      else resolve(code ?? 1);
    });
  });
}

async function waitForDevTools(profile, child, timeoutMs = 20000) {
  const activePortFile = path.join(profile, "DevToolsActivePort");
  const deadline = Date.now() + timeoutMs;
  let diagnostics = "";
  child.stderr.on("data", chunk => { diagnostics = (diagnostics + chunk).slice(-4000); });
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error(`Microsoft Edge exited before DevTools was ready. ${diagnostics}`);
    }
    if (existsSync(activePortFile)) {
      const [port] = readFileSync(activePortFile, "utf8").trim().split(/\r?\n/);
      if (/^\d+$/.test(port ?? "")) {
        const endpoint = `http://127.0.0.1:${port}`;
        try {
          const response = await fetch(`${endpoint}/json/version`, { signal: AbortSignal.timeout(1000) });
          if (response.ok && typeof (await response.json()).webSocketDebuggerUrl === "string") {
            return endpoint;
          }
        } catch {
          // Edge writes DevToolsActivePort before its discovery endpoint accepts requests.
        }
      }
    }
    await delay(100);
  }
  throw new Error(`Timed out waiting for Edge DevTools. ${diagnostics}`);
}

async function main() {
  const executable = edgeExecutable();
  const headless = process.env.SENTINEL_E2E_HEADLESS === "1";
  const keepEdge = shouldKeepEdge({
    requested: process.env.SENTINEL_E2E_KEEP_EDGE === "1",
    headless,
  });
  const profile = mkdtempSync(path.join(tmpdir(), "sentinel-e2e-edge-"));
  const configuredBaseUrl = process.env.BASE_URL ?? "http://localhost:53240";
  const baseUrl = new URL(configuredBaseUrl).origin;
  const startUrl = process.env.SENTINEL_E2E_START_URL ?? `${baseUrl}/#/login?app=all&range=1h`;
  const browser = spawn(executable, [
    ...(headless ? ["--headless=new"] : []),
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--remote-debugging-port=0",
    "--remote-allow-origins=*",
    `--user-data-dir=${profile}`,
    startUrl,
  // Isolate the browser process tree even in headless mode. Killing only the
  // main Edge process leaves renderer/network helpers alive on macOS.
  ], { detached: true, stdio: ["ignore", "ignore", "pipe"] });

  let endpoint;
  try {
    endpoint = await waitForDevTools(profile, browser);
  } catch (error) {
    if (browser.exitCode === null && browser.signalCode === null) {
      signalIsolatedBrowser(browser, "SIGTERM");
      signalIsolatedBrowser(browser, "SIGKILL");
    }
    rmSync(profile, { recursive: true, force: true });
    throw error;
  }

  const specs = (await import("node:fs/promises")).readdir(e2eDirectory)
    .then(names => names.filter(name => name.endsWith(".e2e.test.mjs")).sort())
    .then(names => names.map(name => path.join(e2eDirectory, name)));
  const allFiles = await specs;
  const requestedFile = process.env.SENTINEL_E2E_TEST_FILE;
  const requestedFiles = process.env.SENTINEL_E2E_TEST_FILES
    ?.split(",")
    .map(value => value.trim())
    .filter(Boolean);
  const selectedNames = requestedFiles ?? (requestedFile ? [requestedFile] : null);
  const files = selectedNames
    ? allFiles.filter(file => selectedNames.includes(path.basename(file)))
    : allFiles;
  if (files.length === 0) {
    throw new Error(`No E2E spec matched: ${selectedNames?.join(", ") ?? "(all specs)"}`);
  }
  if (selectedNames && files.length !== selectedNames.length) {
    const matchedNames = new Set(files.map(file => path.basename(file)));
    const missingNames = selectedNames.filter(name => !matchedNames.has(name));
    throw new Error(`Unknown E2E spec(s): ${missingNames.join(", ")}`);
  }
  for (const file of [...files, path.join(e2eDirectory, "cdp.mjs")]) {
    const checkCode = await run(process.execPath, ["--check", file]);
    if (checkCode !== 0) throw new Error(`Syntax check failed: ${file}`);
  }

  browser.unref();
  console.log(`Edge DevTools: ${endpoint}`);
  console.log(`Edge profile: ${profile}`);
  console.log(`Dashboard URL: ${startUrl}`);
  if (headless) console.log("Edge mode: headless (does not take over a visible browser window)");
  if (selectedNames) console.log(`Focused E2E specs: ${selectedNames.join(", ")}`);
  const requestedTestName = process.env.SENTINEL_E2E_TEST_NAME;
  if (requestedTestName) console.log(`Focused E2E test name pattern: ${requestedTestName}`);
  console.log(keepEdge
    ? "The visible isolated Edge window/profile will remain open for review."
    : "The isolated Edge process/profile will close after the test run.");
  const testArgs = ["--test", "--test-concurrency=1"];
  if (requestedTestName) testArgs.push("--test-name-pattern", requestedTestName);
  const testTimeoutMs = process.env.SENTINEL_E2E_TEST_TIMEOUT_MS;
  if (testTimeoutMs !== undefined) {
    if (!/^\d+$/.test(testTimeoutMs) || Number(testTimeoutMs) < 1) {
      throw new Error("SENTINEL_E2E_TEST_TIMEOUT_MS must be a positive integer");
    }
    testArgs.push("--test-timeout", testTimeoutMs);
  }
  try {
    const code = await run(process.execPath, [...testArgs, ...files], {
      cwd: projectRoot,
      env: { ...process.env, SENTINEL_E2E_CDP_URL: endpoint },
    });
    process.exitCode = code;
  } finally {
    if (keepEdge) {
      browser.stderr?.destroy();
      browser.unref();
    } else {
      const exited = new Promise(resolve => browser.once("exit", resolve));
      signalIsolatedBrowser(browser, "SIGTERM");
      if (browser.exitCode === null && browser.signalCode === null)
        await Promise.race([exited, delay(3000)]);
      // Helpers can outlive their parent after SIGTERM. Escalate against the
      // isolated group, then remove only this runner's disposable profile.
      signalIsolatedBrowser(browser, "SIGKILL");
      rmSync(profile, { recursive: true, force: true });
    }
  }
}

main().catch(error => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
