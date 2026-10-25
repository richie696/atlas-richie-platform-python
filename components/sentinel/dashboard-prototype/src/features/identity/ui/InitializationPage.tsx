import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { InitializationWorkflow } from "../application/initializationWorkflow";
import { prepareSetupDatabase, prepareSetupSource } from "../model/setupSubmission";
import { useSetupFlow } from "../state/useSetupFlow";
import { SetupWizard } from "./SetupWizard";
import { InitializationFeedback } from "./setup/InitializationFeedback";
import { INITIAL_SETUP_DRAFT } from "../model/setup";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
import { isSetupAuthorityClosed } from "../presentation/setupFeedback";
import type { SetupConnectionCheckTarget } from "../model/setup";

/**
 * Async first-run container. A stable injected owner governs effects; the wizard
 * owns only transient inputs. Completion clears secrets and notifies routing once,
 * after both operation and bootstrap confirmation. SetupRouteOwner in the app
 * assembly supplies the shared initialization workflow and route transition.
 */
export function InitializationPage({
  workflow,
  onCompleted,
}: {
  readonly workflow: InitializationWorkflow;
  readonly onCompleted: () => void;
}) {
  const invalidateConnectionCheck = useCallback(
    (target?: SetupConnectionCheckTarget) =>
      target ? workflow.invalidateCheck(target) : workflow.invalidateChecks(),
    [workflow],
  );
  const flow = useSetupFlow(invalidateConnectionCheck);
  const { clearSensitive } = flow;
  const snapshot = useExternalSnapshot(workflow);
  const unresolved = ["submitting", "checking", "pending", "result-unknown"].includes(
    snapshot.initialization.status,
  );
  const knownClosed = isSetupAuthorityClosed(snapshot);
  const finished = snapshot.initialization.status === "ready" || knownClosed;
  const bootstrapIsOpen =
    snapshot.bootstrap.status === "ready" &&
    !snapshot.bootstrap.data.initialized &&
    snapshot.bootstrap.data.setupAvailable &&
    snapshot.bootstrap.data.operatorAuthorized;
  useBeforeUnloadGuard(
    !finished && (flow.draft !== INITIAL_SETUP_DRAFT || unresolved),
    !finished && unresolved,
    clearSensitive,
  );
  const completedOwner = useRef<InitializationWorkflow | null>(null);
  const closedRefreshOwner = useRef<InitializationWorkflow | null>(null);
  useEffect(() => {
    void workflow.restore().catch(() => {});
    return () => workflow.cancel();
  }, [workflow]);
  useLayoutEffect(() => {
    if (finished) clearSensitive();
  }, [finished, clearSensitive]);
  useEffect(() => {
    if (bootstrapIsOpen) closedRefreshOwner.current = null;
    if (!knownClosed || closedRefreshOwner.current === workflow) return;
    closedRefreshOwner.current = workflow;
    // A closed-state refresh temporarily changes bootstrap to loading. Keep
    // this workflow marked as checked so that transient state cannot create a
    // refresh loop; a confirmed open bootstrap above resets the marker.
    void workflow.restore(true).catch(() => {});
  }, [workflow, knownClosed, bootstrapIsOpen]);
  useEffect(() => {
    if (snapshot.initialization.status !== "ready" || completedOwner.current === workflow) return;
    completedOwner.current = workflow;
    onCompleted();
  }, [workflow, snapshot.initialization.status, onCompleted]);
  const inspect = () => void workflow.inspect().catch(() => {});
  const restore = () => void workflow.restore(true).catch(() => {});
  const feedback = (
    <InitializationFeedback snapshot={snapshot} onInspect={inspect} onRestore={restore} />
  );
  const databaseChecking =
    snapshot.databaseCheck.status === "loading" || snapshot.databaseCheck.status === "refreshing";
  const sourceChecking =
    snapshot.sourceCheck.status === "loading" || snapshot.sourceCheck.status === "refreshing";
  const window = snapshot.bootstrap;
  const available =
    window.status === "ready" &&
    !window.data.initialized &&
    window.data.setupAvailable &&
    window.data.operatorAuthorized;
  if (finished || (!available && snapshot.initialization.status === "idle")) return feedback;
  const locked =
    ["submitting", "checking", "pending", "result-unknown", "ready", "closed"].includes(
      snapshot.initialization.status,
    ) || !available;
  const testDatabase = () => {
    const result = prepareSetupDatabase(flow.draft);
    if (result.status === "invalid") {
      flow.reportIssues(result.issues);
      return;
    }
    void workflow.checkDatabase(result.input).catch(() => {});
  };
  const testSource = () => {
    const result = prepareSetupSource(flow.draft);
    if (result.status === "invalid") {
      flow.reportIssues(result.issues);
      return;
    }
    void workflow.checkSource(result.input).catch(() => {});
  };
  return (
    <SetupWizard
      flow={flow}
      isLocked={locked}
      feedback={feedback}
      onTestDatabase={testDatabase}
      onTestSource={testSource}
      isDatabaseChecking={databaseChecking}
      isSourceChecking={sourceChecking}
      onFinish={() => {
        const input = flow.prepareSubmission();
        if (input) void workflow.initialize(input).catch(() => {});
      }}
    />
  );
}
