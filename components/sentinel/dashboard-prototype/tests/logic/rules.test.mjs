import assert from "node:assert/strict";
import { test } from "node:test";
import { RULE_KIND, SentinelCode } from "../../src/features/rules/model/ruleKinds";
import { RULE_FIXTURES } from "../fixtures/ruleWorkbenchFixtures";
import { draftFromEntry } from "../../src/features/rules/editor/ruleEntry";
import {
  createDraftSession,
  resolveDraftSession,
  editDraftSession,
} from "../../src/features/rules/editor/ruleEditing";
import { validateRuleDraft } from "../../src/features/rules/editor/rulePolicy";
import { validRuleValue } from "../../src/features/rules/model/ruleValue";
import { ruleDraftPreview } from "../../src/features/rules/presentation/ruleDraftPreview";

const fixture = (kind) => {
  const entry = RULE_FIXTURES.find((entry) => entry.ruleType === kind);
  assert.ok(entry);
  return draftFromEntry(entry);
};
const paths = (rule) => validateRuleDraft(rule).map((issue) => issue.path);

test("F1.6 domain rule facts validate without depending on editable form drafts", () => {
  for (const entry of RULE_FIXTURES)
    assert.equal(validRuleValue({ kind: entry.ruleType, value: entry.sentinelRule }), true);
  const flow = RULE_FIXTURES.find((entry) => entry.ruleType === RULE_KIND.Flow);
  assert.equal(
    validRuleValue({ kind: flow.ruleType, value: { ...flow.sentinelRule, count: NaN } }),
    false,
  );
  assert.equal(
    validRuleValue({ kind: flow.ruleType, value: { ...flow.sentinelRule, count: "12" } }),
    false,
  );
});

test("rule drafting preserves all five category shapes but never aliases the baseline", () => {
  for (const entry of RULE_FIXTURES) {
    const result = draftFromEntry(entry);
    assert.equal(result.kind, entry.ruleType);
    assert.deepEqual(ruleDraftPreview(result), entry.sentinelRule);
    assert.notEqual(result.draft, entry.sentinelRule);
    assert.deepEqual(paths(result), []);
  }
  const param = fixture(RULE_KIND.ParamFlow);
  assert.ok(param.draft.paramFlowItemList.every((item) => item.formKey));
  assert.ok(!JSON.stringify(ruleDraftPreview(param)).includes("formKey"));
});

test("rule session resolves a changed target before rendering and cannot patch a different category", () => {
  const flow = RULE_FIXTURES.find((entry) => entry.ruleType === RULE_KIND.Flow);
  const degrade = RULE_FIXTURES.find((entry) => entry.ruleType === RULE_KIND.Degrade);
  const session = createDraftSession(flow);
  const editing = editDraftSession(session, {
    ...session.rule,
    draft: { ...session.rule.draft, count: 12 },
  });
  assert.equal(resolveDraftSession(flow, editing), editing);
  const switched = resolveDraftSession(degrade, editing);
  assert.equal(switched.rule.kind, RULE_KIND.Degrade);
  assert.equal(switched.editing, false);
  assert.equal(resolveDraftSession(null, editing), null);
  assert.throws(() => editDraftSession(session, fixture(RULE_KIND.Degrade)), /category/);
  const refreshed = { ...flow, sentinelRule: { ...flow.sentinelRule, count: 18 } };
  assert.equal(resolveDraftSession(refreshed, editing).rule.draft.count, 18);
  assert.equal(flow.sentinelRule.count, 2000);
});

test("numeric rule fields reject empty, blank, non-finite, boolean and malformed values", () => {
  const base = fixture(RULE_KIND.Flow);
  for (const count of ["", " ", "Infinity", Infinity, -Infinity, NaN, null, true, "bad", -1, 0]) {
    assert.ok(paths({ ...base, draft: { ...base.draft, count } }).includes("count"), String(count));
  }
  for (const count of [1, 1.5, "1.5"])
    assert.deepEqual(paths({ ...base, draft: { ...base.draft, count } }), []);
  assert.ok(
    paths({
      ...base,
      draft: { ...base.draft, grade: -1, strategy: 30, controlBehavior: 100 },
    }).includes("grade"),
  );
  assert.ok(
    paths({
      ...base,
      draft: { ...base.draft, grade: SentinelCode.FLOW_GRADE_THREAD, count: 1.5 },
    }).includes("count"),
  );
});

