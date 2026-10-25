import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createSourceRegistrationWorkflow } from "../application/sourceRegistrationWorkflow";
import type { RegisteredSource } from "../model/sourceRegistration";
import { SOURCE_AUTH_LABEL } from "../presentation/sourceRegistrationLabels";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable } from "../../../shared/ui/DataTable";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
import { SystemQueryView } from "./SystemQueryView";
import { SourceRegistrationDialog } from "./SourceRegistrationDialog";
import { SourceOperationFeedback } from "./SourceOperationFeedback";
import { SourceDeletionDialog } from "./SourceDeletionDialog";
import styles from "./SystemObservation.module.scss";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
/** Administrative registry, separate from connection health and one-time setup. No credential readback. */
export function SourceRegistryPanel({
  workflow,
  demoMode,
}: {
  readonly workflow: ReturnType<typeof createSourceRegistrationWorkflow>;
  readonly demoMode: boolean;
}) {
  const state = useExternalSnapshot(workflow),
    { t } = useTranslation();
  return state.authorized ? (
    <SourceRegistrySurface workflow={workflow} demoMode={demoMode} />
  ) : (
    <FeedbackPanel
      tone="warning"
      copy={{ title: t("system.source.title"), description: t("system.observed.readDenied") }}
    />
  );
}
/** Revocation unmounts modal intent and credential-local state, even when the same session regains access. */
function SourceRegistrySurface({
  workflow,
  demoMode,
}: {
  readonly workflow: ReturnType<typeof createSourceRegistrationWorkflow>;
  readonly demoMode: boolean;
}) {
  const { t, i18n } = useTranslation(),
    state = useExternalSnapshot(workflow);
  const [intent, setIntent] = useState<{
      readonly owner: typeof workflow;
      readonly record: RegisteredSource | null;
    } | null>(null),
    [deleteIntent, setDeleteIntent] = useState<{
      readonly owner: typeof workflow;
      readonly record: RegisteredSource;
    } | null>(null),
    [failed, setFailed] = useState(false);
  const locked = state.inspecting || ["pending", "result-unknown"].includes(state.command.status),
    fresh = state.registry.status === "ready" || state.registry.status === "empty";
  const open = state.authorized && intent?.owner === workflow,
    deleteOpen = state.authorized && deleteIntent?.owner === workflow;
  useBeforeUnloadGuard(locked, locked);
  useEffect(() => {
    if (state.authorized) void workflow.registry.load(null).catch(() => {});
    return () => workflow.registry.cancel();
  }, [workflow, state.authorized]);
  const refresh = () => void workflow.registry.load(null).catch(() => {});
  async function inspect() {
    setFailed(false);
    try {
      await workflow.inspect();
    } catch {
      setFailed(true);
    }
  }
  return (
    <Panel
      title={t("system.source.title")}
      subtitle={t("system.source.subtitle")}
      action={
        <div className={styles["registry-panel-actions"]}>
          <ActionButton disabled={state.registry.status === "loading" || locked} onClick={refresh}>
            {t("system.source.refresh")}
          </ActionButton>
          <ActionButton
            disabled={!state.authorized || !fresh || locked}
            onClick={() => {
              workflow.invalidateCheck();
              setIntent({ owner: workflow, record: null });
            }}
          >
            {t("system.source.add")}
          </ActionButton>
        </div>
      }
    >
      <div className={styles.content}>
        {demoMode && <p role="note">{t("system.source.mockNotice")}</p>}
        <SystemQueryView snapshot={state.registry} onRetry={refresh}>
          {(value) => (
            <div className={styles["source-registry-body"]}>
              <p>
                {t("system.observed.readAt")}{" "}
                <time dateTime={new Date(value.asOfMs).toISOString()}>
                  {formatUtcDateTime(value.asOfMs, i18n.resolvedLanguage ?? i18n.language)}
                </time>
              </p>
              <DataTable
                heads={[
                  t("system.source.name"),
                  t("system.source.provider"),
                  t("system.source.endpoint"),
                  t("system.source.location"),
                  t("system.source.authentication"),
                  t("system.source.revision"),
                  t("system.source.action"),
                ]}
                rows={value.items.map((record) => (
                  <tr key={record.id} data-source-id={record.id}>
                    <td>
                      {record.name}
                      <br />
                      {record.id}
                    </td>
                    <td>{record.provider === "nacos" ? "Nacos" : "Consul"}</td>
                    <td>{record.endpoint}</td>
                    <td>{record.provider === "nacos" ? record.namespace : record.datacenter}</td>
                    <td>
                      {t(SOURCE_AUTH_LABEL[record.authenticationMode])}
                      <br />
                      {t(
                        record.credentialConfigured
                          ? "system.source.configured"
                          : "system.source.noCredential",
                      )}
                    </td>
                    <td>{record.revision}</td>
                    <td>
                      <div className={styles.actions}>
                        <ActionButton
                          disabled={!fresh || locked}
                          onClick={() => {
                            workflow.invalidateCheck();
                            setIntent({ owner: workflow, record });
                          }}
                        >
                          {t("system.source.edit")}
                        </ActionButton>
                        <ActionButton
                          disabled={!fresh || locked}
                          onClick={() => setDeleteIntent({ owner: workflow, record })}
                        >
                          {t("system.source.delete")}
                        </ActionButton>
                      </div>
                    </td>
                  </tr>
                ))}
              />
            </div>
          )}
        </SystemQueryView>
        {!open && (
          <SourceOperationFeedback
            state={state}
            failed={failed}
            onInspect={() => void inspect()}
            onReadLatest={refresh}
          />
        )}
      </div>
      {open && (
        <SourceRegistrationDialog
          key={intent.record?.revision ?? "new"}
          workflow={workflow}
          record={intent.record}
          onClose={() => setIntent(null)}
        />
      )}
      {deleteOpen && deleteIntent && (
        <SourceDeletionDialog
          key={`${deleteIntent.record.id}:${deleteIntent.record.revision}`}
          workflow={workflow}
          record={deleteIntent.record}
          onClose={() => setDeleteIntent(null)}
        />
      )}
    </Panel>
  );
}
