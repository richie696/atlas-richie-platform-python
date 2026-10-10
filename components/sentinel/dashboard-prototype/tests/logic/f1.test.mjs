import assert from "node:assert/strict";
import { test } from "node:test";
import { TIME_RANGE, TIME_RANGE_MS } from "@/shared/types/navigation";
import { RULE_OPTION_VALUES } from "../../src/features/rules/model/ruleOptions";
import { localizedOptions } from "../../src/features/rules/i18n/localizedOptions";
import {
  isRuleKind,
  resolveRuleKindFilter,
  RULE_KIND_ALL,
} from "../../src/features/rules/model/ruleKinds";
import { IDENTITY_ROLES, isIdentityRoleId } from "../../src/features/identity/model/account";
import { ROLE_OPTIONS } from "../../src/features/identity/presentation/rolePresentation";
import {
  CONTROL_PLANE_DATABASES,
  RULE_SOURCES,
  RULE_SOURCE_AUTHENTICATION_MODES,
  SETUP_STEPS,
} from "../../src/features/identity/model/setup";
import {
  SETUP_DATABASE_OPTIONS,
  RULE_SOURCE_OPTIONS,
  RULE_SOURCE_AUTHENTICATION_OPTIONS,
  INITIALIZATION_STEPS,
} from "../../src/features/identity/presentation/setupPresentation";

test("F1 shared observation window has one owner and the alias resolves in tools", () => {
  assert.equal(TIME_RANGE_MS[TIME_RANGE.Last15Minutes], 900000);
  assert.equal(TIME_RANGE_MS[TIME_RANGE.Last1Hour], 3600000);
});

test("F1 identity presentation is exhaustive but never owns domain permissions or storage defaults", () => {
  assert.deepEqual(
    ROLE_OPTIONS.map(({ id, permissions }) => ({ id, permissions })),
    IDENTITY_ROLES,
  );
  assert.ok(IDENTITY_ROLES.every((role) => !("labelKey" in role)));
  assert.deepEqual(
    SETUP_DATABASE_OPTIONS.map(({ id, defaultPort, requiresNetworkConfiguration, usage }) => ({
      id,
      defaultPort,
      requiresNetworkConfiguration,
      usage,
    })),
    CONTROL_PLANE_DATABASES,
  );
  assert.ok(
    CONTROL_PLANE_DATABASES.every(
      (database) => !("label" in database) && !("descriptionKey" in database),
    ),
  );
  assert.deepEqual(
    RULE_SOURCE_OPTIONS.map((option) => option.id),
    RULE_SOURCES,
  );
  assert.deepEqual(
    RULE_SOURCE_AUTHENTICATION_OPTIONS.map((option) => option.id),
    RULE_SOURCE_AUTHENTICATION_MODES,
  );
  assert.deepEqual(
    INITIALIZATION_STEPS.map((step) => step.id),
    SETUP_STEPS,
  );
});

test("F1 translating choices cannot mutate numeric protocol values or accept missing labels", () => {
  const copy = Object.fromEntries(
    Object.entries(RULE_OPTION_VALUES).map(([group, values]) => [
      group,
      values.map((value) => `label-${value}`),
    ]),
  );
  for (const group of Object.keys(RULE_OPTION_VALUES)) {
    assert.deepEqual(
      localizedOptions(group, copy).map((option) => option.value),
      RULE_OPTION_VALUES[group],
    );
    assert.throws(() => localizedOptions(group, { ...copy, [group]: [] }), /protocol values/);
  }
});

test("F3 rule choices match current capabilities instead of offering bare codes or a rejected hotspot mode", () => {
  assert.deepEqual(RULE_OPTION_VALUES.paramGrade, [1]);
  assert.deepEqual(RULE_OPTION_VALUES.clusterThreshold, [0, 1]);
  assert.ok(Object.isFrozen(RULE_OPTION_VALUES.paramGrade));
  assert.ok(Object.isFrozen(RULE_OPTION_VALUES.clusterThreshold));
});

test("F1 rules reject inherited and unknown URL kinds without vendor adapters", () => {
  for (const invalid of ["", "missing", "toString", "constructor", "__proto__"]) {
    assert.equal(resolveRuleKindFilter(invalid), RULE_KIND_ALL);
    assert.equal(isRuleKind(invalid), false);
  }
  for (const kind of ["flow", "degrade", "system", "authority", "param"]) {
    assert.equal(resolveRuleKindFilter(kind), kind);
    assert.equal(isRuleKind(kind), true);
  }
  assert.equal(isRuleKind(null), false);
});
test("F1 role IDs are narrowed only from the declared role catalog", () => {
  assert.equal(isIdentityRoleId("admin"), true);
  assert.equal(isIdentityRoleId("view"), true);
  assert.equal(isIdentityRoleId("owner"), false);
});
