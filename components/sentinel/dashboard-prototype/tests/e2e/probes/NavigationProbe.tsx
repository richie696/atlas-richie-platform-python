import { useHashRoute, type UseHashRouteOptions } from "../../../src/app/router/useHashRoute";
import { NAVIGATION_HISTORY, ROUTE } from "../../../src/shared/types/navigation";

/** Actual URL owner + native history; no copied router implementation. */
export function NavigationProbe({ options }: { readonly options: UseHashRouteOptions }) {
  const route = useHashRoute(options);
  return (
    <section>
      <output>{JSON.stringify(route)}</output>
      <button
        data-action="push"
        onClick={() =>
          route.navigate(ROUTE.Rules, {
            appId: "order-service",
            view: "flow",
            environmentId: "prod",
            instanceId: "order-1",
            resource: "POST /api/orders?status=ready",
            eventId: "event-1",
            versionId: "version-1",
            metricScope: "application",
            search: "qps > 100",
          })
        }
      >
        Push observation
      </button>
      <button
        data-action="replace"
        onClick={() =>
          route.navigate(
            ROUTE.Rules,
            { search: "qps > 200" },
            { history: NAVIGATION_HISTORY.Replace },
          )
        }
      >
        Replace search
      </button>
      <button
        data-action="clear"
        onClick={() =>
          route.navigate(ROUTE.Rules, {
            instanceId: undefined,
            eventId: undefined,
            view: undefined,
          })
        }
      >
        Clear targets
      </button>
      <button data-action="cross" onClick={() => route.navigate(ROUTE.Applications)}>
        Cross page
      </button>
    </section>
  );
}
