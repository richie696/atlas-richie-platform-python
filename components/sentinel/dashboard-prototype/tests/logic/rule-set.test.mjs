import { test } from "node:test";
import assert from "node:assert/strict";
import {
  beginRuleSetEditing,
  addRuleToSet,
  updateRuleInSet,
  removeRuleFromSet,
  prepareRuleSetCandidate,
  ruleSetIsDirty,
} from "../../src/features/rules/editor/ruleSetEditing";
import {
  materializeRuleDraft,
  editableRule,
} from "../../src/features/rules/editor/ruleMaterialization";
import { validRuleSetSnapshot } from "../../src/features/rules/model/ruleSet";
import { RULE_KIND, SentinelCode } from "../../src/features/rules/model/ruleKinds";
import { ruleSet, flowValue } from "../fixtures/ruleSets";
test("RULESET-CANDIDATE: a single edit preserves all other records, baseline/revision and server identities", () => {
  const session = beginRuleSetEditing(ruleSet);
  assert.equal(ruleSetIsDirty(session), false);
  const first = session.records[0].rule;
  const changed = updateRuleInSet(session, "rule-one", {
    ...first,
    draft: { ...first.draft, count: "30" },
  });
  assert.equal(ruleSetIsDirty(changed), true);
  const prepared = prepareRuleSetCandidate(changed);
  assert.equal(prepared.valid, true);
  assert.equal(prepared.candidate.rules.length, 2);
  assert.deepEqual(prepared.candidate.rules[1], {
    recordId: "rule-two",
    rule: ruleSet.records[1].rule,
  });
  assert.equal(prepared.candidate.rules[0].rule.value.count, 30);
  assert.equal(prepared.candidate.baseVersionId, ruleSet.versionId);
  assert.equal(prepared.candidate.sourceRevision, ruleSet.sourceRevision);
  assert.equal(ruleSet.records[0].rule.value.count, 20);
  assert.equal(
    ruleSetIsDirty(
      updateRuleInSet(session, "rule-one", { ...first, draft: { ...first.draft, count: "20.0" } }),
    ),
    false,
  );
});
test("RULESET-INSERT-DELETE: local form keys do not become management ids; an empty full set is explicit", () => {
  let editing = beginRuleSetEditing(ruleSet);
  const draft = editableRule(
    { kind: RULE_KIND.Flow, value: { ...flowValue, resource: "GET /new" } },
    (i) => String(i),
  );
  editing = addRuleToSet(editing, "local-new", draft);
  const candidate = prepareRuleSetCandidate(editing);
  assert.equal(candidate.candidate.rules[2].recordId, null);
  assert.ok(!JSON.stringify(candidate.candidate).includes("local-new"));
  assert.throws(() => addRuleToSet(editing, "local-new", draft));
  assert.throws(() => updateRuleInSet(editing, "missing", draft));
  assert.throws(() => removeRuleFromSet(editing, "missing"));
  for (const row of editing.records) editing = removeRuleFromSet(editing, row.formKey);
  assert.deepEqual(prepareRuleSetCandidate(editing).candidate.rules, []);
  assert.equal(ruleSetIsDirty(editing), true);
  assert.equal(ruleSet.records.length, 2);
});
test("RULESET-MATERIALIZE: only validated active fields are numeric; stale conditional values and form keys are absent", () => {
  const flow = {
    kind: RULE_KIND.Flow,
    draft: {
      ...flowValue,
      count: "12",
      refResource: "unused",
      warmUpPeriodSec: "",
      maxQueueingTimeMs: Infinity,
      clusterConfig: {
        thresholdType: 0,
        sampleCount: "",
        windowIntervalMs: "",
        fallbackToLocalWhenFail: true,
      },
    },
  };
  const result = materializeRuleDraft(flow);
  assert.equal(result.valid, true);
  assert.equal(result.rule.value.count, 12);
  for (const field of ["refResource", "warmUpPeriodSec", "maxQueueingTimeMs", "clusterConfig"])
    assert.ok(!(field in result.rule.value));
  assert.equal(
    materializeRuleDraft({
      ...flow,
      draft: { ...flow.draft, controlBehavior: SentinelCode.FLOW_BEHAVIOR_QUEUEING },
    }).valid,
    false,
  );
  const param = {
    kind: RULE_KIND.ParamFlow,
    draft: {
      resource: "param",
      grade: 1,
      count: "2",
      durationInSec: "1",
      paramIdx: "0",
      paramFlowItemList: [
        { formKey: "local", classType: "java.lang.String", object: "x", count: "3" },
      ],
    },
  };
  const mapped = materializeRuleDraft(param);
  assert.equal(mapped.valid, true);
  assert.deepEqual(mapped.rule.value.paramFlowItemList, [
    { classType: "java.lang.String", object: "x", count: 3 },
  ]);
  assert.ok(!JSON.stringify(mapped).includes("formKey"));
});
test("RULESET-IDENTITY: resources stay literal; only documented authority list/class type normalization applies", () => {
  const resource = " POST /orders ";
  assert.equal(
    materializeRuleDraft({ kind: RULE_KIND.Flow, draft: { ...flowValue, resource } }).rule.value
      .resource,
    resource,
  );
  const authority = {
    kind: RULE_KIND.Authority,
    draft: { resource, limitApp: " origin-one , origin-two ", strategy: 0 },
  };
  assert.equal(materializeRuleDraft(authority).rule.value.limitApp, "origin-one,origin-two");
  assert.equal(
    materializeRuleDraft({
      ...authority,
      draft: { ...authority.draft, limitApp: "origin-one, origin-one" },
    }).valid,
    false,
  );
  const param = {
    kind: RULE_KIND.ParamFlow,
    draft: {
      resource,
      grade: 1,
      count: 2,
      durationInSec: 1,
      paramIdx: 0,
      paramFlowItemList: [
        { formKey: "one", classType: " java.lang.String ", object: " x ", count: 2 },
        { formKey: "two", classType: "java.lang.String", object: " x ", count: 3 },
      ],
    },
  };
  assert.equal(materializeRuleDraft(param).valid, false);
});
test("RULESET-BOUNDARY: invalid full candidate cannot be previewed as validated or hide the failing rule", () => {
  const original = beginRuleSetEditing(ruleSet);
  const edited = updateRuleInSet(original, "rule-two", {
    ...original.records[1].rule,
    draft: { ...original.records[1].rule.draft, count: "" },
  });
  const candidate = prepareRuleSetCandidate(edited);
  assert.equal(candidate.valid, false);
  assert.equal(candidate.issues[0].formKey, "rule-two");
  assert.equal(candidate.issues[0].issue.path, "count");
  assert.equal(ruleSetIsDirty(edited), true);
  assert.equal(validRuleSetSnapshot(ruleSet, "binding-one"), true);
  assert.equal(validRuleSetSnapshot(ruleSet, "missing"), false);
  assert.equal(
    validRuleSetSnapshot(
      { ...ruleSet, records: [ruleSet.records[0], ruleSet.records[0]] },
      "binding-one",
    ),
    false,
  );
  assert.equal(
    validRuleSetSnapshot(
      { ...ruleSet, binding: { ...ruleSet.binding, kind: RULE_KIND.System } },
      "binding-one",
    ),
    false,
  );
});
test("RULESET-STRUCTURE: duplicate local/server identity, foreign record and wrong category cannot bypass action guards", () => {
  const editing = beginRuleSetEditing(ruleSet);
  const first = editing.records[0],
    second = editing.records[1];
  for (const records of [
    [first, { ...second, formKey: first.formKey }],
    [first, { ...second, recordId: first.recordId }],
    [first, { ...second, recordId: "foreign-record" }],
    [
      first,
      {
        ...second,
        rule: {
          kind: RULE_KIND.Authority,
          draft: { resource: "orders", limitApp: "origin", strategy: 0 },
        },
      },
    ],
    [{ ...first, formKey: "" }],
  ])
    assert.equal(prepareRuleSetCandidate({ ...editing, records }).valid, false);
});
