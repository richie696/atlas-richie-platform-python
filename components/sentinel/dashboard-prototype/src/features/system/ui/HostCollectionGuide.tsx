import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { QueryResource } from "../../../shared/state/queryResource";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { Panel } from "../../../shared/ui/Panel";
import styles from "./SystemObservation.module.scss";
import type { DeploymentGuidesSnapshot } from "../model/deploymentGuide";

const COLLECTION_PATHS = ["existing", "linux", "kubernetes"] as const;
type CollectionPath = (typeof COLLECTION_PATHS)[number];
const COLLECTION_COPY = {
  existing: {
    title: "system.hostCollection.existing.title",
    description: "system.hostCollection.existing.description",
    steps: [
      "system.hostCollection.existing.step1",
      "system.hostCollection.existing.step2",
      "system.hostCollection.existing.step3",
    ],
    availability: "system.hostCollection.existing.availability",
  },
  linux: {
    title: "system.hostCollection.linux.title",
    description: "system.hostCollection.linux.description",
    steps: [
      "system.hostCollection.linux.step1",
      "system.hostCollection.linux.step2",
      "system.hostCollection.linux.step3",
    ],
    availability: "system.hostCollection.linux.availability",
  },
  kubernetes: {
    title: "system.hostCollection.kubernetes.title",
    description: "system.hostCollection.kubernetes.description",
    steps: [
      "system.hostCollection.kubernetes.step1",
      "system.hostCollection.kubernetes.step2",
      "system.hostCollection.kubernetes.step3",
    ],
    availability: "system.hostCollection.kubernetes.availability",
  },
} as const;
const COLLECTION_LABEL = {
  existing: "system.hostCollection.paths.existing",
  linux: "system.hostCollection.paths.linux",
  kubernetes: "system.hostCollection.paths.kubernetes",
} as const;

/** Explains host-metric onboarding without implying that Sentinel deploys collectors. */
export function HostCollectionGuide({
  resource,
}: {
  readonly resource: QueryResource<null, DeploymentGuidesSnapshot>;
}) {
  const { t } = useTranslation();
  const [selectedPath, setSelectedPath] = useState<CollectionPath>("existing");
  const catalog = useQueryResource(resource, null);
  const copy = COLLECTION_COPY[selectedPath];
  const read = () => void resource.load(null).catch(() => {});
  const facts = "data" in catalog ? catalog.data : null;
  const selectedFact = facts?.paths.find((path) => path.id === selectedPath);

  return (
    <Panel title={t("system.hostCollection.title")} subtitle={t("system.hostCollection.subtitle")}>
      <div className={styles.content}>
        <p className={styles.guideNotice} role="note">
          {t("system.hostCollection.boundary")}
        </p>
        <div className={styles.guideNotice} aria-live="polite">
          {catalog.status === "loading" && t("system.hostCollection.catalogLoading")}
          {(catalog.status === "error" || catalog.status === "stale") && (
            <>
              <p>{t("system.hostCollection.catalogFailed")}</p>
              <ActionButton type="button" onClick={read}>
                {t("system.hostCollection.retry")}
              </ActionButton>
            </>
          )}
          {facts && (
            <>
              <p>
                {t("system.hostCollection.catalogRevision", { revision: facts.catalogRevision })}
              </p>
              <p>
                {facts.runtimeCollector.endpoint
                  ? t("system.hostCollection.collectorConfigured", {
                      endpoint: facts.runtimeCollector.endpoint,
                    })
                  : t("system.hostCollection.collectorNotConfigured")}
              </p>
              {selectedFact && (
                <p>
                  {t(
                    selectedFact.readiness === "guide-only"
                      ? "system.hostCollection.readiness.guide-only"
                      : "system.hostCollection.readiness.configuration-required",
                  )}
                  {selectedFact.profileRevision ? ` · ${selectedFact.profileRevision}` : ""}
                </p>
              )}
            </>
          )}
        </div>
        <div
          className={styles.guideChoices}
          role="group"
          aria-label={t("system.hostCollection.choosePath")}
        >
          {COLLECTION_PATHS.map((path) => (
            <ActionButton
              key={path}
              type="button"
              aria-pressed={selectedPath === path}
              className={selectedPath === path ? styles.guideChoiceActive : undefined}
              onClick={() => setSelectedPath(path)}
            >
              {t(COLLECTION_LABEL[path])}
            </ActionButton>
          ))}
        </div>
        <section className={styles.guideDetails} aria-live="polite">
          <h3>{t(copy.title)}</h3>
          <p>{t(copy.description)}</p>
          <ol>
            {copy.steps.map((step) => (
              <li key={step}>{t(step)}</li>
            ))}
          </ol>
          <p className={styles.guideBoundary}>{t(copy.availability)}</p>
        </section>
      </div>
    </Panel>
  );
}