test("conditional flow fields are validated only when active and cluster windows must divide exactly", () => {
  const base = fixture(RULE_KIND.Flow);
  assert.deepEqual(
    paths({ ...base, draft: { ...base.draft, warmUpPeriodSec: "", maxQueueingTimeMs: "" } }),
    [],
  );
  assert.ok(
    paths({
      ...base,
      draft: { ...base.draft, strategy: SentinelCode.FLOW_STRATEGY_CHAIN },
    }).includes("refResource"),
  );
  assert.ok(
    paths({
      ...base,
      draft: {
        ...base.draft,
        controlBehavior: SentinelCode.FLOW_BEHAVIOR_WARM_UP,
        warmUpPeriodSec: 0,
      },
    }).includes("warmUpPeriodSec"),
  );
  assert.ok(
    paths({ ...base, draft: { ...base.draft, clusterMode: true } }).includes("clusterConfig"),
  );
  const clusterConfig = {
    thresholdType: 0,
    fallbackToLocalWhenFail: true,
    sampleCount: 3,
    windowIntervalMs: 1000,
  };
  assert.ok(
    paths({ ...base, draft: { ...base.draft, clusterMode: true, clusterConfig } }).includes(
      "clusterConfig.windowIntervalMs",
    ),
  );
  assert.deepEqual(
    paths({
      ...base,
      draft: {
        ...base.draft,
        clusterMode: true,
        clusterConfig: { ...clusterConfig, sampleCount: 10 },
      },
    }),
    [],
  );
});

test("circuit limits distinguish ratios, counts and positive integer windows", () => {
  const base = fixture(RULE_KIND.Degrade);
  for (const slowRatioThreshold of [0, 1.1, "", NaN])
    assert.ok(
      paths({ ...base, draft: { ...base.draft, slowRatioThreshold } }).includes(
        "slowRatioThreshold",
      ),
    );
  assert.ok(
    paths({
      ...base,
      draft: { ...base.draft, grade: SentinelCode.DEGRADE_ERROR_RATIO, count: 1.1 },
    }).includes("count"),
  );
  assert.ok(
    paths({
      ...base,
      draft: { ...base.draft, grade: SentinelCode.DEGRADE_ERROR_COUNT, count: 1.1 },
    }).includes("count"),
  );
  for (const field of ["timeWindow", "minRequestAmount", "statIntervalMs"])
    assert.ok(paths({ ...base, draft: { ...base.draft, [field]: 1.5 } }).includes(field));
});

test("system disabled sentinel is not blank-as-zero, and CPU and concurrency preserve units", () => {
  const base = fixture(RULE_KIND.System);
  const disabled = Object.fromEntries(Object.keys(base.draft).map((key) => [key, -1]));
  assert.ok(paths({ ...base, draft: disabled }).includes("systemThresholds"));
  for (const highestCpuUsage of ["", -2, 1.1, Infinity])
    assert.ok(
      paths({ ...base, draft: { ...base.draft, highestCpuUsage } }).includes("highestCpuUsage"),
    );
  assert.ok(paths({ ...base, draft: { ...base.draft, maxThread: 1.1 } }).includes("maxThread"));
  assert.deepEqual(paths({ ...base, draft: { ...disabled, highestCpuUsage: 0 } }), []);
});

test("authority origins and parameter exceptions validate structure without pretending to be a Java/Python codec", () => {
  const authority = fixture(RULE_KIND.Authority);
  assert.ok(
    paths({ ...authority, draft: { ...authority.draft, limitApp: "a,,b" } }).includes("limitApp"),
  );
  assert.ok(
    paths({ ...authority, draft: { ...authority.draft, strategy: 9 } }).includes("strategy"),
  );
  const param = fixture(RULE_KIND.ParamFlow);
  for (const paramIdx of ["", -1, 1.2, Infinity])
    assert.ok(paths({ ...param, draft: { ...param.draft, paramIdx } }).includes("paramIdx"));
  assert.ok(
    paths({ ...param, draft: { ...param.draft, grade: SentinelCode.FLOW_GRADE_THREAD } }).includes(
      "grade",
    ),
  );
  assert.ok(
    paths({ ...param, draft: { ...param.draft, durationInSec: 0 } }).includes("durationInSec"),
  );
  const invalid = { classType: "", object: "", count: Infinity };
  const issues = paths({ ...param, draft: { ...param.draft, paramFlowItemList: [invalid] } });
  for (const key of ["classType", "object", "count"])
    assert.ok(issues.includes(`paramFlowItemList.0.${key}`));
  const duplicate = param.draft.paramFlowItemList[0];
  assert.ok(
    paths({
      ...param,
      draft: { ...param.draft, paramFlowItemList: [duplicate, { ...duplicate }] },
    }).includes("paramFlowItemList.1.object"),
  );
});
