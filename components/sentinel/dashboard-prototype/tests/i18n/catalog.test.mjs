import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createInstance } from "i18next";
import { createServer } from "vite";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import {
  MESSAGE_OWNERS,
  assembleMessageCatalog,
  validateCatalogTranslations,
} from "../../src/app/i18n/catalog.ts";
import { interpolationNames } from "./source-keys.mjs";

const locales = ["zh-CN", "en-US", "ja-JP"];
const files = Object.fromEntries(
  locales.map((locale) => [
    locale,
    Object.fromEntries(
      readdirSync(`src/app/i18n/messages/${locale}`)
        .filter((name) => name.endsWith(".json"))
        .map((name) => [
          name.slice(0, -5),
          JSON.parse(readFileSync(`src/app/i18n/messages/${locale}/${name}`, "utf8")),
        ]),
    ),
  ]),
);
const catalogs = Object.fromEntries(
  locales.map((locale) => [locale, assembleMessageCatalog(locale, files[locale])]),
);

test("I18N-OWNER: all actual files have explicit owners; assembly is immutable and does not mutate JSON resources", () => {
  const before = JSON.stringify(files);
  validateCatalogTranslations(catalogs);
  for (const locale of locales) {
    assert.deepEqual(Object.keys(files[locale]).sort(), Object.keys(MESSAGE_OWNERS).sort());
    assert.equal(Object.isFrozen(catalogs[locale]), true);
  }
  assert.equal(JSON.stringify(files), before);
});
test("I18N-OWNER: missing/extra files, foreign keys, empty text and non-string messages are rejected", () => {
  for (const change of [
    (bundle) => {
      delete bundle.shell;
    },
    (bundle) => {
      bundle.extra = {};
    },
    (bundle) => {
      bundle.shell["rules.foreign"] = "foreign";
    },
    (bundle) => {
      bundle.shell["shell.invalid"] = " ";
    },
    (bundle) => {
      bundle.shell["shell.invalid"] = {};
    },
  ]) {
    const candidate = structuredClone(files["zh-CN"]);
    change(candidate);
    assert.throws(() => assembleMessageCatalog("zh-CN", candidate));
  }
});
test("I18N-PARITY: locale/key/placeholder differences and a missing plural branch fail closed", () => {
  for (const change of [
    (all) => {
      delete all["ja-JP"];
    },
    (all) => {
      delete all["ja-JP"]["shell.navigationGuard.stay"];
    },
    (all) => {
      all["ja-JP"]["rules.workspace.sourceRead"] = "{{foreign}}";
    },
    (all) => {
      for (const locale of locales) delete all[locale]["rules.workspace.sourceRead_one"];
    },
  ]) {
    const candidate = structuredClone(catalogs);
    change(candidate);
    assert.throws(() => validateCatalogTranslations(candidate));
  }
});
test("I18N-PLURAL: the actual i18next instance renders zero/one/many in all three locales, never unresolved keys or placeholders", async () => {
  const i18n = createInstance();
  await i18n.init({
    resources: Object.fromEntries(
      locales.map((locale) => [locale, { translation: catalogs[locale] }]),
    ),
    supportedLngs: locales,
    fallbackLng: "zh-CN",
    nsSeparator: false,
    interpolation: { escapeValue: false },
  });
  const keys = Object.keys(catalogs["en-US"]).filter(
    (key) => !/_(one|other)$/.test(key) && catalogs["en-US"][key].includes("{{count}}"),
  );
  assert.equal(keys.length, 7);
  for (const locale of locales)
    for (const key of keys)
      for (const count of [0, 1, 2]) {
        const message = i18n.t(key, { lng: locale, count, filter: "FILTER" });
        assert.notEqual(message, key);
        assert.ok(message.includes(String(count)));
        assert.ok(!message.includes("{{"));
        assert.equal(
          message,
          catalogs[locale][key + "_" + (locale === "en-US" && count === 1 ? "one" : "other")]
            .replaceAll("{{count}}", String(count))
            .replaceAll("{{filter}}", "FILTER"),
        );
      }
  assert.equal(i18n.t("rules.workspace.sourceRead", { lng: "en-US", count: 1 }), "Read 1 rule");
  assert.equal(i18n.t("rules.workspace.sourceRead", { lng: "en-US", count: 2 }), "Read 2 rules");
});

test("I18N-CATALOG-RENDER: every catalog entry resolves in every locale with its declared interpolation inputs", async () => {
  const i18n = createInstance();
  await i18n.init({
    resources: Object.fromEntries(
      locales.map((locale) => [locale, { translation: catalogs[locale] }]),
    ),
    supportedLngs: locales,
    fallbackLng: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
  });
  const keys = Object.keys(catalogs["zh-CN"]).filter((key) => !/_one$|_other$/.test(key));
  for (const locale of locales)
    for (const key of keys) {
      const source = catalogs[locale][key];
      for (const count of interpolationNames(source).includes("count") ? [0, 1, 2] : [2]) {
        const values = Object.fromEntries(
          interpolationNames(source).map((name) => [name, name === "count" ? count : "TEST"]),
        );
        const rendered = i18n.t(key, { lng: locale, ...values });
        assert.notEqual(rendered, key, `${locale} must resolve ${key}`);
        assert.ok(!rendered.includes("{{"), `${locale}/${key} left an interpolation unresolved`);
        assert.ok(rendered.length > 0, `${locale}/${key} rendered empty text`);
      }
    }
});

