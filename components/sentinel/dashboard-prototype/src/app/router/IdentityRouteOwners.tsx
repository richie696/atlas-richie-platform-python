import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { DashboardPageProps } from "../../shared/types/dashboard";
import { useConsoleServices } from "../providers/ConsoleServicesProvider";
import { useAuthentication, type SessionIdentity } from "../../features/identity/authentication";
import {
  AccountsPage,
  RoleManagementPage,
  type AccountListQuery,
} from "../../features/identity/management";
import { createAccountManagementWorkflow } from "../../features/identity/management";
import {
  createAccountManagementHttp,
  createOwnPasswordHttp,
} from "../../features/identity/managementHttp";
import { createOwnPasswordWorkflow } from "../../features/identity/password";
import { OwnPasswordPage } from "../../features/identity/password";
import { LoginEntryPage } from "../../features/identity/login";
import { ActionButton } from "../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../shared/ui/FeedbackPanel";
import { ROUTE } from "./route.constants";
import { routeAfterAuthentication } from "./navigation";
import { useOwnedDisposal } from "../../shared/state/useOwnedDisposal";
import { useConsoleRuntime } from "../../core/api/runtime/ConsoleRuntimeProvider";
import { PublicLocaleControl } from "../shell/PublicLocaleControl";

const newRequestKey = () => crypto.randomUUID();
const EMPTY_DIRECTORY: AccountListQuery = Object.freeze({ page: 1, pageSize: 20, search: "" });

function useCurrentIdentity() {
  const { snapshot } = useAuthentication();
  return snapshot.access.phase === "resolved" && snapshot.access.facts.kind === "authenticated"
    ? snapshot.access.facts.identity
    : null;
}

/** Build and dispose an account owner for exactly the authenticated session epoch. */
export function ConsoleAccountsRoute({ navigate }: DashboardPageProps) {
  const { t } = useTranslation();
  const { workflow: authentication } = useAuthentication();
  const identity = useCurrentIdentity();
  const services = useConsoleServices();
  const [query, setQuery] = useState(EMPTY_DIRECTORY);
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
  const onOwnPasswordReset = useCallback(() => {
    authentication.expire();
    navigate(ROUTE.Login, {}, { history: "replace" });
  }, [authentication, navigate]);
  useOwnedDisposal(workflow);
  if (!workflow)
    return <FeedbackPanel isBusy copy={{ title: t("shell.route.loading"), description: "" }} />;
  return (
    <AccountsPage
      workflow={workflow}
      query={query}
      onQueryChange={setQuery}
      onBindRole={(accountId) => navigate(ROUTE.Roles, { accountId })}
      onOwnPasswordReset={onOwnPasswordReset}
    />
  );
}

/** Account directory and selected role editor share one session-bound owner. */
export function ConsoleRolesRoute({ navigate, accountId }: DashboardPageProps) {
  const { t } = useTranslation();
  const identity = useCurrentIdentity();
  const services = useConsoleServices();
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
  return (
    <RoleManagementPage
      workflow={workflow}
      accountId={accountId || undefined}
      sessionEpoch={identity.sessionEpoch}
      onAccountSelection={(nextId) => navigate(ROUTE.Roles, { accountId: nextId })}
      onBack={() => navigate(ROUTE.Accounts)}
    />
  );
}

/** Password mutation targets the confirmed principal, never an account from the URL. */
export function ConsoleOwnPasswordRoute({ navigate }: DashboardPageProps) {
  const { t } = useTranslation();
  const identity = useCurrentIdentity();
  const { workflow: authentication } = useAuthentication();
  const services = useConsoleServices();
  const workflow = useMemo(
    () =>
      identity
        ? createOwnPasswordWorkflow(
            createOwnPasswordHttp(services.transport),
            identity,
            services.session,
          )
        : null,
    [identity, services],
  );
  useOwnedDisposal(workflow);
  const reauthenticate = useCallback(() => {
    authentication.expire();
    navigate(ROUTE.Login, { returnTo: ROUTE.ChangePassword }, { history: "replace" });
  }, [authentication, navigate]);
  if (!workflow || !identity)
    return <FeedbackPanel isBusy copy={{ title: t("shell.route.loading"), description: "" }} />;
  return (
    <OwnPasswordPage
      workflow={workflow}
      identity={identity}
      onConfirmed={(receipt) => {
        if (receipt.sessionDisposition === "reauthenticate") reauthenticate();
      }}
      onReauthenticate={reauthenticate}
    />
  );
}

/** Real application login entry; only confirmed identity can leave the page. */
export function ConsoleLoginRoute({ navigate, returnTo }: DashboardPageProps) {
  const runtime = useConsoleRuntime();
  const authenticated = useCallback(
    (identity: SessionIdentity) =>
      navigate(
        routeAfterAuthentication(returnTo, identity),
        { returnTo: undefined },
        { history: "replace" },
      ),
    [navigate, returnTo],
  );
  const setupRequired = useCallback(
    () => navigate(ROUTE.Setup, {}, { history: "replace" }),
    [navigate],
  );
  return (
    <LoginEntryPage
      localeControl={<PublicLocaleControl />}
      onAuthenticated={authenticated}
      onSetupRequired={setupRequired}
      demoMode={runtime.mode === "mock"}
    />
  );
}

/** An explicit route-level denial used while no authenticated identity is available. */
export function IdentityRouteUnavailable({ retry }: { readonly retry: () => void }) {
  const { t } = useTranslation();
  return (
    <FeedbackPanel
      tone="error"
      copy={{ title: t("shell.route.failed"), description: t("shell.route.failureHelp") }}
      actions={<ActionButton onClick={retry}>{t("shell.feedback.retryRead")}</ActionButton>}
    />
  );
}
