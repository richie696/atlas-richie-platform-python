import { useTranslation } from "react-i18next";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import type { RuleSetCollection } from "../model/ruleSet";
import type { RuleSetVersion } from "../model/ruleDeployment";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { RuleQueryView } from "./RuleQueryView";
import styles from "./RuleSetWorkspace.module.scss";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
/** Immutable content inspection. Publication is an explicit separate confirmation, never a property edit on a version. */
export function RuleVersionsPanel({
  versions,
  version,
  selectedId,
  canPublish,
  onSelect,
  onRead,
  onPublish,
}: {
  readonly versions: QuerySnapshot<RuleSetCollection<RuleSetVersion>>;
  readonly version: QuerySnapshot<RuleSetVersion>;
  readonly selectedId: string | null;
  readonly canPublish: boolean;
  readonly onSelect: (id: string) => void;
  readonly onRead: () => void;
  readonly onPublish: () => void;
}) {
  const { t, i18n } = useTranslation();
  return (
    <Panel
      title={t("rules.deployment.versionsTitle")}
      subtitle={t("rules.versions.immutable")}
      action={<ActionButton onClick={onRead}>{t("rules.deployment.refreshVersions")}</ActionButton>}
    >
      <div className={styles.content}>
        <RuleQueryView snapshot={versions} onRetry={onRead}>
          {(collection) => (
            <div className={styles.actions}>
              {collection.items.map((item) => (
                <ActionButton
                  key={item.id}
                  data-deployment-version={item.id}
                  aria-pressed={item.id === selectedId}
                  onClick={() => onSelect(item.id)}
                >
                  {item.name}
                </ActionButton>
              ))}
            </div>
          )}
        </RuleQueryView>
        <RuleQueryView
          snapshot={version}
          onRetry={() => {
            if (selectedId) onSelect(selectedId);
          }}
        >
          {(item) => (
            <section data-version-detail>
              <dl className={styles.facts}>
                <div>
                  <dt>{t("rules.deployment.versionId")}</dt>
                  <dd>{item.id}</dd>
                </div>
                <div>
                  <dt>{t("rules.workspace.checksum")}</dt>
                  <dd>{item.checksum}</dd>
                </div>
                <div>
                  <dt>{t("rules.deployment.createdAt")}</dt>
                  <dd>
                    <time dateTime={new Date(item.createdAtMs).toISOString()}>
                      {formatUtcDateTime(item.createdAtMs, i18n.resolvedLanguage ?? i18n.language)}
                    </time>
                  </dd>
                </div>
              </dl>
              <p>{item.note}</p>
              <pre className={styles.preview} data-version-preview>
                {JSON.stringify(
                  item.records.map((record) => record.rule.value),
                  null,
                  2,
                )}
              </pre>
              <ActionButton data-deployment-publish disabled={!canPublish} onClick={onPublish}>
                {t("rules.deployment.publishTarget")}
              </ActionButton>
              <p>{t("rules.deployment.rollbackHint")}</p>
            </section>
          )}
        </RuleQueryView>
      </div>
    </Panel>
  );
}
