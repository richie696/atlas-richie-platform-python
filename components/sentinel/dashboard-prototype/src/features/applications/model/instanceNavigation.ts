import type { NavigationContext } from "../../../shared/types/navigation";

/** Clear the explicit instance target and layer from a merged route context. */
export function withoutInstanceSelection(context: NavigationContext): NavigationContext {
  return { ...context, instanceId: undefined, metricScope: undefined };
}
