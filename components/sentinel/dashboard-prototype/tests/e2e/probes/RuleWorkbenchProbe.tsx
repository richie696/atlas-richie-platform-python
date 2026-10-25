import { useLayoutEffect } from "react";
import {
  useRuleWorkbench,
  type UseRuleWorkbenchOptions,
} from "../../../src/features/rules/state/useRuleWorkbench";
import type { RuleWorkbenchEntry } from "../../../src/features/rules/editor/ruleEntry";
import type { RuleKindFilter } from "../../../src/features/rules/model/ruleKinds";
import { RULE_KIND_ALL } from "../../../src/features/rules/model/ruleKinds";
import { TIME_RANGE } from "../../../src/shared/types/navigation";
import type { TypedRuleDraft } from "../../../src/features/rules/editor/ruleDraft";
export { RULE_FIXTURES } from "../../fixtures/ruleWorkbenchFixtures";

interface Commit {
  readonly selectedKind: string | null;
  readonly draftKind: string | null;
  readonly editing: boolean;
}

/** Actual Hook commits are observed before passive Effects, including StrictMode replay. */
export function RuleWorkbenchProbe({
  entries,
  kind = RULE_KIND_ALL,
  onCommit,
}: {
  readonly entries: readonly RuleWorkbenchEntry[];
  readonly kind?: RuleKindFilter;
  readonly onCommit: (commit: Commit) => void;
}) {
  const options: UseRuleWorkbenchOptions = {
    entries,
    appId: "all",
    range: TIME_RANGE.Last1Hour,
    setAppId: () => {},
    setRange: () => {},
    kindFilter: kind,
    onKindFilterChange: () => {},
  };
  const workbench = useRuleWorkbench(options);
  const { selected, draft, editing } = workbench;
  useLayoutEffect(() => {
    onCommit({ selectedKind: selected?.ruleType ?? null, draftKind: draft?.kind ?? null, editing });
  }, [selected, draft, editing, onCommit]);
  return (
    <>
      <output>
        {JSON.stringify({
          selectedKind: selected?.ruleType ?? null,
          draftKind: draft?.kind ?? null,
          editing,
        })}
      </output>
      <button onClick={workbench.beginEditing}>edit</button>
    </>
  );
}

/** Compile-time negative tests: category mismatch must not be accepted by the public internal types. */
function acceptsDraft(_draft: TypedRuleDraft): void {}
function acceptsEntry(_entry: RuleWorkbenchEntry): void {}
const systemFields = {
  qps: 1,
  avgRt: -1,
  highestSystemLoad: -1,
  highestCpuUsage: -1,
  maxThread: -1,
};
// @ts-expect-error A Flow category cannot carry System fields.
acceptsDraft({ kind: "flow", draft: systemFields });
// @ts-expect-error A catalog entry cannot hide an Authority payload under the Flow category.
acceptsEntry({
  id: "x",
  app: "x",
  ruleType: "flow",
  resource: "x",
  strategy: "x",
  threshold: "x",
  scope: "application",
  provider: "Nacos",
  version: "x",
  sentinelRule: { resource: "x", limitApp: "x", strategy: 0 },
});
