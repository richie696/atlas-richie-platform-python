import assert from "node:assert/strict";
import { test } from "node:test";
import { createLatestLocaleSwitcher } from "../../src/app/i18n/localeSwitcher";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("I18N-LATEST: an older catalog load cannot overwrite a later locale selection", async () => {
  const slowPrepare = deferred();
  const applied = [];
  const persisted = [];
  const switchLocale = createLatestLocaleSwitcher({
    prepare: (locale) => (locale === "zh-CN" ? slowPrepare.promise : Promise.resolve()),
    apply: async (locale) => applied.push(locale),
  });

  const oldRequest = switchLocale("zh-CN", (locale) => persisted.push(locale));
  const latestRequest = switchLocale("en-US", (locale) => persisted.push(locale));

  assert.equal(await latestRequest, true);
  slowPrepare.resolve();
  assert.equal(await oldRequest, false);
  assert.deepEqual(applied, ["en-US"]);
  assert.deepEqual(persisted, ["en-US"]);
});

test("I18N-QUEUE: a newer request commits after an in-flight locale apply", async () => {
  const firstApply = deferred();
  const firstApplyStarted = deferred();
  const applied = [];
  const persisted = [];
  const switchLocale = createLatestLocaleSwitcher({
    prepare: async () => {},
    apply: async (locale) => {
      applied.push(locale);
      if (locale === "zh-CN") {
        firstApplyStarted.resolve();
        await firstApply.promise;
      }
    },
  });

  const persist = (locale) => persisted.push(locale);
  const older = switchLocale("zh-CN", persist);
  await firstApplyStarted.promise;
  const newer = switchLocale("ja-JP", persist);
  firstApply.resolve();

  assert.equal(await older, false);
  assert.equal(await newer, true);
  assert.deepEqual(applied, ["zh-CN", "ja-JP"]);
  assert.deepEqual(persisted, ["ja-JP"]);
});

test("I18N-FAILURE: failed catalog preparation never applies or persists a locale", async () => {
  const applied = [];
  const persisted = [];
  const switchLocale = createLatestLocaleSwitcher({
    prepare: async () => {
      throw new Error("catalog unavailable");
    },
    apply: async (locale) => applied.push(locale),
  });

  await assert.rejects(
    switchLocale("ja-JP", (locale) => persisted.push(locale)),
    /catalog unavailable/,
  );
  assert.deepEqual(applied, []);
  assert.deepEqual(persisted, []);
});

test("I18N-APPLY-RECOVERY: a failed locale commit does not poison later switches", async () => {
  const applied = [];
  const persisted = [];
  const switchLocale = createLatestLocaleSwitcher({
    prepare: async () => {},
    apply: async (locale) => {
      if (locale === "ja-JP") throw new Error("translation runtime unavailable");
      applied.push(locale);
    },
  });

  await assert.rejects(
    switchLocale("ja-JP", (locale) => persisted.push(locale)),
    /translation runtime unavailable/,
  );
  assert.equal(await switchLocale("en-US", (locale) => persisted.push(locale)), true);
  assert.deepEqual(applied, ["en-US"]);
  assert.deepEqual(persisted, ["en-US"]);
});
