import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

const CONSOLE_BASE_PATH_PATTERN = /^\/(?:[A-Za-z0-9_-]+\/)*$/;

export function resolveConsoleBasePath(environment = process.env) {
  const basePath = environment.SENTINEL_CONSOLE_BASE_PATH ?? "/";
  if (
    !CONSOLE_BASE_PATH_PATTERN.test(basePath) ||
    basePath === "/api/" ||
    basePath.startsWith("/api/")
  ) {
    throw new Error("SENTINEL_CONSOLE_BASE_PATH must be / or a canonical path outside /api");
  }
  return basePath;
}

export default defineConfig(({ command, mode }) => {
  const demoProfile = command === "serve" || mode === "demo";
  const demoBuild = command === "build" && mode === "demo";

  return {
    base: resolveConsoleBasePath(),
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    define: {
      __SENTINEL_CONSOLE_BUILD_PROFILE__: JSON.stringify(demoProfile ? "demo" : "live-only"),
    },
    publicDir: demoProfile ? "public" : false,
    build: {
      outDir: demoBuild ? "dist/demo/client" : "dist/client",
      manifest: true,
      rollupOptions: {
        output: {
          manualChunks(id) {
            const normalizedId = id.replaceAll("\\", "/");
            if (!normalizedId.includes("/node_modules/")) return undefined;

            // Only globally required runtimes become shared chunks. Feature
            // packages (notably Astryx and Zod) stay on their route boundaries.
            if (/\/node_modules\/(react|react-dom|scheduler)\//.test(normalizedId)) {
              return "react-runtime";
            }
            if (
              /\/node_modules\/(i18next|react-i18next|intl-messageformat)\//.test(normalizedId) ||
              /\/node_modules\/@formatjs\//.test(normalizedId)
            ) {
              return "i18n-runtime";
            }
            return undefined;
          },
        },
      },
    },
    optimizeDeps: {
      // Lazy feature resources must not trigger dependency optimization/reload
      // halfway through a user interaction or a browser acceptance run.
      include: [
        "react",
        "react-dom/client",
        "@richie696/react-framework",
        "@richie696/react-framework-react",
        "@astryxdesign/core/hooks",
        "@astryxdesign/core/i18n",
        "@astryxdesign/core/Banner",
      ],
    },
    server: {
      host: "0.0.0.0",
      allowedHosts: ["terminal.local"],
      warmup: {
        clientFiles: ["./src/main.tsx"],
      },
    },
    plugins: [react()],
  };
});