test("I18N-DYNAMIC-IDENTITY: actual account, password, setup, role and source producers render in all locales", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const account = await vite.ssrLoadModule("/src/features/identity/model/account.ts");
    const password = await vite.ssrLoadModule("/src/features/identity/model/passwordPolicy.ts");
    const setup = await vite.ssrLoadModule("/src/features/identity/model/setup.ts");
    const rolePresentation = await vite.ssrLoadModule(
      "/src/features/identity/presentation/rolePresentation.ts",
    );
    const source = await vite.ssrLoadModule("/src/shared/model/configurationSource.ts");
    const setupPresentation = await vite.ssrLoadModule(
      "/src/features/identity/presentation/setupPresentation.ts",
    );
    const readySetup = {
      ...setup.INITIAL_SETUP_DRAFT,
      databasePort: "5432",
      database: {
        host: "db.internal",
        name: "sentinel",
        username: "operator",
        password: "synthetic",
      },
      admin: {
        username: "admin",
        password: "synthetic-admin-password",
        confirm: "synthetic-admin-password",
      },
      source: { address: "https://nacos.internal", namespace: "public" },
    };
    const invalidSetupSource = (sourceKind, authenticationMode, credentials) => ({
      ...readySetup,
      sourceKind,
      sourceAuthenticationMode: authenticationMode,
      sourceCredentials: { ...setup.INITIAL_SETUP_DRAFT.sourceCredentials, ...credentials },
    });
    const issues = [
      ...account.validateAccountDraft({ username: "", password: "", roleId: "view" }),
      ...account.validateAccountDraft({ username: "operator", password: "short", roleId: "view" }),
      ...account.validateAccountDraft({
        username: "operator",
        password: "synthetic-password",
        roleId: "invalid",
      }),
      ...account.validateLoginCredentials({ username: "", password: "" }),
      ...password.validatePasswordChange(password.EMPTY_PASSWORD_CHANGE),
      ...password.validatePasswordChange({
        current: "current",
        next: "x".repeat(password.PASSWORD_MIN_LENGTH - 1),
        confirm: "x".repeat(password.PASSWORD_MIN_LENGTH - 1),
      }),
      ...password.validatePasswordChange({
        current: "current",
        next: "x".repeat(password.PASSWORD_MAX_LENGTH + 1),
        confirm: "x".repeat(password.PASSWORD_MAX_LENGTH + 1),
      }),
      ...password.validatePasswordChange({
        current: "current",
        next: "synthetic-password",
        confirm: "different-password",
      }),
      ...setup.validateSetupStep(setup.SETUP_STEP.Storage, setup.INITIAL_SETUP_DRAFT),
      ...setup.validateSetupStep(setup.SETUP_STEP.Storage, { ...readySetup, databasePort: "0" }),
      ...setup.validateSetupStep(setup.SETUP_STEP.Sources, {
        ...readySetup,
        source: { ...readySetup.source, address: "invalid" },
      }),
      ...setup.validateSetupStep(setup.SETUP_STEP.Admin, {
        ...readySetup,
        admin: { username: "", password: "", confirm: "" },
      }),
      ...setup.validateSetupStep(setup.SETUP_STEP.Admin, {
        ...readySetup,
        admin: { ...readySetup.admin, confirm: "different-password" },
      }),
      ...setup.validateSetupStep(
        setup.SETUP_STEP.Sources,
        invalidSetupSource(
          source.RULE_SOURCE.Nacos,
          source.RULE_SOURCE_AUTHENTICATION.CredentialReference,
          { reference: "" },
        ),
      ),
      ...setup.validateSetupStep(
        setup.SETUP_STEP.Sources,
        invalidSetupSource(source.RULE_SOURCE.Nacos, source.RULE_SOURCE_AUTHENTICATION.Direct, {
          username: "",
          password: "",
        }),
      ),
      ...setup.validateSetupStep(
        setup.SETUP_STEP.Sources,
        invalidSetupSource(source.RULE_SOURCE.Consul, source.RULE_SOURCE_AUTHENTICATION.Direct, {
          consulToken: "",
        }),
      ),
    ];
    const keys = [
      ...issues.map(({ key }) => key),
      ...rolePresentation.ROLE_OPTIONS.flatMap(({ labelKey, descriptionKey }) => [
        labelKey,
        descriptionKey,
      ]),
      ...[
        { status: "disabled", builtIn: false, lastActiveAdmin: false },
        { status: "active", builtIn: true, lastActiveAdmin: false },
        { status: "active", builtIn: false, lastActiveAdmin: true },
      ]
        .map(rolePresentation.roleEditRestrictionCopy)
        .filter(Boolean),
      ...[
        { status: "empty" },
        { status: "denied" },
        { status: "error" },
        { status: "stale" },
        { status: "partial" },
        { status: "loading" },
        { status: "ready" },
      ].map(rolePresentation.roleTargetFallbackCopy),
      ...setupPresentation.SETUP_DATABASE_OPTIONS.map(({ descriptionKey }) => descriptionKey),
      ...setupPresentation.INITIALIZATION_STEPS.flatMap(({ labelKey, descriptionKey }) => [
        labelKey,
        descriptionKey,
      ]),
      ...setupPresentation.RULE_SOURCE_OPTIONS.map(({ descriptionKey }) => descriptionKey),
      ...setupPresentation.RULE_SOURCE_AUTHENTICATION_OPTIONS.flatMap(
        ({ labelKey, descriptionKey }) => [labelKey, descriptionKey],
      ),
    ];
    assert.deepEqual(
      new Set(issues.map(({ key }) => key)),
      new Set([
        "account.credentialsRequired",
        "account.passwordTooShort",
        "account.invalidRole",
        "account.loginRequired",
        "password.currentRequired",
        "password.tooShort",
        "password.tooLong",
        "password.mismatch",
        "setup.required",
        "setup.databasePortInvalid",
        "setup.sourceAddressInvalid",
        "setup.adminRequired",
        "setup.adminPasswordMismatch",
        "setup.credentialReferenceRequired",
        "setup.consulTokenRequired",
      ]),
    );
    const i18n = createInstance();
    await i18n.init({
      resources: Object.fromEntries(
        locales.map((locale) => [locale, { translation: catalogs[locale] }]),
      ),
      supportedLngs: locales,
      fallbackLng: false,
      nsSeparator: false,
      interpolation: { escapeValue: false },
    });
    for (const locale of locales)
      for (const { key, params } of issues) {
        const rendered = i18n.t(key, { lng: locale, ...params });
        assert.notEqual(rendered, key, `${locale} must translate actual producer output ${key}`);
        assert.ok(!rendered.includes("{{"), `${locale}/${key} left an interpolation unresolved`);
      }
    for (const locale of locales)
      for (const key of new Set(keys)) {
        const rendered = i18n.t(key, { lng: locale });
        assert.notEqual(
          rendered,
          key,
          `${locale} must translate actual option producer output ${key}`,
        );
      }
  } finally {
    await vite.close();
  }
});

