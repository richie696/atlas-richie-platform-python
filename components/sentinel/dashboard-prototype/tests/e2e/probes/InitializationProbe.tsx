import { useMemo, useState } from "react";
import { AppError, AppErrorKind } from "@richie696/react-framework";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import {
  createInitializationWorkflow,
  InitializationPage,
} from "../../../src/features/identity/initialization";

/** Mutable transport state belongs to this test effect owner, not React props. */
function createInitializationTopology(alreadyInitialized: boolean) {
  const control = {
    initialized: alreadyInitialized,
    fail: "none" as "none" | "timeout" | "validation",
    hold: false,
    releases: [] as (() => void)[],
    writes: 0,
    checks: 0,
    lookups: 0,
    requestKey: "",
  };
  const workflow = createInitializationWorkflow(
    {
      readBootstrap: async (signal) => {
        signal.throwIfAborted();
        return control.initialized
          ? { initialized: true }
          : { initialized: false, setupAvailable: true, operatorAuthorized: true };
      },
      checkDatabase: async () => {
        control.checks++;
        return { status: "reachable" };
      },
      checkSource: async () => {
        control.checks++;
        return { status: "reachable" };
      },
      initialize: async (request, signal) => {
        control.writes++;
        control.requestKey = request.requestKey;
        if (control.hold) await new Promise<void>((resolve) => control.releases.push(resolve));
        signal.throwIfAborted();
        if (control.fail === "validation")
          throw new AppError(AppErrorKind.PROTOCOL, "PRIVATE-INIT-ERROR", { status: 422 });
        control.initialized = true;
        if (control.fail === "timeout")
          throw new AppError(AppErrorKind.TIMEOUT, "PRIVATE-INIT-ERROR");
        return {
          status: "completed",
          requestKey: request.requestKey,
          operationId: "probe-operation",
        };
      },
      readInitialization: async (requestKey) => {
        control.lookups++;
        return { status: "completed", requestKey, operationId: "probe-operation" };
      },
    },
    () => "probe-request-" + (control.writes + 1),
  );
  return Object.freeze({
    workflow,
    readCounts: () => ({
      writes: control.writes,
      checks: control.checks,
      lookups: control.lookups,
    }),
    setFailure: (fail: typeof control.fail) => {
      control.fail = fail;
    },
    setInitialized: (initialized: boolean) => {
      control.initialized = initialized;
    },
    hold: () => {
      control.hold = true;
    },
    release: () => {
      control.hold = false;
      control.releases.splice(0).forEach((release) => release());
    },
  });
}
/** Test-only effect double. The actual page, wizard, workflow and primitive controls run unchanged. */
export function InitializationProbe({
  alreadyInitialized = false,
}: {
  readonly alreadyInitialized?: boolean;
}) {
  const [completions, setCompletions] = useState(0);
  const topology = useMemo(
    () => createInitializationTopology(alreadyInitialized),
    [alreadyInitialized],
  );
  const { workflow } = topology;
  const snapshot = useExternalSnapshot(workflow);
  return (
    <AstryxProvider>
      <aside>
        <button
          data-hold
          onClick={() => {
            topology.hold();
          }}
        >
          Hold request
        </button>
        <button
          data-release
          onClick={() => {
            topology.release();
          }}
        >
          Release request
        </button>
        <button
          data-timeout
          onClick={() => {
            topology.setFailure("timeout");
          }}
        >
          Simulate timeout after commit
        </button>
        <button
          data-validation
          onClick={() => {
            topology.setFailure("validation");
          }}
        >
          Reject validation
        </button>
        <button
          data-close-externally
          onClick={() => {
            topology.setInitialized(true);
            void workflow.restore(true);
          }}
        >
          Close setup from another initializer
        </button>
        <button
          data-reopen-after-close
          onClick={() => {
            topology.setInitialized(false);
            void workflow.restore(true);
          }}
        >
          Reopen setup for secret-clearing assertion
        </button>
        <output data-probe-summary>
          {JSON.stringify({
            status: snapshot.initialization.status,
            ...topology.readCounts(),
            completions,
          })}
        </output>
      </aside>
      <InitializationPage
        workflow={workflow}
        onCompleted={() => setCompletions((current) => current + 1)}
      />
    </AstryxProvider>
  );
}
