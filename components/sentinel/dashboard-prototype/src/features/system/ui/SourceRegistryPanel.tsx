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
import styles from "./SystemObservation.module.scss";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
/** Administrative registry, separate from connection health and one-time setup. No credential readback. */
export function SourceRegistryPanel({
  workflow,
}: {
  readonly workflow: ReturnType<typeof createSourceRegistrationWorkflow>;
}) {
  const state = useExternalSnapshot(workflow),
    { t } = useTranslation();
  return state.authorized ? (
    <SourceRegistrySurface workflow={workflow} />
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
}: {
  readonly workflow: ReturnType<typeof createSourceRegistrationWorkflow>;
}) {
  const { t, i18n } = useTranslation(),
    state = useExternalSnapshot(workflow);
  const [intent, setIntent] = useState<{
      readonly owner: typeof workflow;
      readonly record: RegisteredSource | null;
    } | null>(null),
    [failed, setFailed] = useState(false);
  const locked = state.inspecting || ["pending", "result-unknown"].includes(state.command.status),
    fresh = state.registry.status === "ready" || state.registry.status === "empty";
  const open = state.authorized && intent?.owner === workflow;
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
        <ActionButton
          disabled={!state.authorized || !fresh || locked}
          onClick={() => {
            workflow.invalidateCheck();
            setIntent({ owner: workflow, record: null });
          }}
        >
          {t("system.source.add")}
        </ActionButton>
      }
    >
      <div className={styles.content}>
        <p role="note">{t("system.source.mockNotice")}</p>
        <SystemQueryView snapshot={state.registry} onRetry={refresh}>
          {(value) => (
            <>
              <p>
                {t("system.observed.readAt")}{" "}
                <time dateTime={new Date(value.asOfMs).toISOString()}>
                  {formatUtcDateTime(value.asOfMs, i18n.resolvedLanguage ?? i18n.language)}
                </time>
              </p>
              <ActionButton onClick={refresh}>{t("system.source.refresh")}</ActionButton>
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
                      <ActionButton
                        disabled={!fresh || locked}
                        onClick={() => {
                          workflow.invalidateCheck();
                          setIntent({ owner: workflow, record });
                        }}
                      >
                        {t("system.source.edit")}
                      </ActionButton>
                    </td>
                  </tr>
                ))}
              />
            </>
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
    </Panel>
  );
}