test("I18N-ACCOUNT-STATUS-RESTRICTION: account rows explain protected disable actions in every locale", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { accountStatusRestrictionCopy } = await vite.ssrLoadModule(
      "/src/features/identity/presentation/accountStatusPresentation.ts",
    );
    const { AccountDirectory } = await vite.ssrLoadModule(
      "/src/features/identity/ui/components/AccountDirectory.tsx",
    );
    assert.equal(
      accountStatusRestrictionCopy({
        id: "built-in-admin",
        username: "admin",
        roleId: "admin",
        status: "active",
        builtIn: true,
        lastActiveAdmin: false,
      }),
      "management.builtIn",
    );
    assert.equal(
      accountStatusRestrictionCopy({
        id: "last-admin",
        username: "operator",
        roleId: "admin",
        status: "active",
        builtIn: false,
        lastActiveAdmin: true,
      }),
      "management.lastAdmin",
    );
    const [{ createElement }, { renderToStaticMarkup }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const page = {
      items: [
        {
          id: "built-in-admin",
          username: "admin",
          roleId: "admin",
          status: "active",
          builtIn: true,
          lastActiveAdmin: false,
          lastLoginAt: null,
          revision: "1",
        },
        {
          id: "last-admin",
          username: "operator",
          roleId: "admin",
          status: "active",
          builtIn: false,
          lastActiveAdmin: true,
          lastLoginAt: null,
          revision: "2",
        },
        {
          id: "ordinary-viewer",
          username: "viewer",
          roleId: "view",
          status: "active",
          builtIn: false,
          lastActiveAdmin: false,
          lastLoginAt: null,
          revision: "3",
        },
      ],
      page: 1,
      pageSize: 20,
      total: 3,
    };

    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      });
      const markup = renderToStaticMarkup(
        createElement(
          I18nextProvider,
          { i18n },
          createElement(AccountDirectory, {
            page,
            locked: false,
            onBindRole() {},
            onStatus() {},
            onPage() {},
          }),
        ),
      );
      assert.ok(markup.includes(i18n.t("management.builtIn")), `${locale} built-in reason`);
      assert.ok(markup.includes(i18n.t("management.lastAdmin")), `${locale} last-admin reason`);
      assert.equal(markup.includes("management.builtIn"), false);
      assert.equal(markup.includes("management.lastAdmin"), false);
      assert.equal(markup.includes("viewer"), true);
    }
  } finally {
    await vite.close();
  }
});

test("I18N-DYNAMIC-SETUP-FEEDBACK: initialization rejection reasons render distinct recovery text in all locales", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { initializationFeedbackKey } = await vite.ssrLoadModule(
      "/src/features/identity/presentation/setupFeedback.ts",
    );
    const { InitializationFeedback } = await vite.ssrLoadModule(
      "/src/features/identity/ui/setup/InitializationFeedback.tsx",
    );
    const [{ createElement }, { renderToStaticMarkup }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const rejected = ["validation", "setup-closed", "dependency"].map((reason) => ({
      status: "rejected",
      requestKey: "synthetic-request",
      reason,
    }));
    const keys = rejected.map(initializationFeedbackKey);
    assert.equal(new Set(keys).size, rejected.length, "each server reason needs distinct UI copy");

    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      });
      const messages = keys.map((key) => i18n.t(key));
      assert.equal(new Set(messages).size, rejected.length, `${locale} copy must stay distinct`);
      for (let index = 0; index < keys.length; index++) {
        assert.notEqual(messages[index], keys[index], `${locale} must translate ${keys[index]}`);
        assert.ok(messages[index].length > 0);
        assert.ok(!messages[index].includes("{{"));
      }
      for (let index = 0; index < rejected.length; index++) {
        const markup = renderToStaticMarkup(
          createElement(
            I18nextProvider,
            { i18n },
            createElement(InitializationFeedback, {
              snapshot: {
                bootstrap: {
                  status: "ready",
                  data: { initialized: false, setupAvailable: true },
                },
                databaseCheck: { status: "idle" },
                sourceCheck: { status: "idle" },
                initialization: rejected[index],
              },
              onInspect() {},
              onRestore() {},
            }),
          ),
        );
        assert.ok(
          markup.includes(messages[index]),
          `${locale} must render the matching recovery copy`,
        );
        assert.ok(!markup.includes("synthetic-request"), "request identifiers are not user copy");
        assert.ok(!markup.includes("SYNTHETIC-SECRET"), "credentials must not appear in feedback");
      }
    }
  } finally {
    await vite.close();
  }
});

test("F4.20-SETUP-CHECK-RENDER: connection-check buttons are single-flight while their fields remain rendered", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { SetupWizard } = await vite.ssrLoadModule("/src/features/identity/ui/SetupWizard.tsx");
    const [{ createElement }, { renderToStaticMarkup }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const draft = {
      databaseKind: "postgresql",
      databasePort: "5432",
      database: {
        host: "db.synthetic.internal",
        name: "control",
        username: "operator",
        password: "",
      },
      sourceKind: "nacos",
      source: { address: "http://nacos.synthetic.internal", namespace: "public" },
      sourceAuthenticationMode: "credential-reference",
      sourceCredentials: {
        reference: "synthetic-ref",
        username: "",
        password: "",
        consulToken: "",
      },
      admin: { username: "admin", password: "", confirm: "" },
    };
    const fields = [
      {
        step: "storage",
        index: 0,
        checkingProp: "isDatabaseChecking",
        labelKey: "setup.action.testConnection",
        inputValue: "db.synthetic.internal",
      },
      {
        step: "sources",
        index: 2,
        checkingProp: "isSourceChecking",
        labelKey: "setup.action.testSource",
        inputValue: "http://nacos.synthetic.internal",
      },
    ];
    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      });
      for (const field of fields) {
        const flow = {
          steps: ["storage", "admin", "sources", "complete"],
          stepIndex: field.index,
          step: field.step,
          isFirstStep: field.index === 0,
          isLastStep: false,
          draft,
          fieldIssues: [],
          notice: null,
          selectDatabase() {},
          setDatabasePort() {},
          patchDatabase() {},
          selectRuleSource() {},
          patchRuleSource() {},
          selectAuthenticationMode() {},
          patchSourceCredentials() {},
          patchAdmin() {},
          goNext() {},
          goBack() {},
          reportInfo() {},
          reportIssues() {},
          prepareSubmission() {
            return null;
          },
          clearSensitive() {},
        };
        for (const checking of [false, true]) {
          const markup = renderToStaticMarkup(
            createElement(
              I18nextProvider,
              { i18n },
              createElement(SetupWizard, {
                flow,
                onFinish() {},
                onTestDatabase() {},
                onTestSource() {},
                isDatabaseChecking: field.checkingProp === "isDatabaseChecking" && checking,
                isSourceChecking: field.checkingProp === "isSourceChecking" && checking,
              }),
            ),
          );
          const label = i18n.t(field.labelKey);
          const button = markup
            .match(/<button\b[^>]*>[\s\S]*?<\/button>/g)
            ?.find((item) => item.includes(label));
          assert.ok(button, `${locale}/${field.step} must render its connection-check action`);
          assert.equal(/\sdisabled(?:="")?(?:\s|>)/.test(button), checking);
          const input = markup
            .match(/<input\b[^>]*>/g)
            ?.find((item) => item.includes(field.inputValue));
          assert.ok(input, `${locale}/${field.step} must retain the configured endpoint input`);
          assert.equal(/\sdisabled(?:="")?(?:\s|>)/.test(input), false);
        }
      }
    }
  } finally {
    await vite.close();
  }
});

