import { AppShell } from "./shell/AppShell";
import { Header } from "./shell/Header";
import { StatusBanner } from "./shell/StatusBanner";
import { Footer } from "./shell/Footer";
import { AccessPendingHeader } from "./shell/AccessPendingHeader";
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
import { mayPreserveAuthorizedSetupRoute, shouldKeepLoginEntryMounted } from "./router/navigation";
import { useConsoleRuntime } from "../core/api/runtime/ConsoleRuntimeProvider";

const routeOptions = Object.freeze({
  defaultAccountId: "",
});

/** Compose URL routing with the application shell; page behavior belongs to features. */
export function App() {
  const runtime = useConsoleRuntime();
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
        section: context.section,
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
        embeddedInAppShell: Boolean(identity),
      }}
      onHome={() => navigate(ROUTE.Overview)}
    />
  );

  const decision = decideControlPlaneAccess(accessFor(currentRoute), auth.access);
  useEffect(() => {
    // LoginEntryPage owns authenticated/setup transitions through its route-owner callbacks.
    // Keep this app-level effect responsible only for protecting non-public destinations.
    if (currentRoute === ROUTE.Login) return;
    if (currentRoute === ROUTE.Documentation) return;
    if (decision.kind === "login")
      navigate(
        ROUTE.Login,
        { returnTo: currentRoute === ROUTE.Setup ? undefined : currentRoute },
        { history: "replace" },
      );
    else if (decision.kind === "setup" && currentRoute !== ROUTE.Setup)
      navigate(ROUTE.Setup, {}, { history: "replace" });
  }, [auth.access, context.returnTo, currentRoute, decision.kind, navigate]);

  useEffect(() => {
    // A successful self-password reset revokes the current session. Once the
    // login route is active, resolve that expired snapshot against the server
    // so LoginEntryPage can render the anonymous login form instead of waiting
    // forever for a state transition that no longer has an owner.
    if (currentRoute === ROUTE.Login && auth.access.phase === "expired") {
      void authentication.restore().catch(() => {
        // The workflow publishes the unavailable state; the login route exposes retry.
      });
    }
  }, [auth.access.phase, authentication, currentRoute]);

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
    // Confirmed access must reach LoginEntryPage: its owner effect redirects
    // authenticated sessions and first-run installations to their safe routes.
    // Keep it mounted during a command too, so correctable credentials survive.
    if (shouldKeepLoginEntryMounted(auth.access, auth.login.status !== "idle")) return page;
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
  if (currentRoute === ROUTE.Documentation && !identity)
    return (
      <AppShell header={null} contentClassName={`page-${currentRoute}`}>
        {page}
      </AppShell>
    );
  // Keep the same chrome owner through initial checks and access revalidation.
  // Non-allowed states render only neutral feedback, never previously protected
  // route content or identity data.
  const accessPending =
    currentRoute !== ROUTE.Documentation && (decision.kind !== "allow" || !identity);
  const accessFeedback =
    decision.kind === "unavailable" ? (
      <IdentityRouteFeedback
        tone="error"
        title={logoutRecovery?.title ?? t("shell.route.failed")}
        description={logoutRecovery?.description ?? t("shell.route.failureHelp")}
        onRetry={recovery}
        actionLabel={logoutRecovery ? t("shell.session.inspect") : undefined}
      />
    ) : decision.kind === "denied" ? (
      <IdentityRouteFeedback
        tone="warning"
        title={t("management.title")}
        description={t("management.denied")}
      />
    ) : (
      <IdentityRouteFeedback
        isBusy
        title={
          auth.logout.status === "pending"
            ? t("shell.session.logoutPendingTitle")
            : t("shell.route.loading")
        }
        description={auth.logout.status === "pending" ? t("shell.session.logoutPending") : ""}
      />
    );

  return (
    <AppShell
      header={
        accessPending || !identity ? (
          <AccessPendingHeader />
        ) : (
          <Header
            route={currentRoute}
            navigate={navigate}
            canAdminister={canAdminister}
            identity={identity}
            logoutStatus={auth.logout.status}
            onLogout={() => void authentication.logout().catch(() => {})}
          />
        )
      }
      banner={runtime.mode === "mock" ? <StatusBanner /> : undefined}
      contentClassName={`page-${currentRoute}`}
      footer={runtime.mode === "mock" ? <Footer /> : undefined}
    >
      {accessPending ? <section data-route-state="access-pending">{accessFeedback}</section> : page}
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
  insideShell = false,
}: {
  readonly title: string;
  readonly description: string;
  readonly tone?: "info" | "error" | "warning";
  readonly isBusy?: boolean;
  readonly onRetry?: () => void;
  readonly actionLabel?: string;
  readonly insideShell?: boolean;
}) {
  const { t } = useTranslation();
  const panel = (
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
  );
  return insideShell ? (
    <section data-route-state="access-pending">{panel}</section>
  ) : (
    <main className="content">{panel}</main>
  );
}
