import type { ComponentType } from "react";
import { useMemo } from "react";
import type { DashboardPageProps } from "../../shared/types/dashboard";
import { ROUTE, type RouteId } from "./route.constants";
import type { RouteLoader } from "./RouteBoundary";
import { useConsoleServices } from "../providers/ConsoleServicesProvider";

/** Application-owned navigation projection; no wire DTOs or feature store references. */
export interface RoutePageContext extends DashboardPageProps {
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
      const [{ FleetOverviewContainer, createFleetHttp }, { createObservationCatalogHttp }] =
        await Promise.all([
          import("../../features/overview"),
          import("../../features/applications"),
        ]);
      const Page: ComponentType<RoutePageContext> = (props) => {
        const { transport } = useConsoleServices();
        const fleetPort = useMemo(() => createFleetHttp(transport), [transport]);
        const catalogPort = useMemo(() => createObservationCatalogHttp(transport), [transport]);
        return (
          <FleetOverviewContainer {...props} fleetPort={fleetPort} catalogPort={catalogPort} />
        );
      };
      return { default: Page };
    },
    [ROUTE.Applications]: async () => {
      const { ApplicationsObservationContainer, createObservationCatalogHttp, createInstanceHttp } =
        await import("../../features/applications");
      const Page: ComponentType<RoutePageContext> = (props) => {
        const { transport } = useConsoleServices();
        const catalogPort = useMemo(() => createObservationCatalogHttp(transport), [transport]);
        const instancePort = useMemo(() => createInstanceHttp(transport), [transport]);
        return (
          <ApplicationsObservationContainer
            {...props}
            catalogPort={catalogPort}
            instancePort={instancePort}
          />
        );
      };
      return { default: Page };
    },
    [ROUTE.Rules]: async () => {
      const [
        { RuleConsoleContainer, createRuleSetHttp },
        { createObservationCatalogHttp },
        { createSourceRegistrationHttp },
      ] = await Promise.all([
        import("../../features/rules"),
        import("../../features/applications"),
        import("../../features/system"),
      ]);
      const Page: ComponentType<RoutePageContext> = (props) => {
        const { transport } = useConsoleServices();
        const ruleSetPort = useMemo(() => createRuleSetHttp(transport), [transport]);
        const catalogPort = useMemo(() => createObservationCatalogHttp(transport), [transport]);
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
            catalogPort={catalogPort}
            sourceCatalogPort={sourceCatalogPort}
          />
        );
      };
      return { default: Page };
    },
    [ROUTE.Realtime]: async () => {
      const [
        { RealtimeObservationContainer, createMetricsHttp },
        { createObservationCatalogHttp, createInstanceHttp },
      ] = await Promise.all([
        import("../../features/realtime"),
        import("../../features/applications"),
      ]);
      const Page: ComponentType<RoutePageContext> = (props) => {
        const { transport } = useConsoleServices();
        const metricsPort = useMemo(() => createMetricsHttp(transport), [transport]);
        const catalogPort = useMemo(() => createObservationCatalogHttp(transport), [transport]);
        const instancePort = useMemo(() => createInstanceHttp(transport), [transport]);
        return (
          <RealtimeObservationContainer
            {...props}
            metricsPort={metricsPort}
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
