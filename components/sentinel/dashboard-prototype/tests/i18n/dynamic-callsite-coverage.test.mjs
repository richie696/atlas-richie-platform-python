import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { test } from "node:test";

const dynamicCallsites = [
  {
    path: "src/app/shell/Navigation.tsx",
    call: "t(item.i18nKey)",
    suite: "I18N-DYNAMIC-PRESENTATION",
    producer: "/src/app/router/navigation.ts",
  },
  {
    path: "src/features/identity/ui/CreateAccountDialog.tsx",
    call: "t(issue.key, issue.params)",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/model/account.ts",
  },
  {
    path: "src/features/identity/ui/components/LoginSurface.tsx",
    call: "t(issue.key, issue.params)",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/model/account.ts",
  },
  {
    path: "src/features/identity/ui/LoginEntryPage.tsx",
    call: "t(feedback.key, feedback.values)",
    suite: "I18N-DYNAMIC-PRESENTATION",
    producer: "/src/features/identity/presentation/loginFeedback.ts",
  },
  {
    path: "src/features/identity/ui/OwnPasswordPage.tsx",
    call: "t(issue.key, issue.params)",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/model/passwordPolicy.ts",
  },
  {
    path: "src/features/identity/ui/SetupWizard.tsx",
    call: "t(issue.key, issue.params)",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/model/setup.ts",
  },
  {
    path: "src/features/identity/ui/setup/InitializationFeedback.tsx",
    call: "t(initializationFeedbackKey(snapshot.initialization))",
    suite: "I18N-DYNAMIC-SETUP-FEEDBACK",
    producer: "/src/features/identity/presentation/setupFeedback.ts",
  },
  {
    path: "src/features/identity/ui/components/AccountCommandFeedback.tsx",
    call: "t(key)",
    suite: "I18N-DYNAMIC-PRESENTATION",
    producer: "/src/features/identity/presentation/accountFeedback.ts",
  },
  {
    path: "src/features/identity/ui/components/AccountDirectory.tsx",
    call: "t(rolePresentationFor(record.roleId).labelKey)",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/presentation/rolePresentation.ts",
  },
  {
    path: "src/features/identity/ui/components/AccountDirectory.tsx",
    call: "t(statusRestriction)",
    suite: "I18N-ACCOUNT-STATUS-RESTRICTION",
    producer: "/src/features/identity/presentation/accountStatusPresentation.ts",
  },
  {
    path: "src/features/identity/ui/components/AccountFields.tsx",
    call: "t(role.labelKey)",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/presentation/rolePresentation.ts",
  },
  {
    path: "src/features/identity/ui/components/RoleEditor.tsx",
    call: "t(role.labelKey)",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/presentation/rolePresentation.ts",
  },
  {
    path: "src/features/identity/ui/components/RoleEditor.tsx",
    call: "t(role.descriptionKey)",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/presentation/rolePresentation.ts",
  },
  {
    path: "src/features/identity/ui/components/RoleEditor.tsx",
    call: "t(restrictionCopy)",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/presentation/rolePresentation.ts",
  },
  {
    path: "src/features/identity/ui/RoleManagementPage.tsx",
    call: "t(roleTargetFallbackCopy(snapshot.detail))",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/presentation/rolePresentation.ts",
  },
  {
    path: "src/features/identity/ui/setup/SetupStorageStep.tsx",
    call: "t(database.descriptionKey)",
    suite: "I18N-DYNAMIC-IDENTITY",
    producer: "/src/features/identity/presentation/setupPresentation.ts",
  },
  {
    path: "src/features/realtime/ui/LiveMonitoringPage.tsx",
    call: "t(readCopy.error)",
    suite: "I18N-DYNAMIC-PRESENTATION",
    producer: "/src/features/realtime/presentation/realtimeReadCopy.ts",
  },
  {
    path: "src/features/realtime/ui/LiveMonitoringPage.tsx",
    call: "t(readCopy.stale)",
    suite: "I18N-DYNAMIC-PRESENTATION",
    producer: "/src/features/realtime/presentation/realtimeReadCopy.ts",
  },
  {
    path: "src/features/rules/i18n/useRuleCopy.ts",
    call: "t(key)",
    suite: "I18N-DYNAMIC-RULE-COPY",
    producer: "/src/features/rules/i18n/useRuleCopy.ts",
  },
  {
    path: "src/features/rules/ui/RulePublicationPanel.tsx",
    call: "t(labelKey)",
    suite: "I18N-DYNAMIC-DEPLOYMENT-PRESENTATION",
    producer: "/src/features/rules/presentation/deploymentLabels.ts",
  },
  {
    path: "src/features/system/ui/WorkerProtocolObservationList.tsx",
    call: "t(titleKey)",
    suite: "SYSTEM-PROTOCOL-WORKERS",
    producer: "/src/features/system/ui/ObservedProtocolsPanel.tsx",
    testFile: "tests/verification/worker-protocol-observation-mounted.test.mjs",
  },
  {
    path: "src/features/system/ui/WorkerProtocolObservationList.tsx",
    call: "t(emptyKey)",
    suite: "SYSTEM-PROTOCOL-WORKERS",
    producer: "/src/features/system/ui/ObservedProtocolsPanel.tsx",
    testFile: "tests/verification/worker-protocol-observation-mounted.test.mjs",
  },
];

const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

test("I18N-DYNAMIC-CALLSITE-COVERAGE: every AST-unresolved callsite has a named producer runtime test", () => {
  const audit = spawnSync(process.execPath, ["tests/i18n/keycheck.mjs"], { encoding: "utf8" });
  const output = `${audit.stdout}${audit.stderr}`;
  assert.equal(audit.status, 0, output);
  const actual = [...audit.stdout.matchAll(/^\s*· (src\/[^\s]+)\s{2,}(t\(.*\))$/gm)].map(
    ([, path, call]) => [path, call],
  );
  const expected = dynamicCallsites.map(({ path, call }) => [path, call]);
  assert.deepEqual(
    actual.sort(([leftPath, leftCall], [rightPath, rightCall]) =>
      `${leftPath}\0${leftCall}`.localeCompare(`${rightPath}\0${rightCall}`),
    ),
    expected.sort(([leftPath, leftCall], [rightPath, rightCall]) =>
      `${leftPath}\0${leftCall}`.localeCompare(`${rightPath}\0${rightCall}`),
    ),
    "update the explicit callsite-to-producer-runtime-test mapping when dynamic calls change",
  );
  for (const { path, call, suite, producer, testFile } of dynamicCallsites) {
    const runtimeTests = readFileSync(testFile ?? "tests/i18n/catalog.test.mjs", "utf8");
    const suiteStart = runtimeTests.indexOf(`test(\"${suite}:`);
    assert.notEqual(suiteStart, -1, `${path} ${call} must have runtime suite ${suite}`);
    const nextSuite = runtimeTests.indexOf('\ntest("', suiteStart + 1);
    const suiteBody = runtimeTests.slice(suiteStart, nextSuite === -1 ? undefined : nextSuite);
    assert.ok(
      new RegExp(`ssrLoadModule\\s*\\(\\s*[\"']${escapeRegExp(producer)}[\"']\\s*,?\\s*\\)`).test(
        suiteBody,
      ),
      `${path} ${call} must be covered by ${suite}, which must load ${producer} through Vite`,
    );
  }
});
