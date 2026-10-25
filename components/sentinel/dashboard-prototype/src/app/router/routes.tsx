import type { ComponentType } from "react";
import { useMemo } from "react";
import type { DashboardPageProps } from "../../shared/types/dashboard";
import { ROUTE, type RouteId } from "./route.constants";
import type { RouteLoader } from "./RouteBoundary";
import { useConsoleServices } from "../providers/ConsoleServicesProvider";
import { PublicLocaleControl } from "../shell/PublicLocaleControl";

/** Application-owned navigation projection; no wire DTOs or feature store references. */
export interface RoutePageContext extends DashboardPageProps {
  /** True when the route is rendered under the authenticated console shell. */
  readonly embeddedInAppShell: boolean;
  readonly accountId: string;
  readonly environmentId?: string;
  readonly instanceId?: string;
  readonly eventId?: string;
  readonly incidentSeverity?: string;
  readonly incidentCategory?: string;
  readonly incidentCursor?: string;
  readonly publicationId?: string;
  readonly versionId?: string;
  readonly bindingId?: string;
  readonly metricScope?: string;
  readonly from?: string;
  readonly to?: string;
  readonly search?: string;
}

/** Stable lazy loader table. Each feature is reached through its public entry. */
export const routeLoaders: Readonly<Record<RouteId, RouteLoader<RoutePageContext>>> = Object.freeze(
  {
    [ROUTE.Overview]: async () => {
      const [overview, applications, system, hosts] = await Promise.all([
        import("../../features/overview"),
        import("../../features/applications"),
        import("../../features/system"),
        import("../../features/hosts"),
      ]);
      const { FleetOverviewContainer, createFleetHttp } = overview;
      const { createObservationCatalogHttp } = applications;
      const Page: ComponentType<RoutePageContext> = (props) => {
        const { transport } = useConsoleServices();
        const fleetPort = useMemo(() => createFleetHttp(transport), [transport]);
        const catalogPort = useMemo(() => createObservationCatalogHttp(transport), [transport]);
        const sourcePort = useMemo(() => system.createMonitoringSourceHttp(transport), [transport]);
        return (
          <FleetOverviewContainer
            {...props}
            fleetPort={fleetPort}
            catalogPort={catalogPort}
            hostMonitoringSummary={
              props.environmentId ? (
                <hosts.HostMonitoringSummary
                  environmentId={props.environmentId}
                  sourcePort={{ readSources: (signal) => sourcePort.readSources(signal) }}
                  navigate={props.navigate}
                />
              ) : null
            }
          />
        );
      };
      return { default: Page };
    },
    [ROUTE.Applications]: async () => {
      const [applications, system, realtime, hosts] = await Promise.all([
        import("../../features/applications"),
        import("../../features/system"),
        import("../../features/realtime"),
        import("../../features/hosts"),
      ]);
      const { ApplicationsObservationContainer, createObservationCatalogHttp, createInstanceHttp } =
        applications;
      const Page: ComponentType<RoutePageContext> = (props) => {
        const { transport } = useConsoleServices();
        const catalogPort = useMemo(() => createObservationCatalogHttp(transport), [transport]);
        const instancePort = useMemo(() => createInstanceHttp(transport), [transport]);
        const sourcePort = useMemo(() => system.createMonitoringSourceHttp(transport), [transport]);
        const hostMetricsPort = useMemo(
          () => realtime.createHostMetricsHttp(transport),
          [transport],
        );
        const hostAssociationsPort = useMemo(
          () => hosts.createHostAssociationHttp(transport),
          [transport],
        );
        if (props.view === "hosts" && props.environmentId) {
          return (
            <hosts.HostDirectoryPage
              environmentId={props.environmentId}
              appId={props.appId}
              sourcesPort={{ readSources: (signal) => sourcePort.readSources(signal) }}
              metricsPort={hostMetricsPort}
              associationPort={hostAssociationsPort}
              navigate={props.navigate}
            />
          );
        }
        return (
          <ApplicationsObservationContainer
            {...props}
            catalogPort={catalogPort}
            instancePort={instancePort}
            onShowHosts={() =>
              props.navigate(ROUTE.Applications, {
                environmentId: props.environmentId ?? "",
                appId: props.appId,
                view: "hosts",
              })
            }
          />
        );
      };
      return { default: Page };
    },
    [ROUTE.Rules]: async () => {
      const [
        {
          RuleConsoleContainer,
          createRuleSetHttp,
          createRuleBindingScopeHttp,
          createRuleObservationHttp,
        },
        { createSourceRegistrationHttp },
      ] = await Promise.all([import("../../features/rules"), import("../../features/system")]);
      const Page: ComponentType<RoutePageContext> = (props) => {
        const { transport } = useConsoleServices();
        const ruleSetPort = useMemo(() => createRuleSetHttp(transport), [transport]);
        const observationPort = useMemo(() => createRuleObservationHttp(transport), [transport]);
        const scopePort = useMemo(() => createRuleBindingScopeHttp(transport), [transport]);
        const sourceRegistrationPort = useMemo(
          () => createSourceRegistrationHttp(transport),
          [transport],
        );
        const sourceCatalogPort = useMemo(
          () => ({
            async readSources(signal: AbortSignal) {
              const registry = await sourceRegistrationPort.readSources(signal);
              return {
                asOfMs: registry.asOfMs,
                items: registry.items.map((source) =>
                  source.provider === "nacos"
                    ? {
                        id: source.id,
                        revision: source.revision,
                        name: source.name,
                        provider: source.provider,
                        namespace: source.namespace,
                      }
                    : {
                        id: source.id,
                        revision: source.revision,
                        name: source.name,
                        provider: source.provider,
                        datacenter: source.datacenter,
                      },
                ),
              };
            },
          }),
          [sourceRegistrationPort],
        );
        return (
          <RuleConsoleContainer
            {...props}
            ruleSetPort={ruleSetPort}
            observationPort={observationPort}
            scopePort={scopePort}
            sourceCatalogPort={sourceCatalogPort}
          />
        );
      };
      return { default: Page };
    },
    [ROUTE.Realtime]: async () => {
      const [
        { RealtimeObservationContainer, createMetricsHttp, createHostMetricsHttp },
        { createObservationCatalogHttp, createInstanceHttp },
        { createMonitoringSourceHttp },
      ] = await Promise.all([
        import("../../features/realtime"),
        import("../../features/applications"),
        import("../../features/system"),
      ]);
      const Page: ComponentType<RoutePageContext> = (props) => {
        const { transport } = useConsoleServices();
        const metricsPort = useMemo(() => createMetricsHttp(transport), [transport]);
        const catalogPort = useMemo(() => createObservationCatalogHttp(transport), [transport]);
        const instancePort = useMemo(() => createInstanceHttp(transport), [transport]);
        const hostMetricsPort = useMemo(() => createHostMetricsHttp(transport), [transport]);
        const sourcePort = useMemo(() => createMonitoringSourceHttp(transport), [transport]);
        const hostMetricsSourcePort = useMemo(
          () => ({ readSources: (signal: AbortSignal) => sourcePort.readSources(signal) }),
          [sourcePort],
        );
        return (
          <RealtimeObservationContainer
            {...props}
            metricsPort={metricsPort}
            hostMetricsPort={hostMetricsPort}
            hostMetricsSourcePort={hostMetricsSourcePort}
            catalogPort={catalogPort}
            instancePort={instancePort}
          />
        );
      };
      return { default: Page };
    },
    [ROUTE.Faults]: async () => {
      const [
        { IncidentObservationContainer, createIncidentHttp },
        { createObservationCatalogHttp, createInstanceHttp },
      ] = await Promise.all([
        import("../../features/faults"),
        import("../../features/applications"),
      ]);
      const Page: ComponentType<RoutePageContext> = (props) => {
        const { transport } = useConsoleServices();
        const incidentPort = useMemo(() => createIncidentHttp(transport), [transport]);
        const catalogPort = useMemo(() => createObservationCatalogHttp(transport), [transport]);
        const instancePort = useMemo(() => createInstanceHttp(transport), [transport]);
        return (
          <IncidentObservationContainer
            {...props}
            incidentPort={incidentPort}
            catalogPort={catalogPort}
            instancePort={instancePort}
          />
        );
      };
      return { default: Page };
    },
    [ROUTE.System]: async () => {
      const { ConsoleSystemRoute } = await import("./ConsoleSystemRoute");
      return { default: ConsoleSystemRoute };
    },
    [ROUTE.Documentation]: async () => {
      const { DocumentationPage } = await import("../../features/documentation");
      const Page: ComponentType<RoutePageContext> = (props) => (
        <DocumentationPage
          {...props}
          embeddedInAppShell={props.embeddedInAppShell}
          localeControl={<PublicLocaleControl />}
        />
      );
      return { default: Page };
    },
    [ROUTE.Accounts]: async () => ({
      default: (await import("./IdentityRouteOwners")).ConsoleAccountsRoute,
    }),
    [ROUTE.Roles]: async () => {
      const { ConsoleRolesRoute } = await import("./IdentityRouteOwners");
      return { default: ConsoleRolesRoute };
    },
    [ROUTE.ChangePassword]: async () => ({
      default: (await import("./IdentityRouteOwners")).ConsoleOwnPasswordRoute,
    }),
    [ROUTE.Login]: async () => ({
      default: (await import("./IdentityRouteOwners")).ConsoleLoginRoute,
    }),
    [ROUTE.Setup]: async () => {
      const { SetupRouteOwner } = await import("./SetupRouteOwner");
      return { default: SetupRouteOwner };
    },
  },
);
