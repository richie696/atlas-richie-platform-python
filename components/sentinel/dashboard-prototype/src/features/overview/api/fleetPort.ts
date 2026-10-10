import type { FleetQuery, FleetSnapshot } from "../model/fleet";

/** Internal read capability. An adapter must aggregate/filter at the backend, never from one page of rows. */
export interface FleetPort {
  readonly readFleet: (query: FleetQuery, signal: AbortSignal) => Promise<FleetSnapshot>;
}