test("F4.20-SETUP-PAGE-RENDER: the initialization container renders open, locked, closed, and failed states safely", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { InitializationPage } = await vite.ssrLoadModule(
      "/src/features/identity/ui/InitializationPage.tsx",
    );
    const [{ createElement }, { renderToStaticMarkup }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const readyBootstrap = {
      status: "ready",
      key: "setup-window",
      data: { initialized: false, setupAvailable: true, operatorAuthorized: true },
      receivedAt: 1,
    };
    const openIdleSnapshot = {
      bootstrap: readyBootstrap,
      databaseCheck: { status: "loading", key: "database-check" },
      sourceCheck: { status: "idle" },
      initialization: { status: "idle" },
    };
    const unknownSnapshot = {
      ...openIdleSnapshot,
      databaseCheck: { status: "idle" },
      initialization: { status: "result-unknown", requestKey: "synthetic-request" },
    };
    const failedSnapshot = {
      ...openIdleSnapshot,
      databaseCheck: { status: "idle" },
      initialization: {
        status: "error",
        requestKey: "synthetic-request",
        error: new AppError(AppErrorKind.SERVER, "SYNTHETIC-SECRET raw infrastructure detail"),
      },
    };
    const closedSnapshot = {
      ...openIdleSnapshot,
      bootstrap: {
        status: "ready",
        key: "setup-window",
        data: { initialized: true },
        receivedAt: 2,
      },
      databaseCheck: { status: "idle" },
    };
    const serverClosedReceiptSnapshot = {
      ...openIdleSnapshot,
      databaseCheck: { status: "idle" },
      initialization: { status: "closed" },
    };
    const completedSnapshot = {
      ...openIdleSnapshot,
      bootstrap: {
        status: "ready",
        key: "setup-window",
        data: { initialized: true },
        receivedAt: 3,
      },
      databaseCheck: { status: "idle" },
      initialization: {
        status: "ready",
        requestKey: "synthetic-request",
        operationId: "synthetic-operation",
      },
    };
    const connectionFailuresSnapshot = {
      ...openIdleSnapshot,
      databaseCheck: {
        status: "ready",
        key: "database-check",
        data: { status: "unreachable", reason: "authentication" },
      },
      sourceCheck: {
        status: "ready",
        key: "source-check",
        data: { status: "unreachable", reason: "unsupported" },
      },
    };
    const cases = [
      { name: "open-check-pending", snapshot: openIdleSnapshot },
      { name: "unknown-result", snapshot: unknownSnapshot },
      { name: "failed-initialization", snapshot: failedSnapshot },
      { name: "already-initialized", snapshot: closedSnapshot },
      { name: "server-closed-stale-bootstrap", snapshot: serverClosedReceiptSnapshot },
      { name: "completed-success", snapshot: completedSnapshot },
      { name: "connection-failures", snapshot: connectionFailuresSnapshot },
    ];
    const workflowFor = (snapshot) => ({
      getSnapshot: () => snapshot,
      subscribe: () => () => {},
      restore: async () => snapshot.bootstrap.data,
      checkDatabase: async () => ({ status: "reachable" }),
      checkSource: async () => ({ status: "reachable" }),
      invalidateChecks() {},
      initialize: async () => snapshot.initialization,
      inspect: async () => snapshot.initialization,
      cancel() {},
      dispose() {},
    });

    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      });
      for (const item of cases) {
        const markup = renderToStaticMarkup(
          createElement(
            I18nextProvider,
            { i18n },
            createElement(InitializationPage, {
              workflow: workflowFor(item.snapshot),
              onCompleted() {},
            }),
          ),
        );
        assert.ok(markup.length > 0, `${locale}/${item.name} must render`);
        assert.ok(
          !markup.includes("synthetic-request"),
          `${locale}/${item.name} must not expose request keys`,
        );
        assert.ok(
          !markup.includes("SYNTHETIC-SECRET"),
          `${locale}/${item.name} must not expose secrets`,
        );

        if (item.name === "open-check-pending") {
          const buttonText = i18n.t("setup.action.testConnection");
          const checkButton = markup
            .match(/<button\b[^>]*>[\s\S]*?<\/button>/g)
            ?.find((button) => button.includes(buttonText));
          assert.ok(checkButton, `${locale} must render the database check action`);
          assert.match(checkButton, /\sdisabled(?:="")?(?:\s|>)/);
          assert.ok(
            markup.includes(i18n.t("setup.field.host")),
            `${locale} keeps setup fields visible`,
          );
          assert.doesNotMatch(markup, /<fieldset\b[^>]*\sdisabled(?:="")?(?:\s|>)/);
        } else if (item.name === "unknown-result") {
          assert.match(markup, /<fieldset\b[^>]*\sdisabled(?:="")?(?:\s|>)/);
          assert.ok(markup.includes(i18n.t("shell.feedback.inspectOutcome")));
        } else if (item.name === "failed-initialization") {
          assert.ok(markup.includes(i18n.t("setup.workflow.error")));
          assert.ok(!markup.includes("raw infrastructure detail"));
        } else if (item.name === "connection-failures") {
          assert.ok(markup.includes(i18n.t("setup.check.authenticationFailed")));
          assert.ok(markup.includes(i18n.t("setup.check.unsupported")));
          const databaseRetryLabel = i18n.t("setup.action.testConnection");
          const databaseRetry = markup
            .match(/<button\b[^>]*>[\s\S]*?<\/button>/g)
            ?.find((candidate) => candidate.includes(databaseRetryLabel));
          assert.ok(databaseRetry, `${locale} keeps the database retry available after failure`);
          assert.doesNotMatch(databaseRetry, /\sdisabled(?:="")?(?:\s|>)/);
        } else if (item.name === "server-closed-stale-bootstrap") {
          assert.ok(markup.includes(i18n.t("setup.workflow.closed")));
          assert.ok(
            !markup.includes(i18n.t("setup.intro.title")),
            "a setup-closed server receipt must hide the wizard despite a stale-open bootstrap",
          );
          assert.ok(
            markup.includes(i18n.t("shell.feedback.retryRead")),
            "the user can explicitly refresh the stale bootstrap fact",
          );
        } else if (item.name === "completed-success") {
          assert.ok(markup.includes(i18n.t("setup.workflow.ready")));
          assert.ok(
            !markup.includes(i18n.t("setup.intro.title")),
            "confirmed completion must not keep the sensitive setup form rendered",
          );
        } else {
          assert.ok(markup.includes(i18n.t("setup.workflow.closed")));
          assert.ok(
            !markup.includes(i18n.t("setup.intro.title")),
            "closed setup must not render the wizard",
          );
        }
      }
    }
  } finally {
    await vite.close();
  }
});

