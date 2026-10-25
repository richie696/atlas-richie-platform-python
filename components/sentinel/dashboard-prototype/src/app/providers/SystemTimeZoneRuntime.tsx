import { useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { useAuthentication } from "../../features/identity/authentication";
import { createSystemSettingsHttp } from "../../features/system";
import {
  getSystemTimeZone,
  setSystemTimeZone,
  subscribeSystemTimeZone,
} from "../../shared/presentation/systemTimeZone";
import { useConsoleServices } from "./ConsoleServicesProvider";

/** Loads the durable system timezone for every authenticated Console route. */
export function SystemTimeZoneRuntime({ children }: { readonly children: ReactNode }) {
  const services = useConsoleServices();
  const { snapshot } = useAuthentication();
  const identity =
    snapshot.access.phase === "resolved" && snapshot.access.facts.kind === "authenticated"
      ? snapshot.access.facts.identity
      : null;
  const sessionEpoch = identity?.sessionEpoch ?? null;
  const settings = useMemo(
    () => createSystemSettingsHttp(services.transport),
    [services.transport],
  );
  const timeZone = useSyncExternalStore(
    subscribeSystemTimeZone,
    getSystemTimeZone,
    getSystemTimeZone,
  );

  useEffect(() => {
    if (sessionEpoch === null) return;
    const controller = new AbortController();
    void settings
      .read(controller.signal)
      .then((result) => setSystemTimeZone(result.timeZone))
      .catch(() => {});
    return () => controller.abort();
  }, [sessionEpoch, settings]);

  // The subscription causes the shell subtree to render again after a setting change.
  void timeZone;
  return <>{children}</>;
}
