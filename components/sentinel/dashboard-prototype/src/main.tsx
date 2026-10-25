import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { AppProviders } from "./app/providers/AppProviders";
import "./core/styles/index.scss";
import { resolveConsoleRuntimeConfiguration } from "./core/api/runtime/consoleRuntimeConfiguration";
import { startConsoleInterception } from "./core/api/runtime/startConsoleInterception";
import { bootstrapConsoleApplication } from "./core/api/runtime/bootstrapConsoleApplication";
import { createConsoleServices } from "./app/providers/consoleServices";
import { i18nReady } from "./app/i18n/config";
import { loadAstryxLocaleCatalog } from "./app/i18n/astryxLocaleCatalogs";
import { readStoredLocale } from "./app/i18n/locales";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Dashboard root element is missing.");
}
const root = rootElement;

async function bootstrap(): Promise<void> {
  await i18nReady;
  await loadAstryxLocaleCatalog(readStoredLocale());
  const runtime = resolveConsoleRuntimeConfiguration(
    {
      mode: import.meta.env.VITE_CONSOLE_MODE,
      apiBaseUrl: import.meta.env.VITE_CONSOLE_API_BASE_URL,
    },
    window.location.origin,
    __SENTINEL_CONSOLE_BUILD_PROFILE__,
  );
  await bootstrapConsoleApplication(runtime, {
    startInterception: async (configuration) => {
      if (__SENTINEL_CONSOLE_BUILD_PROFILE__ !== "demo") return;
      if (configuration.mode === "mock") {
        const { APP_CONSOLE_MOCK_HANDLERS } = await import("./app/api/mockConsoleHandlers");
        await startConsoleInterception(configuration, APP_CONSOLE_MOCK_HANDLERS);
        return;
      }
      await startConsoleInterception(configuration);
    },
    createServices: createConsoleServices,
    mount: (services) => {
      window.addEventListener("pagehide", services.dispose, { once: true });
      createRoot(root).render(
        <React.StrictMode>
          <AppProviders runtime={runtime} services={services}>
            <App />
          </AppProviders>
        </React.StrictMode>,
      );
    },
  });
}

void bootstrap().catch(() => {
  const failure = document.createElement("p");
  failure.setAttribute("role", "alert");
  failure.textContent =
    "Sentinel Dashboard could not establish its configured Console request boundary. No API request was sent.";
  root.replaceChildren(failure);
});
