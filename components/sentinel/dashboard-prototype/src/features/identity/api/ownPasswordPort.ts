import type { OwnPasswordChange } from "../model/ownPasswordChange";

/** Confirmed server policy, not inferred from a status code or a local role. */
export interface OwnPasswordReceipt {
  readonly sessionDisposition: "reauthenticate";
}

/** Password mutation boundary. No target account or secrets appear in its receipt. */
export interface OwnPasswordPort {
  readonly changeOwnPassword: (
    input: OwnPasswordChange,
    signal: AbortSignal,
  ) => Promise<OwnPasswordReceipt>;
}