test("F4.20-SETUP-FIELD-ERROR-RENDER: actual setup fields render translated field errors", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { SetupWizard } = await vite.ssrLoadModule("/src/features/identity/ui/SetupWizard.tsx");
    const { INITIAL_SETUP_DRAFT } = await vite.ssrLoadModule(
      "/src/features/identity/model/setup.ts",
    );
    const [{ createElement }, { renderToStaticMarkup }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const flow = {
      steps: ["storage", "admin", "sources", "complete"],
      stepIndex: 0,
      step: "storage",
      isFirstStep: true,
      isLastStep: false,
      draft: INITIAL_SETUP_DRAFT,
      fieldIssues: [
        { key: "setup.required", field: "database.host" },
        { key: "setup.required", field: "database.name" },
      ],
      notice: null,
      selectDatabase() {},
      setDatabasePort() {},
      patchDatabase() {},
      selectRuleSource() {},
      patchRuleSource() {},
      selectAuthenticationMode() {},
      patchSourceCredentials() {},
      patchAdmin() {},
      goNext() {},
      goBack() {},
      reportInfo() {},
      reportIssues() {},
      prepareSubmission() {
        return null;
      },
      clearSensitive() {},
    };

    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      });
      const markup = renderToStaticMarkup(
        createElement(
          I18nextProvider,
          { i18n },
          createElement(SetupWizard, {
            flow,
            onFinish() {},
            onTestDatabase() {},
            onTestSource() {},
          }),
        ),
      );
      const requiredCopy = i18n.t("setup.required");
      assert.ok(markup.includes(i18n.t("setup.field.host")), `${locale} renders host field label`);
      assert.ok(
        markup.includes(i18n.t("setup.field.databaseName")),
        `${locale} renders database field label`,
      );
      assert.ok(markup.includes(requiredCopy), `${locale} renders field-level error copy`);
      assert.match(markup, /role="alert"/);
    }
  } finally {
    await vite.close();
  }
});

test("F4.31-PASSWORD-PAGE-RENDER: the actual own-password page binds only the session identity and renders three localized secret fields", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { OwnPasswordPage } = await vite.ssrLoadModule(
      "/src/features/identity/ui/OwnPasswordPage.tsx",
    );
    const [{ createElement }, { renderToStaticMarkup }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const identity = {
      accountId: "session-account-17",
      username: "session-viewer",
      roleId: "view",
      capabilities: ["metrics:view"],
      sessionEpoch: "session-epoch-4",
    };
    let workflowSnapshot = { status: "idle" };
    const workflow = {
      getSnapshot: () => workflowSnapshot,
      subscribe: () => () => {},
      submit: async () => ({ sessionDisposition: "reauthenticate" }),
      cancel() {},
      dispose() {},
    };

    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      });
      const markup = renderToStaticMarkup(
        createElement(
          I18nextProvider,
          { i18n },
          createElement(OwnPasswordPage, {
            workflow,
            identity,
            onConfirmed() {},
            onReauthenticate() {},
          }),
        ),
      );
      const inputs = markup.match(/<input\b[^>]*>/g) ?? [];
      assert.equal(inputs.length, 3, `${locale} renders only the current/new/confirm fields`);
      assert.deepEqual(
        inputs.map((input) => input.match(/\btype="([^"]+)"/)?.[1]),
        ["password", "password", "password"],
        `${locale} never renders password values as plain text`,
      );
      assert.deepEqual(
        inputs.map((input) => input.match(/\bautoComplete="([^"]+)"/)?.[1]),
        ["current-password", "new-password", "new-password"],
        `${locale} uses the expected password-manager autocomplete semantics`,
      );
      for (const key of [
        "changePassword.field.current",
        "changePassword.field.next",
        "changePassword.field.confirm",
      ]) {
        assert.ok(markup.includes(i18n.t(key)), `${locale} renders ${key}`);
      }
      assert.ok(markup.includes("session-viewer"), `${locale} uses the session username`);
      assert.ok(!markup.includes("session-account-17"), "account IDs are not rendered into the UI");
      assert.ok(!markup.includes("accountId"), "there is no user-selectable account target");

      workflowSnapshot = {
        status: "error",
        error: { status: 400, code: "current_password_invalid" },
      };
      const rejectedMarkup = renderToStaticMarkup(
        createElement(
          I18nextProvider,
          { i18n },
          createElement(OwnPasswordPage, {
            workflow,
            identity,
            onConfirmed() {},
            onReauthenticate() {},
          }),
        ),
      );
      assert.ok(
        rejectedMarkup.includes(i18n.t("password.remote.currentInvalid")),
        `${locale} maps current_password_invalid to the correctable current-password message`,
      );
      assert.ok(
        !rejectedMarkup.includes(i18n.t("password.remote.session")),
        `${locale} does not misreport an incorrect current password as an expired session`,
      );
      workflowSnapshot = { status: "idle" };
    }
  } finally {
    await vite.close();
  }
});

