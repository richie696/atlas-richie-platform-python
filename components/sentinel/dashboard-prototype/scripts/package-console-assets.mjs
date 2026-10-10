import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const prototypeRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const clientRoot = path.join(prototypeRoot, "dist", "client");
const packageRoot = path.resolve(prototypeRoot, "..", "sentinel-console");
const webRoot = path.join(packageRoot, "src", "atlas_richie", "sentinel_console", "web");
const markerPath = path.join(webRoot, ".dashboard-assets.json");
const indexPath = path.join(clientRoot, "index.html");
const manifestPath = path.join(clientRoot, ".vite", "manifest.json");

if (!existsSync(indexPath) || !existsSync(manifestPath)) {
  throw new Error("Production client build is incomplete; run npm run build first");
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const runtimeFiles = ["index.html"];
for (const item of Object.values(manifest)) {
  if (!item || typeof item.file !== "string") {
    throw new Error("Production manifest contains an invalid entry");
  }
  runtimeFiles.push(item.file, ...(item.css ?? []), ...(item.assets ?? []));
}

const uniqueFiles = [...new Set(runtimeFiles)].sort();
for (const file of uniqueFiles) {
  if (
    !file ||
    file.includes("\\") ||
    file.includes("\0") ||
    file.startsWith("/") ||
    file.split("/").some((segment) => segment === ".." || segment === "." || !segment)
  ) {
    throw new Error(`Unsafe production asset path: ${file}`);
  }
  const source = path.resolve(clientRoot, file);
  if (!source.startsWith(`${clientRoot}${path.sep}`) || !statSync(source).isFile()) {
    throw new Error(`Production asset is missing or outside the client build: ${file}`);
  }
  if (file === "mockServiceWorker.js") {
    throw new Error("The live Console package must not contain the Demo service worker");
  }
}

if (existsSync(webRoot)) {
  if (!existsSync(markerPath)) {
    throw new Error("Refusing to replace an unmarked Console web asset directory");
  }
  rmSync(webRoot, { recursive: true, force: true });
}
mkdirSync(webRoot, { recursive: true });

for (const file of uniqueFiles) {
  const destination = path.join(webRoot, file);
  mkdirSync(path.dirname(destination), { recursive: true });
  copyFileSync(path.join(clientRoot, file), destination);
}

const packagedFiles = uniqueFiles.map((file) => {
  const bytes = readFileSync(path.join(webRoot, file));
  return {
    path: file,
    bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
  };
});
writeFileSync(
  markerPath,
  `${JSON.stringify({ schemaVersion: 1, files: packagedFiles }, null, 2)}\n`,
);

console.log(
  `Packaged ${packagedFiles.length} production web files (${packagedFiles.reduce((sum, file) => sum + file.bytes, 0)} bytes) into sentinel-console`,
);
