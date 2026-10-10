import { AppShell } from "./shell/AppShell";
import { Header } from "./shell/Header";
import { StatusBanner } from "./shell/StatusBanner";
import { Footer } from "./shell/Footer";
import { accessFor, ROUTE } from "./router/route.constants";
import { RouteBoundary } from "./router/RouteBoundary";
import { routeLoaders } from "./router/routes";
import { routePageOwnerKey } from "./router/routeOwner";
import { useHashRoute } from "./router/useHashRoute";
import { useLocale } from "./i18n/locales";
import { UnknownRoute } from "./router/UnknownRoute";
import { useEffect } from "react";
import {
  decideControlPlaneAccess,
  isAdministrator,
  type SessionIdentity,
  useAuthentication,
} from "../features/identity/authentication";
import { FeedbackPanel } from "../shared/ui/FeedbackPanel";
import { ActionButton } from "../shared/ui/ActionButton";
import { useTranslation } from "react-i18next";
import { mayPreserveAuthorizedSetupRoute } from "./router/navigation";

const routeOptions = Object.freeze({
  defaultAccountId: "",
});

/** Compose URL routing with the application shell; page behavior belongs to features. */
export function App() {
  const route = useHashRoute(routeOptions);
  const locale = useLocale();
  const { workflow: authentication, snapshot: auth } = useAuthentication();
  const { t } = useTranslation();
  const sessionEpoch =
    auth.access.phase === "resolved" && auth.access.facts.kind === "authenticated"
      ? auth.access.facts.identity.sessionEpoch
      : null;
  const canAdminister =
    auth.access.phase === "resolved" &&
    auth.access.facts.kind === "authenticated" &&
    isAdministrator(auth.access.facts.identity);
  const identity: SessionIdentity | null =
    auth.access.phase === "resolved" && auth.access.facts.kind === "authenticated"
      ? auth.access.facts.identity
      : null;
  const {
    route: currentRoute,
    navigate,
    appId,
    setAppId,
    range,
    setRange,
    accountId,
    view,
    context,
  } = route;
  const page = route.notFound ? (
    <UnknownRoute onHome={() => navigate(ROUTE.Overview)} />
  ) : (
    <RouteBoundary
      loader={routeLoaders[currentRoute]}
      resetKey={routePageOwnerKey(currentRoute, sessionEpoch)}
      pageProps={{
        navigate,
        appId,
        setAppId,
        range,
        setRange,
        accountId,
        locale,
        view,
        environmentId: context.environmentId,
        instanceId: context.instanceId,
        eventId: context.eventId,
        incidentSeverity: context.incidentSeverity,
        incidentCategory: context.incidentCategory,
        incidentCursor: context.incidentCursor,
        publicationId: context.publicationId,
        bindingId: context.bindingId,
        metricScope: context.metricScope,
        from: context.from,
        to: context.to,
        search: context.search,
        returnTo: context.returnTo,
      }}
      onHome={() => navigate(ROUTE.Overview)}
    />
  );

  const decision = decideControlPlaneAccess(accessFor(currentRoute), auth.access);
  useEffect(() => {
    // LoginEntryPage owns authenticated/setup transitions through its route-owner callbacks.
    // Keep this app-level effect responsible only for protecting non-public destinations.
    if (currentRoute === ROUTE.Login) return;
    if (decision.kind === "login")
      navigate(
        ROUTE.Login,
        { returnTo: currentRoute === ROUTE.Setup ? undefined : currentRoute },
        { history: "replace" },
      );
    else if (decision.kind === "setup" && currentRoute !== ROUTE.Setup)
      navigate(ROUTE.Setup, {}, { history: "replace" });
  }, [auth.access, context.returnTo, currentRoute, decision.kind, navigate]);

  const recovery = () => void authentication.inspectSession().catch(() => {});
  const logoutRecovery =
    auth.logout.status === "result-unknown"
      ? {
          title: t("shell.session.logoutUnknownTitle"),
          description: t("shell.session.logoutUnknown"),
        }
      : auth.logout.status === "success"
        ? {
            title: t("shell.session.logoutUnconfirmedTitle"),
            description: t("shell.session.logoutUnconfirmed"),
          }
        : auth.logout.status === "error" || auth.logout.status === "conflict"
          ? {
              title: t("shell.session.logoutFailedTitle"),
              description: t("shell.session.logoutFailed"),
            }
          : undefined;
  if (currentRoute === ROUTE.Login) {
    if (auth.access.phase === "resolved" && auth.access.facts.kind === "anonymous") return page;
    // Keep the public login owner mounted throughout its own command and
    // confirmation/recovery projections. Replacing it here would drop
    // correctable credentials if the server rejects the attempt.
    if (
      auth.login.status !== "idle" &&
      (auth.access.phase === "authenticating" ||
        auth.access.phase === "checking" ||
        auth.access.phase === "unavailable")
    )
      return page;
    if (auth.access.phase === "unavailable")
      return (
        <IdentityRouteFeedback
          tone="error"
          title={t("shell.route.failed")}
          description={t("shell.route.failureHelp")}
          onRetry={recovery}
        />
      );
    return <IdentityRouteFeedback isBusy title={t("shell.route.loading")} description="" />;
  }
  if (currentRoute === ROUTE.Setup) {
    if (decision.kind === "setup") {
      return page;
    }
    // Keep the already-authorized one-time setup workflow mounted while its own
    // command performs the required server revalidation. A checking snapshot is
    // not new authority; it may only preserve the route until that read resolves.
    if (decision.kind === "wait" && mayPreserveAuthorizedSetupRoute(auth.access)) return page;
    if (decision.kind === "unavailable")
      return (
        <IdentityRouteFeedback
          tone="error"
          title={t("setup.operator.closedTitle")}
          description={t("setup.operator.closed")}
          onRetry={recovery}
        />
      );
    return <IdentityRouteFeedback isBusy title={t("setup.workflow.checking")} description="" />;
  }
  if (decision.kind === "wait")
    return auth.logout.status === "pending" ? (
      <IdentityRouteFeedback
        isBusy
        title={t("shell.session.logoutPendingTitle")}
        description={t("shell.session.logoutPending")}
      />
    ) : (
      <IdentityRouteFeedback isBusy title={t("shell.route.loading")} description="" />
    );
  if (decision.kind === "unavailable")
    return (
      <IdentityRouteFeedback
        tone="error"
        title={logoutRecovery?.title ?? t("shell.route.failed")}
        description={logoutRecovery?.description ?? t("shell.route.failureHelp")}
        onRetry={recovery}
        actionLabel={logoutRecovery ? t("shell.session.inspect") : undefined}
      />
    );
  if (decision.kind === "denied")
    return (
      <IdentityRouteFeedback
        tone="warning"
        title={t("management.title")}
        description={t("management.denied")}
      />
    );
  if (decision.kind !== "allow")
    return <IdentityRouteFeedback isBusy title={t("shell.route.loading")} description="" />;
  if (!identity)
    return <IdentityRouteFeedback isBusy title={t("shell.route.loading")} description="" />;

  return (
    <AppShell
      header={
        <Header
          route={currentRoute}
          navigate={navigate}
          canAdminister={canAdminister}
          identity={identity}
          logoutStatus={auth.logout.status}
          onLogout={() => void authentication.logout().catch(() => {})}
        />
      }
      banner={__SENTINEL_CONSOLE_BUILD_PROFILE__ === "demo" ? <StatusBanner /> : undefined}
      contentClassName={`page-${currentRoute}`}
      footer={<Footer />}
    >
      {page}
    </AppShell>
  );
}

function IdentityRouteFeedback({
  title,
  description,
  tone = "info",
  isBusy = false,
  onRetry,
  actionLabel,
}: {
  readonly title: string;
  readonly description: string;
  readonly tone?: "info" | "error" | "warning";
  readonly isBusy?: boolean;
  readonly onRetry?: () => void;
  readonly actionLabel?: string;
}) {
  const { t } = useTranslation();
  return (
    <main className="content">
      <FeedbackPanel
        tone={tone}
        isBusy={isBusy}
        copy={{ title, description }}
        actions={
          onRetry ? (
            <ActionButton onClick={onRetry}>
              {actionLabel ?? t("shell.feedback.retryRead")}
            </ActionButton>
          ) : undefined
        }
      />
    </main>
  );
}