test("F4.22-LOGIN-PAGE-RENDER: the actual login page separates safe rejection, unknown write and unavailable session states", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { LoginEntryPage } = await vite.ssrLoadModule(
      "/src/features/identity/ui/LoginEntryPage.tsx",
    );
    const { AuthenticationProvider } = await vite.ssrLoadModule(
      "/src/features/identity/state/AuthenticationProvider.tsx",
    );
    const [{ createElement }, { renderToStaticMarkup }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const cases = [
      {
        name: "known-rejection",
        snapshot: {
          access: { phase: "resolved", facts: { kind: "anonymous" } },
          login: {
            status: "error",
            error: new AppError(AppErrorKind.UNAUTHORIZED, "PRIVATE-ACCOUNT-EXISTS-DETAIL", {
              status: 401,
            }),
          },
          logout: { status: "idle" },
        },
        feedbackKey: "login.remote.invalid",
      },
      {
        name: "unknown-write",
        snapshot: {
          access: { phase: "unavailable" },
          login: {
            status: "result-unknown",
            error: new AppError(AppErrorKind.NETWORK, "PRIVATE-TRANSPORT-DETAIL"),
          },
          logout: { status: "idle" },
        },
        feedbackKey: "login.remote.unknown",
      },
      {
        name: "session-unavailable",
        snapshot: {
          access: { phase: "unavailable" },
          login: { status: "idle" },
          logout: { status: "idle" },
        },
        feedbackKey: "login.remote.unavailable",
      },
    ];
    const workflowFor = (snapshot) => ({
      getSnapshot: () => snapshot,
      subscribe: () => () => {},
      restore: async () => null,
      login: async () => null,
      logout: async () => undefined,
      inspectSession: async () => null,
      clearLoginFailure() {},
      cancel() {},
      dispose() {},
    });

    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      });
      const anonymousWorkflow = workflowFor({
        access: { phase: "resolved", facts: { kind: "anonymous" } },
        login: { status: "idle" },
        logout: { status: "idle" },
      });
      const renderLogin = (demoMode) =>
        renderToStaticMarkup(
          createElement(
            I18nextProvider,
            { i18n },
            createElement(
              AuthenticationProvider,
              { workflow: anonymousWorkflow },
              createElement(LoginEntryPage, {
                onAuthenticated() {},
                onSetupRequired() {},
                demoMode,
              }),
            ),
          ),
        );
      const liveLoginMarkup = renderLogin(false);
      const demoLoginMarkup = renderLogin(true);
      assert.ok(
        liveLoginMarkup.includes(i18n.t("login.description")),
        `${locale} renders the environment-neutral login description`,
      );
      assert.ok(
        !liveLoginMarkup.includes(i18n.t("login.demoNotice")),
        `${locale} never shows demo-only identities in the live login page`,
      );
      assert.ok(
        demoLoginMarkup.includes(i18n.t("login.demoNotice")),
        `${locale} explains synthetic sign-in and data in the demo login page`,
      );
      for (const item of cases) {
        const workflow = workflowFor(item.snapshot);
        const markup = renderToStaticMarkup(
          createElement(
            I18nextProvider,
            { i18n },
            createElement(
              AuthenticationProvider,
              { workflow },
              createElement(LoginEntryPage, { onAuthenticated() {}, onSetupRequired() {} }),
            ),
          ),
        );
        assert.ok(markup.includes(i18n.t(item.feedbackKey)), `${locale}/${item.name} feedback`);
        assert.ok(!markup.includes("PRIVATE-ACCOUNT-EXISTS-DETAIL"));
        assert.ok(!markup.includes("PRIVATE-TRANSPORT-DETAIL"));

        const inputs = markup.match(/<input\b[^>]*>/g) ?? [];
        if (item.name === "known-rejection") {
          assert.equal(
            inputs.length,
            2,
            `${locale} keeps both editable fields after a known rejection`,
          );
          assert.ok(
            inputs.some((input) => input.includes('autoComplete="username"')),
            `${locale} keeps the account field password-manager semantics`,
          );
          assert.ok(
            inputs.some(
              (input) =>
                /type="password"/.test(input) && /autoComplete="current-password"/.test(input),
            ),
            `${locale} keeps the password masked with current-password autocomplete`,
          );
          const submitLabel = i18n.t("login.submit");
          const submit = markup
            .match(/<button\b[^>]*>[\s\S]*?<\/button>/g)
            ?.find((button) => button.includes(submitLabel));
          assert.ok(submit, `${locale} retains the deliberate retry action`);
          assert.match(submit, /type="submit"/);
          assert.doesNotMatch(submit, /\sdisabled(?:="")?(?:\s|>)/);
          const revealButton = markup
            .match(/<button\b[^>]*>[\s\S]*?<\/button>/g)
            ?.find((button) => button.includes(i18n.t("login.remote.showPassword")));
          assert.ok(revealButton, `${locale} exposes a localized password-visibility control`);
          assert.match(revealButton, /type="button"/);
          assert.match(revealButton, /aria-pressed="false"/);
        } else if (item.name === "unknown-write") {
          assert.equal(inputs.length, 2);
          assert.ok(inputs.every((input) => /\sdisabled(?:="")?(?:\s|>)/.test(input)));
          assert.ok(markup.includes(i18n.t("login.remote.inspect")));
        } else {
          assert.equal(
            inputs.length,
            0,
            "do not show a new login form while session authority is unavailable",
          );
          assert.ok(markup.includes(i18n.t("login.remote.inspect")));
        }
      }
    }
  } finally {
    await vite.close();
  }
});

test("F4.21-BOOTSTRAP-GATE-RENDER: initialization content is rendered only after operator authorization", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { BootstrapAuthorizationGate } = await vite.ssrLoadModule(
      "/src/features/identity/ui/BootstrapAuthorizationGate.tsx",
    );
    const [{ createElement }, { renderToStaticMarkup }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const snapshots = [
      {
        name: "authorization-required",
        snapshot: {
          gate: {
            status: "ready",
            key: "synthetic-gate",
            data: { kind: "open", authorized: false },
            receivedAt: 1,
          },
          command: { status: "idle" },
        },
        showsChild: false,
      },
      {
        name: "authorized",
        snapshot: {
          gate: {
            status: "ready",
            key: "synthetic-gate",
            data: { kind: "open", authorized: true },
            receivedAt: 2,
          },
          command: { status: "idle" },
        },
        showsChild: true,
      },
      {
        name: "closed",
        snapshot: {
          gate: {
            status: "ready",
            key: "synthetic-gate",
            data: { kind: "closed" },
            receivedAt: 3,
          },
          command: { status: "idle" },
        },
        showsChild: false,
      },
    ];
    const workflowFor = (snapshot) => ({
      getSnapshot: () => snapshot,
      subscribe: () => () => {},
      restore: async () => snapshot.gate.data,
      authorize: async () => {},
      inspect: async () => snapshot.gate.data,
      cancel() {},
      dispose() {},
    });

    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      });
      for (const item of snapshots) {
        const markup = renderToStaticMarkup(
          createElement(
            I18nextProvider,
            { i18n },
            createElement(
              BootstrapAuthorizationGate,
              { workflow: workflowFor(item.snapshot) },
              createElement("span", null, "PROTECTED_SETUP_SENTINEL"),
            ),
          ),
        );
        assert.equal(
          markup.includes("PROTECTED_SETUP_SENTINEL"),
          item.showsChild,
          `${locale}/${item.name} must respect the server-confirmed authorization gate`,
        );
        if (item.name === "authorization-required") {
          assert.ok(markup.includes(i18n.t("setup.operator.code")));
          assert.match(markup, /type="password"/);
        }
        if (item.name === "closed") assert.ok(markup.includes(i18n.t("setup.operator.closed")));
      }
    }
  } finally {
    await vite.close();
  }
});

