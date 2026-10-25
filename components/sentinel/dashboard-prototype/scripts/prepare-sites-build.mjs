#!/usr/bin/env node
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const buildRoot = path.resolve(process.env.SENTINEL_BUILD_OUTPUT_ROOT ?? path.join(root, "dist"));
const index = path.join(buildRoot, "client", "index.html");
const worker = path.join(root, "worker", "index.js");
const hosting = path.join(root, ".openai", "hosting.json");

for (const file of [index, worker, hosting]) {
  if (!existsSync(file)) throw new Error("Missing Sites build input: " + file);
}

mkdirSync(path.join(buildRoot, "server"), { recursive: true });
mkdirSync(path.join(buildRoot, ".openai"), { recursive: true });
copyFileSync(worker, path.join(buildRoot, "server", "index.js"));
copyFileSync(hosting, path.join(buildRoot, ".openai", "hosting.json"));

console.log(`Prepared Sites build under ${buildRoot}`);
