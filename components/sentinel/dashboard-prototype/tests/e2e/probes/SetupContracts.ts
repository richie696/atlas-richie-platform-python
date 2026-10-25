import type { SetupSubmission } from "../../../src/features/identity/model/setupSubmission";

/** Compile-time negative cases for the actual internal command input, not a copied DTO. */
export function setupContractCases() {
  const local: SetupSubmission["database"] = { kind: "sqlite" };
  // @ts-expect-error Local storage must not carry a network database password.
  const wrongLocal: SetupSubmission["database"] = { kind: "sqlite", password: "synthetic" };
  const source: SetupSubmission["source"] = {
    provider: "consul",
    endpoint: "http://127.0.0.1:8500",
    datacenter: "",
    authentication: { mode: "direct", aclToken: "synthetic" },
  };
  const wrongSource: SetupSubmission["source"] = {
    provider: "consul",
    endpoint: "http://127.0.0.1:8500",
    datacenter: "",
    // @ts-expect-error Nacos direct credentials cannot substitute for a Consul ACL token.
    authentication: { mode: "direct", username: "user", password: "synthetic" },
  };
  const wrongAdmin: SetupSubmission["admin"] = {
    username: "admin",
    password: "synthetic",
    // @ts-expect-error Confirmation is a local form field, not a command credential.
    confirm: "synthetic",
  };
  return { local, source, wrongLocal, wrongSource, wrongAdmin };
}
