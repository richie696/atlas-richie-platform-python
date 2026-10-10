import { useEffect } from "react";
import { useReactFramework } from "@richie696/react-framework-react";

/** Commit-time test observation; no external mutation during render. */
export function ProviderProbe({
  value,
  onSnapshot,
}: {
  readonly value: string;
  readonly onSnapshot: (services: ReturnType<typeof useReactFramework>) => void;
}) {
  const services = useReactFramework();
  useEffect(() => {
    onSnapshot(services);
  }, [services, onSnapshot, value]);
  return <output>{value}</output>;
}
