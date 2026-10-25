import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import { NavigationBoundary } from "../../../src/app/router/NavigationBoundary";
import { useHashRoute } from "../../../src/app/router/useHashRoute";
import { useHashNavigationController } from "../../../src/app/router/HashNavigationContext";
import { ROUTE } from "../../../src/app/router/route.constants";
import { NAVIGATION_HISTORY } from "../../../src/shared/types/navigation";
import { RuleSetWorkbenchPage } from "../../../src/features/rules/workspace";
import { ruleSet } from "../../fixtures/ruleSets";
import { createRuleWorkspaceTopology } from "./RuleSetWorkspaceProbe";
const OPTIONS = { applicationScopeIds: ["orders"], defaultAccountId: "me" };
/** Real app history boundary and formal editor; synthetic rule Port is isolated acceptance input only. */
export function NavigationGuardProbe({
  topology,
}: {
  readonly topology: ReturnType<typeof createRuleWorkspaceTopology>;
}) {
  return (
    <AstryxProvider>
      <NavigationBoundary>
        <GuardConsumer topology={topology} />
      </NavigationBoundary>
    </AstryxProvider>
  );
}
function GuardConsumer({
  topology,
}: {
  readonly topology: ReturnType<typeof createRuleWorkspaceTopology>;
}) {
  const route = useHashRoute(OPTIONS),
    controller = useHashNavigationController()!,
    history = useExternalSnapshot(controller),
    editor = useExternalSnapshot(topology.workflow),
    counts = useExternalSnapshot(topology.counts);
  return (
    <>
      <div data-test-effects>
        <button data-guard-rules onClick={() => route.navigate(ROUTE.Rules)}>
          Rules
        </button>
        <button data-guard-next onClick={() => route.navigate(ROUTE.Realtime)}>
          Monitor
        </button>
        <button
          data-guard-replace
          onClick={() =>
            route.navigate(ROUTE.Accounts, {}, { history: NAVIGATION_HISTORY.Replace })
          }
        >
          Replace
        </button>
        <button data-guard-back onClick={() => window.history.back()}>
          Back
        </button>
        <button data-guard-forward onClick={() => window.history.forward()}>
          Forward
        </button>
        <button data-guard-unknown onClick={() => topology.setMode("unknown")}>
          Lose acknowledgement
        </button>
        <button data-guard-confirm onClick={() => topology.setLookup("completed")}>
          Confirm receipt
        </button>
        <button data-guard-pending onClick={() => topology.setLookup("pending")}>
          Pending receipt
        </button>
      </div>
      {route.route === ROUTE.Rules ? (
        <RuleSetWorkbenchPage
          workflow={topology.workflow}
          binding={ruleSet.binding}
          newFormKey={topology.newFormKey}
        />
      ) : (
        <p data-guard-destination>{route.route}</p>
      )}
      <output data-guard-summary style={{ display: "block", overflowWrap: "anywhere" }}>
        {JSON.stringify({
          route: route.route,
          hash: history.location.hash,
          index: history.location.index,
          prompt: history.prompt?.kind ?? null,
          historical: history.prompt?.historical ?? null,
          restoring: history.restoring,
          source: editor.source.status,
          dirty: editor.dirty,
          editing: !!editor.editing,
          value: editor.editing?.records[0]?.rule.draft,
          operation: editor.operation.command.status,
          inspecting: editor.operation.inspecting,
          writes: counts.writes,
          lookups: counts.lookups,
        })}
      </output>
    </>
  );
}