test("I18N-DYNAMIC-RULE-COPY: the actual rule workbench hook builds translated copy in all locales", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { useRuleCopy } = await vite.ssrLoadModule("/src/features/rules/i18n/useRuleCopy.ts");
    const [{ createElement }, { renderToString }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);
    const flattenStrings = (value) =>
      typeof value === "string"
        ? [value]
        : Array.isArray(value)
          ? value.flatMap(flattenStrings)
          : value && typeof value === "object"
            ? Object.values(value).flatMap(flattenStrings)
            : [];
    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      });
      let messages;
      function CaptureRuleCopy() {
        messages = useRuleCopy().messages;
        return null;
      }
      renderToString(createElement(I18nextProvider, { i18n }, createElement(CaptureRuleCopy)));
      const rendered = flattenStrings(messages);
      assert.ok(rendered.length > 100, `${locale} must build the full rule workbench copy`);
      for (const value of rendered) {
        assert.ok(value.length > 0, `${locale} must not render an empty rule label`);
        assert.ok(!value.includes("{{"), `${locale} left rule-copy interpolation unresolved`);
        assert.ok(!value.startsWith("rules."), `${locale} leaked a rule translation key`);
      }
    }
  } finally {
    await vite.close();
  }
});

test("I18N-DYNAMIC-DEPLOYMENT-PRESENTATION: publication field labels render from the actual producer in all locales", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { publicationStages } = await vite.ssrLoadModule(
      "/src/features/rules/presentation/deploymentLabels.ts",
    );
    const phases = [
      { state: "succeeded", observedAtMs: 1, reason: null },
      { state: "running", observedAtMs: 2, reason: null },
      { state: "awaiting", observedAtMs: null, reason: null },
    ];
    const labels = publicationStages({
      validation: phases[0],
      configurationWrite: phases[1],
      readBack: phases[2],
    });
    assert.deepEqual(
      labels.map(({ labelKey }) => labelKey),
      [
        "rules.deployment.validation",
        "rules.deployment.configurationWrite",
        "rules.deployment.readBack",
      ],
    );
    assert.deepEqual(
      labels.map(({ phase }) => phase),
      phases,
    );
    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
      });
      for (const { labelKey } of labels) {
        const rendered = i18n.t(labelKey);
        assert.notEqual(rendered, labelKey, `${locale} must translate ${labelKey}`);
        assert.ok(rendered.length > 0, `${locale}/${labelKey} must not render empty text`);
      }
    }
  } finally {
    await vite.close();
  }
});

test("I18N-DYNAMIC-PRESENTATION: actual navigation, instance and identity feedback producers translate in all locales", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const navigation = await vite.ssrLoadModule("/src/app/router/navigation.ts");
    const instanceStatus = await vite.ssrLoadModule(
      "/src/features/applications/presentation/instanceStatus.ts",
    );
    const accountFeedback = await vite.ssrLoadModule(
      "/src/features/identity/presentation/accountFeedback.ts",
    );
    const loginFeedback = await vite.ssrLoadModule(
      "/src/features/identity/presentation/loginFeedback.ts",
    );
    const unavailableFeedback = loginFeedback.loginFeedback({
      access: { phase: "unavailable" },
      login: { status: "idle" },
      logout: { status: "idle" },
    });
    assert.equal(unavailableFeedback.key, "login.remote.unavailable");
    assert.equal(unavailableFeedback.canInspect, true);
    const unknownWriteFeedback = loginFeedback.loginFeedback({
      access: { phase: "unavailable" },
      login: {
        status: "result-unknown",
        error: new AppError(AppErrorKind.NETWORK, "private transport details"),
      },
      logout: { status: "idle" },
    });
    assert.equal(unknownWriteFeedback.key, "login.remote.unknown");
    assert.equal(unknownWriteFeedback.canInspect, true);
    const retryFeedback = loginFeedback.loginFeedback(
      {
        access: { phase: "resolved", facts: { kind: "anonymous" } },
        login: { status: "idle" },
        logout: { status: "idle" },
      },
      2,
    );
    assert.equal(retryFeedback.key, "login.remote.rateLimitedFor");
    assert.deepEqual(retryFeedback.values, { count: 2 });
    const realtimeReadCopy = await vite.ssrLoadModule(
      "/src/features/realtime/presentation/realtimeReadCopy.ts",
    );
    const keys = [
      ...navigation.navigationItemsForAccess(true).map(({ i18nKey }) => i18nKey),
      ...navigation.navigationItemsForAccess(false).map(({ i18nKey }) => i18nKey),
      retryFeedback.key,
      ...[
        { status: "healthy", cpu: 10, memory: 10 },
        { status: "warning", cpu: 10, memory: 10 },
        { status: "critical", cpu: 10, memory: 10 },
        { status: "healthy", cpu: 81, memory: 10 },
        { status: "healthy", cpu: 10, memory: 81 },
      ].map(instanceStatus.instanceStatusLabelKey),
      ...[
        { authorized: false, inspecting: false, mutation: { status: "idle" } },
        { authorized: true, inspecting: true, mutation: { status: "idle" } },
        { authorized: true, inspecting: false, mutation: { status: "pending" } },
        { authorized: true, inspecting: false, mutation: { status: "success" } },
        { authorized: true, inspecting: false, mutation: { status: "result-unknown" } },
        ...["account_username_taken", "account_last_admin", "account_built_in", "other"].map(
          (code) => ({
            authorized: true,
            inspecting: false,
            mutation: { status: "error", error: { code } },
          }),
        ),
        {
          authorized: true,
          inspecting: false,
          mutation: { status: "conflict", error: { code: "account_conflict" } },
        },
      ].map((snapshot) => accountFeedback.accountFeedbackKey(snapshot)),
      ...[
        { access: { phase: "unavailable" }, login: { status: "idle" } },
        { access: { phase: "expired" }, login: { status: "idle" } },
        {
          access: { phase: "resolved", facts: { kind: "uninitialized", setupAvailable: true } },
          login: { status: "idle" },
        },
        {
          access: { phase: "resolved", facts: { kind: "uninitialized", setupAvailable: false } },
          login: { status: "idle" },
        },
        {
          access: { phase: "resolved", facts: { kind: "authenticated" } },
          login: { status: "idle" },
        },
        ...["checking", "authenticating", "unknown"].map((phase) => ({
          access: { phase },
          login: { status: "idle" },
        })),
        ...[
          { status: 429, kind: AppErrorKind.PROTOCOL },
          { status: 401, kind: AppErrorKind.UNAUTHORIZED },
          { status: 403, kind: AppErrorKind.FORBIDDEN },
          { status: 503, kind: AppErrorKind.SERVER },
        ].map((error) => ({
          access: { phase: "resolved", facts: { kind: "anonymous" } },
          login: { status: "error", error },
        })),
      ]
        .map((snapshot) => loginFeedback.loginFeedback(snapshot)?.key)
        .filter(Boolean),
      realtimeReadCopy.realtimeReadCopy({
        status: "error",
        key: "network-error",
        error: new AppError(AppErrorKind.NETWORK, "synthetic offline"),
      }).error,
      realtimeReadCopy.realtimeReadCopy({
        status: "stale",
        key: "network-stale",
        data: {},
        error: new AppError(AppErrorKind.NETWORK, "synthetic offline"),
      }).stale,
    ];
    assert.ok(keys.length > 20, "all finite presentation branches must be exercised");
    assert.equal(keys.includes(null), false, "all account feedback scenarios need a key");

    for (const locale of locales) {
      const i18n = createInstance();
      await i18n.init({
        resources: { [locale]: { translation: catalogs[locale] } },
        lng: locale,
        supportedLngs: locales,
        fallbackLng: false,
        nsSeparator: false,
        interpolation: { escapeValue: false },
      });
      for (const key of new Set(keys)) {
        const rendered = i18n.t(key, { lng: locale, count: 2 });
        assert.notEqual(rendered, key, `${locale} must translate presentation key ${key}`);
        assert.ok(!rendered.includes("{{"), `${locale}/${key} left an interpolation unresolved`);
      }
    }
  } finally {
    await vite.close();
  }
});

