import assert from "node:assert/strict";
import { Window } from "happy-dom";
import { createInstance } from "i18next";
import { createServer } from "vite";
import { test } from "node:test";

test("shared Astryx field adapters render unique label, hint, and error relationships", async () => {
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: { middlewareMode: true, hmr: false, ws: false },
  });
  try {
    const [
      { TextField },
      { NumberField },
      { Select },
      { AstryxProvider },
      { loadAstryxLocaleCatalog },
    ] = await Promise.all([
      vite.ssrLoadModule("/src/shared/ui/TextField.tsx"),
      vite.ssrLoadModule("/src/shared/ui/NumberField.tsx"),
      vite.ssrLoadModule("/src/shared/ui/Select.tsx"),
      vite.ssrLoadModule("/src/app/providers/AstryxProvider.tsx"),
      vite.ssrLoadModule("/src/app/i18n/astryxLocaleCatalogs.ts"),
    ]);
    const [{ createElement }, { renderToStaticMarkup }, { I18nextProvider }] = await Promise.all([
      import("react"),
      import("react-dom/server"),
      import("react-i18next"),
    ]);

    await loadAstryxLocaleCatalog("en-US");
    const i18n = createInstance();
    await i18n.init({
      lng: "en-US",
      fallbackLng: false,
      resources: { "en-US": { translation: {} } },
    });

    const markup = renderToStaticMarkup(
      createElement(
        I18nextProvider,
        { i18n },
        createElement(
          AstryxProvider,
          null,
          createElement(
            "main",
            null,
            createElement(TextField, {
              label: "Account name",
              value: "",
              onChange() {},
              hint: "Use the login identifier",
              error: "Account name is required",
              isLabelHidden: true,
            }),
            createElement(NumberField, {
              label: "Limit",
              value: 10,
              onChange() {},
              hint: "Requests per second",
              error: "Limit is outside the supported range",
            }),
            createElement(Select, {
              label: "Rule mode",
              value: "direct",
              options: [{ value: "direct", label: "Direct" }],
              onChange() {},
              hint: "Choose how excess traffic is handled",
              error: "Select a supported rule mode",
            }),
          ),
        ),
      ),
    );

    const browser = new Window();
    try {
      browser.document.body.innerHTML = markup;
      const { document } = browser;
      const ids = [...document.querySelectorAll("[id]")].map((element) => element.id);
      assert.equal(new Set(ids).size, ids.length, "SSR must not generate duplicate field IDs");

      const controls = [...document.querySelectorAll("input, [role='combobox']")];
      assert.equal(controls.length, 3, "each shared adapter renders one labeled control");
      for (const control of controls) {
        const id = control.id;
        assert.ok(id, "every control has an ID");
        assert.equal(
          document.querySelectorAll(`label[for="${id}"]`).length,
          1,
          "every control has exactly one associated label, including visually hidden labels",
        );
        assert.equal(control.getAttribute("aria-invalid"), "true");

        const describedBy = control.getAttribute("aria-describedby")?.split(/\s+/) ?? [];
        assert.ok(describedBy.length >= 2, "hint and error are both associated to the control");
        for (const describedId of describedBy) {
          assert.equal(
            document.querySelectorAll(`#${describedId}`).length,
            1,
            `aria-describedby target ${describedId} exists exactly once`,
          );
        }
        assert.ok(
          describedBy.some((describedId) =>
            document.getElementById(describedId)?.textContent?.trim(),
          ),
          "described-by references point to rendered hint/error content",
        );
      }

      const labels = [...document.querySelectorAll("label[for]")];
      assert.ok(labels.some((label) => label.textContent?.includes("Account name")));
      assert.ok(labels.some((label) => label.textContent?.includes("Limit")));
      assert.ok(labels.some((label) => label.textContent?.includes("Rule mode")));
      assert.ok(markup.includes("Use the login identifier"));
      assert.ok(markup.includes("Requests per second"));
      assert.ok(markup.includes("Choose how excess traffic is handled"));
      assert.ok(markup.includes("Account name is required"));
      assert.ok(markup.includes("Limit is outside the supported range"));
      assert.ok(markup.includes("Select a supported rule mode"));
    } finally {
      browser.happyDOM.abort();
    }
  } finally {
    await vite.close();
  }
});
