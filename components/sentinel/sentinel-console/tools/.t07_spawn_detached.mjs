import { openSync, closeSync } from "node:fs";
import { spawn } from "node:child_process";

const [cwd, logPath, separator, command, ...args] = process.argv.slice(2);
if (!cwd || !logPath || separator !== "--" || !command) {
  throw new Error("Usage: .t07_spawn_detached.mjs <cwd> <log-path> -- <command> [args...]");
}

const logFd = openSync(logPath, "a", 0o600);
const child = spawn(command, args, {
  cwd,
  env: process.env,
  detached: true,
  stdio: ["ignore", logFd, logFd],
});
try {
  await new Promise((resolve, reject) => {
    child.once("spawn", resolve);
    child.once("error", reject);
  });
} finally {
  closeSync(logFd);
}
child.unref();
console.log(child.pid);
