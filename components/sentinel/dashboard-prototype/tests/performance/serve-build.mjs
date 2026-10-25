import { createServer } from "node:http";
import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 5201;
const PROBE_PATH = "/__performance-probe";
const BUILD_DIRECTORY = "dist/demo/client";
const CONTENT_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".webmanifest", "application/manifest+json"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
]);

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const configuredBuild = process.env.SENTINEL_PERF_BUILD_DIR ?? BUILD_DIRECTORY;
const buildRoot = await realpath(path.resolve(projectRoot, configuredBuild));
const probeFile = path.join(path.dirname(fileURLToPath(import.meta.url)), "performance-probe.html");
const host = process.env.SENTINEL_PERF_HOST ?? DEFAULT_HOST;
const port = Number(process.env.SENTINEL_PERF_PORT ?? DEFAULT_PORT);

if (!Number.isInteger(port) || port < 1 || port > 65_535) {
  throw new Error("SENTINEL_PERF_PORT must be a valid TCP port");
}

function responseHeaders(contentType, cacheControl) {
  return {
    "Cache-Control": cacheControl,
    "Content-Type": contentType,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
  };
}

function isWithinBuild(pathname) {
  return pathname === buildRoot || pathname.startsWith(`${buildRoot}${path.sep}`);
}

async function sendFile(response, filePath, requestMethod, cacheControl) {
  const details = await stat(filePath);
  if (!details.isFile()) return false;
  const contentType = CONTENT_TYPES.get(path.extname(filePath)) ?? "application/octet-stream";
  response.writeHead(200, responseHeaders(contentType, cacheControl));
  if (requestMethod === "HEAD") {
    response.end();
  } else {
    response.end(await readFile(filePath));
  }
  return true;
}

const server = createServer(async (request, response) => {
  const method = request.method ?? "GET";
  if (method !== "GET" && method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" });
    response.end();
    return;
  }

  let pathname;
  try {
    pathname = decodeURIComponent(new URL(request.url ?? "/", `http://${host}`).pathname);
  } catch {
    response.writeHead(400);
    response.end();
    return;
  }

  try {
    if (pathname === PROBE_PATH) {
      await sendFile(response, probeFile, method, "no-store");
      return;
    }

    const requestedPath = pathname === "/" ? "/index.html" : pathname;
    if (requestedPath.includes("\\")) {
      response.writeHead(400);
      response.end();
      return;
    }

    let filePath = path.resolve(buildRoot, `.${requestedPath}`);
    if (!isWithinBuild(filePath)) {
      response.writeHead(404);
      response.end();
      return;
    }

    try {
      filePath = await realpath(filePath);
    } catch {
      if (path.extname(requestedPath)) {
        response.writeHead(404);
        response.end();
        return;
      }
      filePath = path.join(buildRoot, "index.html");
    }

    if (!isWithinBuild(filePath)) {
      response.writeHead(404);
      response.end();
      return;
    }

    const hashedAsset = requestedPath.startsWith("/assets/");
    const cacheControl = hashedAsset ? "public, max-age=31536000, immutable" : "no-store";
    if (!(await sendFile(response, filePath, method, cacheControl))) {
      response.writeHead(404);
      response.end();
    }
  } catch {
    if (!response.headersSent) response.writeHead(500);
    response.end();
  }
});

server.listen(port, host, () => {
  console.log(`Serving ${buildRoot} at http://${host}:${port}`);
  console.log(`Performance probe: http://${host}:${port}${PROBE_PATH}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => server.close(() => process.exit(0)));
}
