/** Finite deployment guide facts returned by the Console's versioned catalog. */
export const DEPLOYMENT_GUIDE_ID = {
  Existing: "existing",
  Linux: "linux",
  Kubernetes: "kubernetes",
} as const;
export type DeploymentGuideId = (typeof DEPLOYMENT_GUIDE_ID)[keyof typeof DEPLOYMENT_GUIDE_ID];

export const DEPLOYMENT_GUIDE_READINESS = {
  ConfigurationRequired: "configuration-required",
  GuideOnly: "guide-only",
} as const;
export type DeploymentGuideReadiness =
  (typeof DEPLOYMENT_GUIDE_READINESS)[keyof typeof DEPLOYMENT_GUIDE_READINESS];

export interface DeploymentGuidePath {
  readonly id: DeploymentGuideId;
  readonly readiness: DeploymentGuideReadiness;
  readonly profileRevision: string | null;
}

export interface DeploymentGuidesSnapshot {
  readonly catalogRevision: string;
  readonly runtimeCollector: {
    readonly state: "configured" | "not_configured";
    readonly endpoint: string | null;
  };
  readonly paths: readonly DeploymentGuidePath[];
}

/** Validate the business shape in addition to the strict wire schema. */
export function validDeploymentGuides(value: DeploymentGuidesSnapshot): boolean {
  return (
    value.catalogRevision.length > 0 &&
    value.paths.length === 3 &&
    value.paths.every((path, index) => {
      const expected = ["existing", "linux", "kubernetes"][index];
      return (
        path.id === expected &&
        (path.readiness === "configuration-required" || path.readiness === "guide-only") &&
        path.profileRevision === null
      );
    }) &&
    ((value.runtimeCollector.state === "configured" &&
      value.runtimeCollector.endpoint?.startsWith("https://") === true) ||
      (value.runtimeCollector.state === "not_configured" &&
        value.runtimeCollector.endpoint === null))
  );
}
