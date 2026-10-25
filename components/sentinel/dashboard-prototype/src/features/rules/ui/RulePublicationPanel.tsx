import { useTranslation } from "react-i18next";
import type { QuerySnapshot } from "../../../shared/state/queryResource";
import type { RuleSetCollection } from "../model/ruleSet";
import type { RulePublication, PublicationReceiptPage } from "../model/ruleDeployment";
import {
  PUBLICATION_STAGE_LABEL,
  RECEIPT_STATE_LABEL,
  publicationStages,
} from "../presentation/deploymentLabels";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable } from "../../../shared/ui/DataTable";
import { RuleQueryView } from "./RuleQueryView";
import styles from "./RuleSetWorkspace.module.scss";
import { formatLocaleNumber } from "../../../shared/presentation/formatLocaleNumber";
/** Write/readback/loading are independent observations. Aggregate counts describe all expected processes, not only this receipt page. */
export function RulePublicationPanel({
  publications,
  publication,
  receipts,
  selectedId,
  onSelect,
  onRead,
  onReadReceipts,
}: {
  readonly publications: QuerySnapshot<RuleSetCollection<RulePublication>>;
  readonly publication: QuerySnapshot<RulePublication>;
  readonly receipts: QuerySnapshot<PublicationReceiptPage>;
  readonly selectedId: string | null;
  readonly onSelect: (id: string) => void;
  readonly onRead: () => void;
  readonly onReadReceipts: (page: number) => void;
}) {
  const { t, i18n } = useTranslation(),
    locale = i18n.resolvedLanguage ?? i18n.language;
  return (
    <Panel
      title={t("rules.deployment.publicationsTitle")}
      subtitle={t("rules.deployment.phaseHint")}
      action={
        <ActionButton onClick={onRead}>{t("rules.deployment.refreshPublication")}</ActionButton>
      }
    >
      <div className={styles.content}>
        <RuleQueryView snapshot={publications} onRetry={onRead}>
          {(collection) => (
            <div className={styles.actions}>
              {collection.items.map((item) => (
                <ActionButton
                  key={item.id}
                  data-deployment-publication={item.id}
                  aria-pressed={item.id === selectedId}
                  onClick={() => onSelect(item.id)}
                >
                  {item.id} · {item.targetVersionId}
                </ActionButton>
              ))}
            </div>
          )}
        </RuleQueryView>
        <RuleQueryView snapshot={publication} onRetry={onRead}>
          {(item) => (
            <section data-publication-detail>
              <dl className={styles.facts}>
                {publicationStages(item).map(({ labelKey, phase }) => (
                  <div key={labelKey}>
                    <dt>{t(labelKey)}</dt>
                    <dd>{t(PUBLICATION_STAGE_LABEL[phase.state])}</dd>
                  </div>
                ))}
              </dl>
              <p>
                {item.targetVersionId} · {item.targetChecksum}
              </p>
              <ActionButton data-deployment-receipts onClick={() => onReadReceipts(1)}>
                {t("rules.deployment.readReceipts")}
              </ActionButton>
            </section>
          )}
        </RuleQueryView>
        <RuleQueryView
          snapshot={receipts}
          onRetry={() => onReadReceipts("data" in receipts ? receipts.data.page : 1)}
          partialCopy={{
            title: t("rules.deployment.receiptPartialTitle"),
            description: t("rules.deployment.receiptPartial"),
          }}
        >
          {(page) => (
            <section data-publication-receipts>
              <p>
                {t(
                  page.expected === null
                    ? "rules.deployment.coverageUnknown"
                    : "rules.deployment.coverage",
                  {
                    applied: formatLocaleNumber(page.applied, locale),
                    expected:
                      page.expected === null ? "" : formatLocaleNumber(page.expected, locale),
                    total: formatLocaleNumber(page.total, locale),
                    pending: formatLocaleNumber(page.pending, locale),
                    failed: formatLocaleNumber(page.failed, locale),
                    unknown: formatLocaleNumber(page.unknown, locale),
                    restart: formatLocaleNumber(page.restartRequired, locale),
                  },
                )}
                {page.inventorySource !== null && (
                  <>
                    <br />
                    {t("observation.inventorySource", { source: page.inventorySource })}
                  </>
                )}
              </p>
              <DataTable
                heads={[
                  t("rules.deployment.instance"),
                  t("rules.deployment.processEpoch"),
                  t("rules.deployment.loadedVersion"),
                  t("rules.deployment.receiptStatus"),
                ]}
                rows={page.items.map((item) => (
                  <tr key={item.instanceId}>
                    <td>{item.instanceId}</td>
                    <td>{item.processEpoch ?? t("rules.deployment.notReported")}</td>
                    <td>{item.loadedVersionId ?? t("rules.deployment.notReported")}</td>
                    <td>{t(RECEIPT_STATE_LABEL[item.state])}</td>
                  </tr>
                ))}
              />
              <p>{t("rules.deployment.restartHint")}</p>
              <div className={styles.actions}>
                <ActionButton
                  disabled={page.page <= 1}
                  onClick={() => onReadReceipts(page.page - 1)}
                >
                  {t("rules.deployment.previousPage")}
                </ActionButton>
                <span>
                  {t("rules.deployment.receiptPage", {
                    page: formatLocaleNumber(page.page, locale),
                  })}
                </span>
                <ActionButton
                  disabled={page.page * page.pageSize >= page.total}
                  onClick={() => onReadReceipts(page.page + 1)}
                >
                  {t("rules.deployment.nextPage")}
                </ActionButton>
              </div>
            </section>
          )}
        </RuleQueryView>
      </div>
    </Panel>
  );
}