test("I18N-RUNTIME-LAZY: startup loads only the active catalog and language changes load each locale on demand", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { default: i18n, i18nReady } = await vite.ssrLoadModule("/src/app/i18n/config.ts");
    await i18nReady;
    assert.equal(i18n.language, "zh-CN");
    assert.equal(i18n.hasResourceBundle("zh-CN", "translation"), true);
    assert.equal(i18n.hasResourceBundle("en-US", "translation"), false);
    assert.equal(i18n.hasResourceBundle("ja-JP", "translation"), false);

    await i18n.changeLanguage("en-US");
    assert.equal(i18n.t("shell.language"), "Language");
    assert.equal(i18n.hasResourceBundle("en-US", "translation"), true);
    assert.equal(i18n.hasResourceBundle("ja-JP", "translation"), false);

    await i18n.changeLanguage("ja-JP");
    assert.equal(i18n.t("shell.language"), "表示言語");
    assert.equal(i18n.hasResourceBundle("ja-JP", "translation"), true);
  } finally {
    await vite.close();
  }
});

test("ASTRYX-I18N-LAZY: only the selected public catalog is loaded before locale rendering", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const { default: i18n, i18nReady } = await vite.ssrLoadModule("/src/app/i18n/config.ts");
    await i18nReady;
    const { changeLocale } = await vite.ssrLoadModule("/src/app/i18n/changeLocale.ts");
    const catalogs = await vite.ssrLoadModule("/src/app/i18n/astryxLocaleCatalogs.ts");
    await catalogs.loadAstryxLocaleCatalog("zh-CN");
    assert.deepEqual(Object.keys(catalogs.getLoadedAstryxLocaleCatalog("zh-CN")), ["zh-CN"]);

    await changeLocale("en-US");
    assert.equal(i18n.language, "en-US");
    assert.deepEqual(Object.keys(catalogs.getLoadedAstryxLocaleCatalog("en-US")), []);

    await changeLocale("ja-JP");
    assert.equal(i18n.language, "ja-JP");
    assert.equal(i18n.t("shell.language"), "表示言語");
    assert.deepEqual(Object.keys(catalogs.getLoadedAstryxLocaleCatalog("ja-JP")), ["ja-JP"]);

    const { createAstryxLocaleCatalogOwner } = catalogs;
    assert.deepEqual(Object.keys(catalogs.getLoadedAstryxLocaleCatalog("en-US")), []);
    await catalogs.loadAstryxLocaleCatalog("zh-CN");
    assert.deepEqual(Object.keys(catalogs.getLoadedAstryxLocaleCatalog("zh-CN")), ["zh-CN"]);
    assert.equal(
      catalogs.getLoadedAstryxLocaleCatalog("zh-CN")["zh-CN"]["@astryx.pagination.next"]
        .defaultMessage,
      "转到下一页",
    );
    await catalogs.loadAstryxLocaleCatalog("ja-JP");
    assert.deepEqual(Object.keys(catalogs.getLoadedAstryxLocaleCatalog("ja-JP")), ["ja-JP"]);
    assert.equal(
      catalogs.getLoadedAstryxLocaleCatalog("ja-JP")["ja-JP"]["@astryx.pagination.next"]
        .defaultMessage,
      "次のページへ",
    );

    let attempts = 0;
    const retryableOwner = createAstryxLocaleCatalogOwner({
      "zh-CN": async () => {
        attempts += 1;
        if (attempts === 1) throw new Error("deferred catalog unavailable");
        return { "@astryx.pagination.next": { defaultMessage: "转到下一页" } };
      },
    });
    await assert.rejects(retryableOwner.load("zh-CN"), /deferred catalog unavailable/);
    await retryableOwner.load("zh-CN");
    assert.equal(attempts, 2, "a rejected deferred import is retried, not cached forever");
    assert.equal(
      retryableOwner.getLoaded("zh-CN")["zh-CN"]["@astryx.pagination.next"].defaultMessage,
      "转到下一页",
    );
  } finally {
    await vite.close();
  }
});
