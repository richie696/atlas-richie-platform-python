import { spawn } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";

const consoleRoot = fileURLToPath(new URL("../../../sentinel-console", import.meta.url));
const pythonServer = fileURLToPath(
  new URL("../../../sentinel-console/tests/support/live_rule_catalog_server.py", import.meta.url),
);

/** Start the synthetic Python Console on an OS-assigned loopback port. */
export async function startLiveRuleCatalogConsole() {
  const child = spawn(
    process.env.SENTINEL_UV ?? "uv",
    [
      "run",
      "--project",
      consoleRoot,
      "--extra",
      "test",
      "--extra",
      "server",
      "python",
      pythonServer,
      "--port",
      "0",
    ],
    { cwd: consoleRoot, stdio: ["ignore", "pipe", "pipe"] },
  );
  let output = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => (output += chunk));
  child.stderr.on("data", (chunk) => (output += chunk));
  const port = await new Promise((resolve, reject) => {
    const deadline = setTimeout(
      () => reject(new Error(`Console startup timeout:\n${output}`)),
      60_000,
    );
    const check = () => {
      for (const line of output.split(/\r?\n/)) {
        try {
          const message = JSON.parse(line);
          if (message.ready === true && Number.isInteger(message.port)) {
            clearTimeout(deadline);
            resolve(message.port);
            return;
          }
        } catch {
          // uv and Uvicorn can emit diagnostics before the JSON readiness record.
        }
      }
      if (child.exitCode !== null) {
        clearTimeout(deadline);
        reject(new Error(`Console exited before startup (${child.exitCode}):\n${output}`));
      }
    };
    child.stdout.on("data", check);
    child.stderr.on("data", check);
    child.once("error", (error) => {
      clearTimeout(deadline);
      reject(error);
    });
    child.once("exit", check);
    check();
  });
  return { child, port, output: () => output };
}

/** Stop only a child returned by startLiveRuleCatalogConsole. */
export async function stopLiveRuleCatalogConsole(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  let timer;
  await Promise.race([
    once(child, "exit"),
    new Promise((resolve) => (timer = setTimeout(resolve, 5_000))),
  ]);
  clearTimeout(timer);
  if (child.exitCode === null && child.signalCode === null) {
    child.kill("SIGKILL");
    await once(child, "exit");
  }
}
