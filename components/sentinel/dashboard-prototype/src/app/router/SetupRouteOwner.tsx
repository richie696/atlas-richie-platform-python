import { useMemo } from "react";
import { useConsoleServices } from "../providers/ConsoleServicesProvider";
import { useAuthentication } from "../../features/identity/authentication";
import { createSetupIdentityPorts } from "../api/setupIdentityPorts";
import { createBootstrapAuthorizationWorkflow } from "../../features/identity/bootstrapAuthorization";
import {
  createBootstrapAuthorizationHttp,
  createInitializationHttp,
} from "../../features/identity/setupHttp";
import { createInitializationWorkflow } from "../../features/identity/initialization";
import {
  BootstrapAuthorizationGate,
  InitializationPage,
} from "../../features/identity/initialization";
import { ROUTE } from "./route.constants";
import type { DashboardPageProps } from "../../shared/types/dashboard";
import { useOwnedDisposal } from "../../shared/state/useOwnedDisposal";

const newRequestKey = () => crypto.randomUUID();

/** Assemble one-use bootstrap authorization and initialization around the shared Console transport. */
export function SetupRouteOwner({ navigate }: DashboardPageProps) {
  const { transport } = useConsoleServices();
  const { workflow: authentication } = useAuthentication();
  const owners = useMemo(() => {
    const ports = createSetupIdentityPorts(
      authentication,
      createBootstrapAuthorizationHttp(transport),
      createInitializationHttp(transport),
    );
    return Object.freeze({
      authorization: createBootstrapAuthorizationWorkflow(ports.authorization),
      initialization: createInitializationWorkflow(ports.initialization, newRequestKey),
    });
  }, [authentication, transport]);
  const { authorization, initialization } = owners;
  useOwnedDisposal(authorization);
  useOwnedDisposal(initialization);
  return (
    <BootstrapAuthorizationGate workflow={authorization}>
      <InitializationPage
        workflow={initialization}
        onCompleted={() => navigate(ROUTE.Login, {}, { history: "replace" })}
      />
    </BootstrapAuthorizationGate>
  );
}
