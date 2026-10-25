/** Safe persisted view of a Prometheus-compatible monitoring source. */
export interface MonitoringSourceRecord {
  readonly id: string;
  readonly revision: string;
  readonly displayName: string;
  readonly environmentId: string;
  readonly provider: "prometheus-compatible";
  readonly profile: "node-exporter-v1";
  readonly enabled: boolean;
  readonly authenticationMode: "none" | "direct-basic" | "direct-bearer" | "credential-reference";
  readonly credentialConfigured: boolean;
  readonly endpointOrigin?: string;
  readonly identityLabels?: readonly string[];
  readonly selectorLabels?: readonly { readonly name: string; readonly value: string }[];
  readonly scrapeIntervalSeconds?: number;
  readonly staleAfterSeconds?: number;
}

/** Candidate submitted for bounded validation and management; credential values are transient only. */
export interface MonitoringSourceCandidate {
  readonly sourceId: string;
  readonly revision: string;
  readonly displayName: string;
  readonly environmentId: string;
  readonly endpoint: string;
  readonly provider: "prometheus-compatible";
  readonly profile: "node-exporter-v1";
  readonly authenticationMode: MonitoringSourceRecord["authenticationMode"];
  readonly credentialConfigured: boolean;
  readonly enabled: boolean;
  readonly identityLabels: readonly string[];
  readonly selectorLabels: readonly { readonly name: string; readonly value: string }[];
  readonly scrapeIntervalSeconds: number;
  readonly staleAfterSeconds: number;
}

export type MonitoringCredentialMaterial =
  | null
  | { readonly username: string; readonly password: string }
  | { readonly bearerToken: string }
  | { readonly reference: string };

export interface MonitoringSourceCheckReceipt {
  readonly checkId: string;
  readonly sourceId: string;
  readonly sourceRevision: string;
  readonly candidateFingerprint: string;
  readonly checkedAt: string;
  readonly expiresAt: string;
  readonly result: {
    readonly connection: "reachable" | "unreachable";
    readonly queryApi: "available" | "denied" | "unsupported" | "unknown";
    readonly profile: "supported" | "missing_samples" | "unsupported" | "unknown";
    readonly identity: {
      readonly observed: number;
      readonly unique: number;
      readonly missing: number;
      readonly conflicting: number;
    };
    readonly failure:
      "target_rejected" | "authentication" | "timeout" | "transport" | "invalid_response" | null;
  };
}

export interface MonitoringSourceOperation {
  readonly status: "completed" | "rejected" | "not_found";
  readonly requestKey: string;
  readonly sourceId?: string;
  readonly sourceRevision?: string;
  readonly enabled?: boolean;
  readonly verified?: boolean;
  readonly reason?:
    "conflict" | "not_found" | "check_required" | "check_mismatch" | "source_in_use";
}

export interface MonitoringSourcesSnapshot {
  readonly asOf: string;
  readonly items: readonly MonitoringSourceRecord[];
}

export type MonitoringSourceMutation =
  | {
      readonly kind: "set-enabled";
      readonly requestKey: string;
      readonly sourceId: string;
      readonly expectedRevision: string;
      readonly enabled: boolean;
    }
  | {
      readonly kind: "create" | "update";
      readonly requestKey: string;
      readonly source: MonitoringSourceCandidate;
      readonly credentials: MonitoringCredentialMaterial;
      readonly credentialUpdate: "keep" | "replace" | "clear";
      readonly checkId: string | null;
      readonly skipCheck: boolean;
      readonly expectedRevision?: string;
    }
  | {
      readonly kind: "delete";
      readonly requestKey: string;
      readonly sourceId: string;
      readonly expectedRevision: string;
    };

export interface MonitoringSourceWorkflowSnapshot {
  readonly authorized: boolean;
  readonly loading: boolean;
  readonly items: readonly MonitoringSourceRecord[];
  readonly error: "read_failed" | "write_failed" | "unknown_outcome" | null;
  readonly busyRequestKey: string | null;
  readonly unresolvedRequestKey: string | null;
  readonly lastOperation: MonitoringSourceOperation | null;
}
