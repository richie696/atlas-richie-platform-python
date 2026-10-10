import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { QueryResource } from "../../../shared/state/queryResource";
import { useQueryResource } from "../../../shared/state/useQueryResource";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable } from "../../../shared/ui/DataTable";
import { FormGrid } from "../../../shared/ui/FormGrid";
import { TextField } from "../../../shared/ui/TextField";
import { Select } from "../../../shared/ui/Select";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import {
  AUDIT_ACTION,
  AUDIT_RESULT,
  auditQueryKey,
  type AuditQuery,
  type AuditPage,
  type AuditRecord,
} from "../model/systemObservation";
import { auditFilterDraft, applyAuditFilters } from "../model/auditFilters";
import { AUDIT_ACTION_LABEL_KEY, AUDIT_RESULT_LABEL_KEY } from "../presentation/observationLabels";
import { SystemQueryView } from "./SystemQueryView";
import styles from "./SystemObservation.module.scss";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
interface Props {
  readonly resource: QueryResource<AuditQuery, AuditPage>;
  readonly query: AuditQuery;
  readonly onQueryChange: (query: AuditQuery) => void;
  readonly onPublication: (record: AuditRecord) => void;
}
/** Audit's own bounded window/filters are controlled by its feature owner. Hidden/denied facts cannot authorize links or paging. */
export function ObservedAuditPanel(props: Props) {
  const { startMs, endMs, actorId, action, result, page, pageSize } = props.query;
  const query = useMemo(
    () => ({ startMs, endMs, actorId, action, result, page, pageSize }),
    [startMs, endMs, actorId, action, result, page, pageSize],
  );
  const state = useQueryResource(props.resource, query),
    { t, i18n } = useTranslation(),
    read = () => void props.resource.load(query).catch(() => {});
  const current =
    "data" in state && auditQueryKey(state.data.query) === auditQueryKey(query) ? state.data : null;
  return (
    <Panel
      title={t("system.audit.title")}
      subtitle={t("system.audit.hint")}
      action={<ActionButton onClick={read}>{t("system.audit.refresh")}</ActionButton>}
    >
      <div className={styles.content}>
        {state.status !== "denied" && (
          <AuditFilters
            key={JSON.stringify([startMs, endMs, actorId, action, result])}
            query={query}
            onApply={props.onQueryChange}
          />
        )}
        {current && (
          <p>
            {t("system.audit.total", {
              total: current.total,
              page: current.query.page,
              shown: current.items.length,
            })}
          </p>
        )}
        <SystemQueryView snapshot={state} onRetry={read}>
          {(value) => (
            <DataTable
              heads={[
                t("system.audit.time"),
                t("system.audit.actor"),
                t("system.audit.action"),
                t("system.audit.target"),
                t("system.audit.result"),
                t("system.audit.correlation"),
              ]}
              rows={value.items.map((record) => (
                <tr key={record.id} data-system-audit={record.id}>
                  <td>
                    <time dateTime={new Date(record.occurredAtMs).toISOString()}>
                      {formatUtcDateTime(
                        record.occurredAtMs,
                        i18n.resolvedLanguage ?? i18n.language,
                      )}
                    </time>
                  </td>
                  <td>{record.actorId ?? t("system.audit.systemActor")}</td>
                  <td>{t(AUDIT_ACTION_LABEL_KEY[record.action])}</td>
                  <td>{record.targetId}</td>
                  <td>{t(AUDIT_RESULT_LABEL_KEY[record.result])}</td>
                  <td>
                    <div className={styles.correlation}>
                      <span>{record.requestId}</span>
                      {record.publicationId !== null && (
                        <ActionButton onClick={() => props.onPublication(record)}>
                          {t("system.audit.openPublication")}
                        </ActionButton>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            />
          )}
        </SystemQueryView>
        <div className={styles.actions}>
          <ActionButton
            data-audit-previous
            disabled={state.status === "denied" || page <= 1}
            onClick={() => props.onQueryChange({ ...query, page: page - 1 })}
          >
            {t("system.audit.previous")}
          </ActionButton>
          <ActionButton
            data-audit-next
            disabled={!current || page * pageSize >= current.total}
            onClick={() => props.onQueryChange({ ...query, page: page + 1 })}
          >
            {t("system.audit.next")}
          </ActionButton>
        </div>
      </div>
    </Panel>
  );
}
/** Apply is explicit, so invalid date text remains editable rather than instantly replacing the active query. */
function AuditFilters({
  query,
  onApply,
}: {
  readonly query: AuditQuery;
  readonly onApply: (query: AuditQuery) => void;
}) {
  const [draft, setDraft] = useState(() => auditFilterDraft(query)),
    [invalid, setInvalid] = useState(false),
    { t } = useTranslation();
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const next = applyAuditFilters(draft, query);
        setInvalid(next === null);
        if (next) onApply(next);
      }}
    >
      <FormGrid>
        <TextField
          label={t("system.audit.start")}
          hint={t("system.audit.utcHint")}
          value={draft.startUtc}
          onChange={(value) => setDraft({ ...draft, startUtc: value })}
        />
        <TextField
          label={t("system.audit.end")}
          hint={t("system.audit.utcHint")}
          value={draft.endUtc}
          onChange={(value) => setDraft({ ...draft, endUtc: value })}
        />
        <TextField
          label={t("system.audit.actorFilter")}
          value={draft.actorId}
          onChange={(value) => setDraft({ ...draft, actorId: value })}
        />
        <Select
          label={t("system.audit.actionFilter")}
          value={draft.action}
          options={[
            { value: "", label: t("system.audit.allActions") },
            ...Object.values(AUDIT_ACTION).map((value) => ({
              value,
              label: t(AUDIT_ACTION_LABEL_KEY[value]),
            })),
          ]}
          onChange={(value) => setDraft({ ...draft, action: value })}
        />
        <Select
          label={t("system.audit.resultFilter")}
          value={draft.result}
          options={[
            { value: "", label: t("system.audit.allResults") },
            ...Object.values(AUDIT_RESULT).map((value) => ({
              value,
              label: t(AUDIT_RESULT_LABEL_KEY[value]),
            })),
          ]}
          onChange={(value) => setDraft({ ...draft, result: value })}
        />
      </FormGrid>
      {invalid && (
        <FeedbackPanel
          tone="warning"
          copy={{
            title: t("system.audit.invalidTitle"),
            description: t("system.audit.invalidHint"),
          }}
        />
      )}
      <ActionButton type="submit">{t("system.audit.apply")}</ActionButton>
    </form>
  );
}
