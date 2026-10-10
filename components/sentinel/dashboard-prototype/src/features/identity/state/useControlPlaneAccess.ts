import { useMemo } from "react";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import type { IdentityAccessPort } from "../api/identityAccessPort";
import { accessStateFromResource, createAccessResource } from "./accessResource";

/** App bootstrap subscription. Stable Port + session generation own this resource; StrictMode cancels safely. */
export function useControlPlaneAccess(port: IdentityAccessPort, sessionGeneration: string) {
  const resource = useMemo(() => createAccessResource(port), [port]);
  const query = useMemo(() => ({ sessionGeneration }), [sessionGeneration]);
  const snapshot = useQueryResource(resource, query);
  return { state: accessStateFromResource(snapshot), resource };
}
