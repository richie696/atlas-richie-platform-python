import { useCallback, useMemo, useState } from "react";
import { useAuthentication } from "../../features/identity/authentication";
import {
  AccountsPage,
  RoleManagementPage,
  type AccountListQuery,
} from "../../features/identity/management";
import { createAccountManagementWorkflow } from "../../features/identity/management";
import { createAccountManagementHttp } from "../../features/identity/managementHttp";
import { useConsoleServices } from "../providers/ConsoleServicesProvider";
import {
  SystemObservationContainer,
  createMonitoringSourceHttp,
  createSourceRegistrationHttp,
  createSystemObservationHttp,
  createSystemSettingsHttp,
} from "../../features/system";
import { SYSTEM_TAB } from "../../features/system";
import { ROUTE } from "./route.constants";
import type { RoutePageContext } from "./routes";
import { FeedbackPanel } from "../../shared/ui/FeedbackPanel";
import { useTranslation } from "react-i18next";
import { useOwnedDisposal } from "../../shared/state/useOwnedDisposal";

const EMPTY_DIRECTORY: AccountListQuery = Object.freeze({ page: 1, pageSize: 20, search: "" });
const newRequestKey = () => crypto.randomUUID();

/** App owner joining system observations and the existing session-bound identity workflows. */
export function ConsoleSystemRoute(props: RoutePageContext) {
  const { navigate } = props;
  const { t } = useTranslation();
  const services = useConsoleServices();
  const observationPorts = useMemo(
    () => createSystemObservationHttp(services.transport),
    [services.transport],
  );
  const sourceRegistrationPort = useMemo(
    () => createSourceRegistrationHttp(services.transport),
    [services.transport],
  );
  const monitoringSourcePort = useMemo(
    () => createMonitoringSourceHttp(services.transport),
    [services.transport],
  );
  const systemSettingsPort = useMemo(
    () => createSystemSettingsHttp(services.transport),
    [services.transport],
  );
  const { workflow: authentication, snapshot } = useAuthentication();
  const identity =
    snapshot.access.phase === "resolved" && snapshot.access.facts.kind === "authenticated"
      ? snapshot.access.facts.identity
      : null;
  const [query, setQuery] = useState(EMPTY_DIRECTORY);
  const onOwnPasswordReset = useCallback(() => {
    authentication.expire();
    navigate(ROUTE.Login, {}, { history: "replace" });
  }, [authentication, navigate]);
  const workflow = useMemo(
    () =>
      identity
        ? createAccountManagementWorkflow(
            createAccountManagementHttp(services.transport),
            identity,
            services.session,
            newRequestKey,
          )
        : null,
    [identity, services],
  );
  useOwnedDisposal(workflow);

  if (!workflow || !identity)
    return <FeedbackPanel isBusy copy={{ title: t("shell.route.loading"), description: "" }} />;

  const identityPanels = {
    accounts: (
      <AccountsPage
        workflow={workflow}
        query={query}
        onQueryChange={setQuery}
        onBindRole={(accountId) =>
          props.navigate(ROUTE.System, { view: SYSTEM_TAB.Roles, accountId })
        }
        onOwnPasswordReset={onOwnPasswordReset}
      />
    ),
    roles: (
      <RoleManagementPage
        workflow={workflow}
        accountId={props.accountId || undefined}
        sessionEpoch={identity.sessionEpoch}
        onAccountSelection={(accountId) =>
          props.navigate(ROUTE.System, { view: SYSTEM_TAB.Roles, accountId })
        }
        onBack={() => props.navigate(ROUTE.System, { view: SYSTEM_TAB.Accounts })}
      />
    ),
  };
  return (
    <SystemObservationContainer
      {...props}
      observationPorts={observationPorts}
      sourceRegistrationPort={sourceRegistrationPort}
      systemSettingsPort={systemSettingsPort}
      monitoringSourcePort={monitoringSourcePort}
      principal={{ roleId: identity.roleId, sessionEpoch: identity.sessionEpoch }}
      access={snapshot.access}
      identityPanels={identityPanels}
      demoMode={services.mode === "mock"}
    />
  );
}
