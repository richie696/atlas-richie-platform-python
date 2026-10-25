/** Confirmed host-to-worker mapping returned by the Console API. */
export type HostAssociation = {
  readonly sourceId: string;
  readonly environmentId: string;
  readonly hostId: string;
  readonly appId: string;
  readonly instanceId: string;
  readonly processId: string;
  readonly revision: string;
  readonly provenance: "operator_confirmed";
  readonly currentEpoch: string | null;
  readonly lastReceivedAt: string | null;
  readonly reporterActive: boolean;
  readonly createdAt: string;
};

/** One bounded page of explicitly configured host associations. */
export type HostAssociationDirectory = {
  readonly environmentId: string;
  readonly asOf: string;
  readonly page: number;
  readonly pageSize: number;
  readonly total: number;
  readonly associatedHostIds: readonly string[];
  readonly hostIdsComplete: boolean;
  readonly items: readonly HostAssociation[];
};

/** Input for associating a monitored host with one enrolled application worker. */
export type HostAssociationInput = {
  readonly requestKey: string;
  readonly environmentId: string;
  readonly sourceId: string;
  readonly hostId: string;
  readonly appId: string;
  readonly instanceId: string;
  readonly expectedRevision: string | null;
};

/** Result of a potentially replayed host-association command. */
export type HostAssociationOperation =
  | {
      readonly status: "completed";
      readonly requestKey: string;
      readonly result: HostAssociation | { readonly removed: true };
    }
  | { readonly status: "not_found"; readonly requestKey: string };

/** Application-facing boundary for host association reads and mutations. */
export interface HostAssociationPort {
  read(
    environmentId: string,
    filters: {
      readonly sourceId?: string;
      readonly appId?: string;
      readonly instanceId?: string;
      readonly page: number;
      readonly pageSize: number;
    },
    signal: AbortSignal,
  ): Promise<HostAssociationDirectory>;
  associate(input: HostAssociationInput, signal: AbortSignal): Promise<HostAssociation>;
  remove(
    input: {
      readonly requestKey: string;
      readonly environmentId: string;
      readonly appId: string;
      readonly instanceId: string;
      readonly expectedRevision: string;
    },
    signal: AbortSignal,
  ): Promise<{ readonly removed: true }>;
  readOperation(requestKey: string, signal: AbortSignal): Promise<HostAssociationOperation>;
}
