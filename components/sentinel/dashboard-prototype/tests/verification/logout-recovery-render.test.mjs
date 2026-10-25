import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createInstance } from "i18next";
import { createServer } from "vite";
import { test } from "node:test";

test("failed logout renders the explicit session-inspection recovery action", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    define: { __SENTINEL_CONSOLE_BUILD_PROFILE__: JSON.stringify("live-only") },
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  let workflow;
  try {
    const [
      { App },
      { ConsoleRuntimeProvider },
      { AuthenticationProvider },
      { HashNavigationContext },
      { createAuthenticationWorkflow },
      { IDENTITY_ROLE },
      { SESSION_CAPABILITY },
      { createElement },
      { renderToStaticMarkup },
      { I18nextProvider },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/app/App.tsx"),
      vite.ssrLoadModule("/src/core/api/runtime/ConsoleRuntimeProvider.tsx"),
      vite.ssrLoadModule("/src/features/identity/state/AuthenticationProvider.tsx"),
      vite.ssrLoadModule("/src/app/router/HashNavigationContext.tsx"),
      vite.ssrLoadModule("/src/features/identity/application/authenticationWorkflow.ts"),
      vite.ssrLoadModule("/src/features/identity/model/account.ts"),
      vite.ssrLoadModule("/src/core/session/capabilities.ts"),
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const locale = "en-US";
    const shell = JSON.parse(
      await readFile(
        new URL(`../../src/app/i18n/messages/${locale}/shell.json`, import.meta.url),
        "utf8",
      ),
    );
    const i18n = createInstance();
    await i18n.init({
      lng: locale,
      fallbackLng: false,
      nsSeparator: false,
      resources: { [locale]: { translation: shell } },
    });

    workflow = createAuthenticationWorkflow({
      readBootstrap: async () => ({ initialized: true }),
      readSession: async () => ({
        accountId: "operator-1",
        username: "operator",
        roleId: IDENTITY_ROLE.Admin,
        capabilities: [SESSION_CAPABILITY.MetricsView, SESSION_CAPABILITY.RulesWrite],
        sessionEpoch: "session-1",
      }),
      login: async () => {
        throw new Error("not used by this render contract");
      },
      logout: async () => {
        throw new AppError(AppErrorKind.SERVER, "outcome cannot be confirmed", { status: 503 });
      },
    });
    await workflow.restore();
    await assert.rejects(workflow.logout());

    const navigation = {
      getSnapshot: () => ({
        location: { hash: "#/accounts?app=all&range=1h", index: 0 },
        prompt: null,
        restoring: false,
      }),
      subscribe: () => () => {},
      request: () => {},
    };
    const markup = renderToStaticMarkup(
      createElement(
        I18nextProvider,
        { i18n },
        createElement(
          ConsoleRuntimeProvider,
          { configuration: { mode: "live", apiBaseUrl: "https://console.test" } },
          createElement(
            HashNavigationContext.Provider,
            { value: navigation },
            createElement(
              AuthenticationProvider,
              { workflow },
              createElement(App),
            ),
          ),
        ),
      ),
    );

    assert.ok(markup.includes(i18n.t("shell.session.logoutUnknownTitle")));
    assert.ok(markup.includes(i18n.t("shell.session.logoutUnknown")));
    assert.ok(markup.includes(i18n.t("shell.session.inspect")));
    assert.doesNotMatch(markup, /Signing out|shell\.route\.loading/);
  } finally {
    workflow?.dispose();
    await vite.close();
  }
});
