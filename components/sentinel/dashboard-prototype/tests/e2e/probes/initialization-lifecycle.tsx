import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { i18nReady } from "../../../src/app/i18n/config";
import { loadAstryxLocaleCatalog } from "../../../src/app/i18n/astryxLocaleCatalogs";
import { InitializationProbe } from "./InitializationProbe";

const root = document.getElementById("root");
if (!root) throw new Error("Initialization lifecycle probe requires #root");
window.addEventListener("error", (event) => {
  root.textContent = `Probe load failed: ${event.message}`;
});
window.addEventListener("unhandledrejection", (event) => {
  root.textContent = `Probe load failed: ${String(event.reason)}`;
});

void Promise.all([i18nReady, loadAstryxLocaleCatalog("zh-CN")])
  .then(() => {
    createRoot(root).render(
      <StrictMode>
        <InitializationProbe />
      </StrictMode>,
    );
  })
  .catch((error: unknown) => {
    root.textContent = `Probe load failed: ${String(error)}`;
  });
