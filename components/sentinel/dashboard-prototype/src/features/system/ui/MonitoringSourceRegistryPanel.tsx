import { useEffect, useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createMonitoringSourceWorkflow } from "../application/monitoringSourceWorkflow";
import type {
  MonitoringCredentialMaterial,
  MonitoringSourceCandidate,
  MonitoringSourceRecord,
} from "../model/monitoringSource";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable } from "../../../shared/ui/DataTable";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { FormGrid } from "../../../shared/ui/FormGrid";
import { Panel } from "../../../shared/ui/Panel";
import { Select } from "../../../shared/ui/Select";
import { TextField } from "../../../shared/ui/TextField";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
import styles from "./SystemObservation.module.scss";

type Workflow = ReturnType<typeof createMonitoringSourceWorkflow>;
const authenticationModeLabelKey: Record<
  MonitoringSourceRecord["authenticationMode"],
  | "system.monitoringSources.auth.none"
  | "system.monitoringSources.auth.direct-basic"
  | "system.monitoringSources.auth.direct-bearer"
  | "system.monitoringSources.auth.credential-reference"
> = {
  none: "system.monitoringSources.auth.none",
  "direct-basic": "system.monitoringSources.auth.direct-basic",
  "direct-bearer": "system.monitoringSources.auth.direct-bearer",
  "credential-reference": "system.monitoringSources.auth.credential-reference",
};
type Draft = {
  readonly sourceId: string;
  readonly revision: string;
  readonly displayName: string;
  readonly environmentId: string;
  readonly endpoint: string;
  readonly identityLabels: string;
  readonly selectorName: string;
  readonly selectorValue: string;
  readonly scrapeIntervalSeconds: string;
  readonly staleAfterSeconds: string;
  readonly authenticationMode: MonitoringSourceRecord["authenticationMode"];
  readonly credentialUpdate: "keep" | "replace" | "clear";
  readonly username: string;
  readonly password: string;
  readonly bearerToken: string;
  readonly reference: string;
  readonly enabled: boolean;
  readonly skipCheck: boolean;
};

const emptyDraft = (): Draft => ({
  sourceId: crypto.randomUUID(),
  revision: `candidate-${crypto.randomUUID()}`,
  displayName: "",
  environmentId: "",
  endpoint: "",
  identityLabels: "instance",
  selectorName: "job",
  selectorValue: "node-exporter",
  scrapeIntervalSeconds: "15",
  staleAfterSeconds: "90",
  authenticationMode: "none",
  credentialUpdate: "clear",
  username: "",
  password: "",
  bearerToken: "",
  reference: "",
  enabled: true,
  skipCheck: false,
});

function candidateFrom(draft: Draft): MonitoringSourceCandidate {
  const identityLabels = draft.identityLabels.split(",").map((label) => label.trim());
  const selectorLabels = draft.selectorName.trim()
    ? [{ name: draft.selectorName.trim(), value: draft.selectorValue.trim() }]
    : [];
  const credentialConfigured =
    draft.authenticationMode !== "none" &&
    (draft.credentialUpdate === "keep" ||
      (draft.authenticationMode === "direct-basic" &&
        !!draft.username.trim() &&
        !!draft.password) ||
      (draft.authenticationMode === "direct-bearer" && !!draft.bearerToken) ||
      (draft.authenticationMode === "credential-reference" && !!draft.reference.trim()));
  return {
    sourceId: draft.sourceId.trim(),
    revision: draft.revision,
    displayName: draft.displayName.trim(),
    environmentId: draft.environmentId.trim(),
    endpoint: draft.endpoint.trim(),
    provider: "prometheus-compatible",
    profile: "node-exporter-v1",
    authenticationMode: draft.authenticationMode,
    credentialConfigured,
    enabled: draft.enabled,
    identityLabels,
    selectorLabels,
    scrapeIntervalSeconds: Number(draft.scrapeIntervalSeconds),
    staleAfterSeconds: Number(draft.staleAfterSeconds),
  };
}

function credentialsFrom(draft: Draft): MonitoringCredentialMaterial {
  if (draft.credentialUpdate === "keep" || draft.authenticationMode === "none") return null;
  if (draft.authenticationMode === "direct-basic")
    return { username: draft.username, password: draft.password };
  if (draft.authenticationMode === "direct-bearer") return { bearerToken: draft.bearerToken };
  return { reference: draft.reference };
}

function draftFromRecord(record: MonitoringSourceRecord): Draft {
  return {
    ...emptyDraft(),
    sourceId: record.id,
    revision: record.revision,
    displayName: record.displayName,
    environmentId: record.environmentId,
    endpoint: record.endpointOrigin ?? "",
    identityLabels: record.identityLabels?.join(", ") ?? "instance",
    selectorName: record.selectorLabels?.[0]?.name ?? "job",
    selectorValue: record.selectorLabels?.[0]?.value ?? "node-exporter",
    scrapeIntervalSeconds: String(record.scrapeIntervalSeconds ?? 15),
    staleAfterSeconds: String(record.staleAfterSeconds ?? 90),
    authenticationMode: record.authenticationMode,
    credentialUpdate: record.credentialConfigured ? "keep" : "clear",
    enabled: record.enabled,
    skipCheck: record.credentialConfigured,
  };
}

/** Prometheus source registry editor. Form secrets stay in local component state and are cleared on close. */
export function MonitoringSourceRegistryPanel({
  workflow,
  canManage,
  demoMode,
}: {
  readonly workflow: Workflow;
  readonly canManage: boolean;
  readonly demoMode: boolean;
}) {
  const state = useExternalSnapshot(workflow);
  const { t } = useTranslation();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState<MonitoringSourceRecord | null>(null);
  const [checking, setChecking] = useState(false);
  const [receipt, setReceipt] = useState<Awaited<ReturnType<Workflow["check"]>> | null>(null);
  const [failed, setFailed] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<MonitoringSourceRecord | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const formId = useId();
  const busy = checking || state.busyRequestKey !== null;
  useBeforeUnloadGuard(draft !== null || busy, busy, () => setDraft(null));

  useEffect(() => {
    void workflow.refresh().catch(() => {});
    return () => {};
  }, [workflow]);

  const open = (record?: MonitoringSourceRecord) => {
    setReceipt(null);
    setFailed(false);
    setMessage(null);
    setEditing(record ?? null);
    if (!record) setDraft(emptyDraft());
    else
      void workflow
        .readSource(record.id)
        .then((detail) => {
          setDraft(draftFromRecord(detail));
        })
        .catch(() => setFailed(true));
  };

  const close = () => {
    if (busy) return;
    setDraft(null);
    setEditing(null);
    setReceipt(null);
    setFailed(false);
  };

  const check = async () => {
    if (!draft) return;
    setChecking(true);
    setReceipt(null);
    setFailed(false);
    try {
      const candidate = candidateFrom(draft);
      const result = await workflow.check(candidate, credentialsFrom(draft));
      setReceipt(result);
    } catch {
      setFailed(true);
    } finally {
      setChecking(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft || busy) return;
    setFailed(false);
    const candidate = candidateFrom(draft);
    const canUseReceipt =
      receipt?.sourceId === candidate.sourceId &&
      receipt.sourceRevision === candidate.revision &&
      receipt.result.connection === "reachable" &&
      receipt.result.queryApi === "available" &&
      receipt.result.profile === "supported";
    const skipCheck = draft.skipCheck || (editing !== null && draft.credentialUpdate === "keep");
    if (!skipCheck && !canUseReceipt) {
      setFailed(true);
      return;
    }
    try {
      const operation = await workflow.mutate({
        kind: editing ? "update" : "create",
        source: candidate,
        credentials: credentialsFrom(draft),
        credentialUpdate: draft.credentialUpdate,
        checkId: canUseReceipt ? (receipt?.checkId ?? null) : null,
        skipCheck,
        ...(editing ? { expectedRevision: editing.revision } : {}),
      });
      if (operation.status === "completed") {
        setMessage(
          t(
            operation.verified
              ? "system.monitoringSources.savedVerified"
              : "system.monitoringSources.savedUnverified",
          ),
        );
        setDraft(null);
        setEditing(null);
        setReceipt(null);
      } else setFailed(true);
    } catch {
      // Unknown outcomes retain only the request key in the workflow; secret inputs are cleared.
      setDraft((current) =>
        current ? { ...current, password: "", bearerToken: "", reference: "" } : null,
      );
      setFailed(true);
    }
  };

  const setEnabled = async (record: MonitoringSourceRecord) => {
    try {
      const operation = await workflow.mutate({
        kind: "set-enabled",
        sourceId: record.id,
        expectedRevision: record.revision,
        enabled: !record.enabled,
      });
      if (operation.status === "completed") setMessage(t("system.monitoringSources.stateUpdated"));
      else setFailed(true);
    } catch {
      setFailed(true);
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    try {
      const operation = await workflow.mutate({
        kind: "delete",
        sourceId: deleteTarget.id,
        expectedRevision: deleteTarget.revision,
      });
      if (operation.status === "completed") setMessage(t("system.monitoringSources.deleted"));
      else setFailed(true);
    } catch {
      setFailed(true);
    }
    setDeleteTarget(null);
  };

  return (
    <Panel
      title={t("system.monitoringSources.title")}
      subtitle={t("system.monitoringSources.subtitle")}
      action={
        <div className={styles["registry-panel-actions"]}>
          <ActionButton
            disabled={state.loading || busy}
            onClick={() => void workflow.refresh().catch(() => {})}
          >
            {t("system.monitoringSources.refresh")}
          </ActionButton>
          {canManage && (
            <ActionButton disabled={busy} onClick={() => open()}>
              {t("system.monitoringSources.add")}
            </ActionButton>
          )}
        </div>
      }
    >
      <div className={styles.content}>
        {demoMode && <p role="note">{t("system.monitoringSources.mockNotice")}</p>}
        {state.error === "read_failed" && (
          <FeedbackPanel
            tone="warning"
            copy={{
              title: t("system.monitoringSources.readFailed"),
              description: t("system.monitoringSources.retryHint"),
            }}
          />
        )}
        {message && (
          <FeedbackPanel
            tone="success"
            copy={{ title: message, description: t("system.monitoringSources.noSecretReadback") }}
          />
        )}
        {failed && (
          <FeedbackPanel
            tone="error"
            copy={{
              title: t("system.monitoringSources.operationFailed"),
              description:
                state.lastOperation?.reason === "source_in_use"
                  ? t("system.monitoringSources.sourceInUse")
                  : t("system.monitoringSources.safeFailure"),
            }}
          />
        )}
        {state.error === "unknown_outcome" && state.unresolvedRequestKey && (
          <FeedbackPanel
            tone="warning"
            copy={{
              title: t("system.monitoringSources.unknownOutcome"),
              description: `${t("system.monitoringSources.requestKey")}: ${state.unresolvedRequestKey}`,
            }}
            actions={
              <ActionButton
                onClick={() =>
                  void workflow.inspect(state.unresolvedRequestKey!).catch(() => setFailed(true))
                }
              >
                {t("system.monitoringSources.inspect")}
              </ActionButton>
            }
          />
        )}
        <DataTable
          heads={[
            t("system.monitoringSources.name"),
            t("system.monitoringSources.environment"),
            t("system.monitoringSources.authentication"),
            t("system.monitoringSources.status"),
            t("system.monitoringSources.actions"),
          ]}
          rows={state.items.map((record) => (
            <tr key={record.id} data-monitoring-source-id={record.id}>
              <td>
                {record.displayName}
                <br />
                {record.id}
              </td>
              <td>{record.environmentId}</td>
              <td>
                {t(authenticationModeLabelKey[record.authenticationMode])} ·{" "}
                {t(
                  record.credentialConfigured
                    ? "system.monitoringSources.credentialSet"
                    : "system.monitoringSources.credentialMissing",
                )}
              </td>
              <td>
                {t(
                  record.enabled
                    ? "system.monitoringSources.enabled"
                    : "system.monitoringSources.disabled",
                )}
                {record.enabled ? "" : ` · ${t("system.monitoringSources.unavailable")}`}
              </td>
              <td>
                <div className={styles.actions}>
                  {canManage && (
                    <>
                      <ActionButton
                        disabled={busy || state.unresolvedRequestKey !== null}
                        onClick={() => open(record)}
                      >
                        {t("system.monitoringSources.edit")}
                      </ActionButton>
                      <ActionButton
                        disabled={busy || state.unresolvedRequestKey !== null}
                        onClick={() => void setEnabled(record)}
                      >
                        {t(
                          record.enabled
                            ? "system.monitoringSources.disable"
                            : "system.monitoringSources.enable",
                        )}
                      </ActionButton>
                      <ActionButton
                        disabled={busy || state.unresolvedRequestKey !== null}
                        onClick={() => setDeleteTarget(record)}
                      >
                        {t("system.monitoringSources.delete")}
                      </ActionButton>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
        />
      </div>
      {draft && (
        <DialogFrame
          isOpen
          onOpenChange={(value) => {
            if (!value) close();
          }}
          isBusy={busy}
          title={t(editing ? "system.monitoringSources.edit" : "system.monitoringSources.add")}
          subtitle={t("system.monitoringSources.dialogHint")}
          width={820}
          actions={
            <>
              <ActionButton disabled={busy} onClick={close}>
                {t("system.source.close")}
              </ActionButton>
              <ActionButton
                disabled={busy || draft.credentialUpdate === "keep"}
                onClick={() => void check()}
              >
                {t("system.source.check")}
              </ActionButton>
              <ActionButton
                variant="primary"
                type="submit"
                form={formId}
                disabled={busy || state.unresolvedRequestKey !== null}
              >
                {t("system.source.save")}
              </ActionButton>
            </>
          }
        >
          <form id={formId} className={styles.content} onSubmit={(event) => void submit(event)}>
            <FormGrid>
              <TextField
                label={t("system.monitoringSources.name")}
                value={draft.displayName}
                onChange={(value) => {
                  setDraft({ ...draft, displayName: value });
                  setReceipt(null);
                }}
              />
              <TextField
                label={t("system.monitoringSources.environment")}
                value={draft.environmentId}
                onChange={(value) => {
                  setDraft({ ...draft, environmentId: value });
                  setReceipt(null);
                }}
              />
              <TextField
                label={t("system.monitoringSources.endpoint")}
                hint={
                  editing
                    ? t("system.monitoringSources.endpointEditHint")
                    : t("system.monitoringSources.endpointHint")
                }
                value={draft.endpoint}
                onChange={(value) => {
                  setDraft({ ...draft, endpoint: value });
                  setReceipt(null);
                }}
              />
              <TextField
                label={t("system.monitoringSources.identityLabels")}
                value={draft.identityLabels}
                onChange={(value) => {
                  setDraft({ ...draft, identityLabels: value });
                  setReceipt(null);
                }}
              />
              <TextField
                label={t("system.monitoringSources.selectorName")}
                value={draft.selectorName}
                onChange={(value) => {
                  setDraft({ ...draft, selectorName: value });
                  setReceipt(null);
                }}
              />
              <TextField
                label={t("system.monitoringSources.selectorValue")}
                value={draft.selectorValue}
                onChange={(value) => {
                  setDraft({ ...draft, selectorValue: value });
                  setReceipt(null);
                }}
              />
              <TextField
                label={t("system.monitoringSources.scrapeInterval")}
                value={draft.scrapeIntervalSeconds}
                onChange={(value) => {
                  setDraft({ ...draft, scrapeIntervalSeconds: value });
                  setReceipt(null);
                }}
              />
              <TextField
                label={t("system.monitoringSources.staleAfter")}
                value={draft.staleAfterSeconds}
                onChange={(value) => {
                  setDraft({ ...draft, staleAfterSeconds: value });
                  setReceipt(null);
                }}
              />
              {editing && (
                <Select
                  label={t("system.monitoringSources.credentialUpdate")}
                  value={draft.credentialUpdate}
                  options={[
                    { value: "keep", label: t("system.monitoringSources.keepCredential") },
                    { value: "replace", label: t("system.monitoringSources.replaceCredential") },
                    { value: "clear", label: t("system.monitoringSources.clearCredential") },
                  ]}
                  onChange={(credentialUpdate) => {
                    setDraft({
                      ...draft,
                      credentialUpdate,
                      authenticationMode:
                        credentialUpdate === "clear" ? "none" : draft.authenticationMode,
                      skipCheck: credentialUpdate === "keep",
                    });
                    setReceipt(null);
                  }}
                />
              )}
              {draft.credentialUpdate !== "keep" && (
                <Select
                  label={t("system.monitoringSources.authentication")}
                  value={draft.authenticationMode}
                  options={[
                    { value: "none", label: t("system.monitoringSources.auth.none") },
                    {
                      value: "direct-basic",
                      label: t("system.monitoringSources.auth.direct-basic"),
                    },
                    {
                      value: "direct-bearer",
                      label: t("system.monitoringSources.auth.direct-bearer"),
                    },
                    {
                      value: "credential-reference",
                      label: t("system.monitoringSources.auth.credential-reference"),
                    },
                  ]}
                  onChange={(authenticationMode) => {
                    setDraft({
                      ...draft,
                      authenticationMode,
                      credentialUpdate: authenticationMode === "none" ? "clear" : "replace",
                    });
                    setReceipt(null);
                  }}
                />
              )}
              {!editing && (
                <Select
                  label={t("system.monitoringSources.authentication")}
                  value={draft.authenticationMode}
                  options={[
                    { value: "none", label: t("system.monitoringSources.auth.none") },
                    {
                      value: "direct-basic",
                      label: t("system.monitoringSources.auth.direct-basic"),
                    },
                    {
                      value: "direct-bearer",
                      label: t("system.monitoringSources.auth.direct-bearer"),
                    },
                    {
                      value: "credential-reference",
                      label: t("system.monitoringSources.auth.credential-reference"),
                    },
                  ]}
                  onChange={(authenticationMode) => {
                    setDraft({
                      ...draft,
                      authenticationMode,
                      credentialUpdate: authenticationMode === "none" ? "clear" : "replace",
                    });
                    setReceipt(null);
                  }}
                />
              )}
              {draft.credentialUpdate !== "keep" && draft.authenticationMode === "direct-basic" && (
                <>
                  <TextField
                    label={t("system.monitoringSources.username")}
                    value={draft.username}
                    onChange={(username) => setDraft({ ...draft, username })}
                  />
                  <TextField
                    label={t("system.monitoringSources.password")}
                    type="password"
                    autoComplete="new-password"
                    value={draft.password}
                    onChange={(password) => setDraft({ ...draft, password })}
                  />
                </>
              )}
              {draft.credentialUpdate !== "keep" &&
                draft.authenticationMode === "direct-bearer" && (
                  <TextField
                    label={t("system.monitoringSources.bearerToken")}
                    type="password"
                    autoComplete="new-password"
                    value={draft.bearerToken}
                    onChange={(bearerToken) => setDraft({ ...draft, bearerToken })}
                  />
                )}
              {draft.credentialUpdate !== "keep" &&
                draft.authenticationMode === "credential-reference" && (
                  <TextField
                    label={t("system.monitoringSources.credentialReference")}
                    type="password"
                    autoComplete="new-password"
                    value={draft.reference}
                    onChange={(reference) => setDraft({ ...draft, reference })}
                  />
                )}
            </FormGrid>
            {editing && <p>{t("system.monitoringSources.endpointEditHint")}</p>}
            {draft.credentialUpdate === "keep" && (
              <p>{t("system.monitoringSources.keepCredentialHint")}</p>
            )}
            <label className={styles.inlineOption}>
              <input
                type="checkbox"
                checked={draft.skipCheck}
                disabled={draft.credentialUpdate === "keep"}
                onChange={(event) => {
                  setDraft({ ...draft, skipCheck: event.currentTarget.checked });
                  setReceipt(null);
                }}
              />
              {t("system.monitoringSources.skipCheck")}
            </label>
            {receipt && (
              <FeedbackPanel
                tone={
                  receipt.result.connection === "reachable" &&
                  receipt.result.queryApi === "available" &&
                  receipt.result.profile === "supported"
                    ? "success"
                    : "warning"
                }
                copy={{
                  title: t("system.monitoringSources.checkResult"),
                  description: `${receipt.result.connection} · ${receipt.result.queryApi} · ${receipt.result.profile}`,
                }}
              />
            )}
            {checking && (
              <FeedbackPanel
                tone="info"
                isBusy
                copy={{
                  title: t("system.source.check"),
                  description: t("system.monitoringSources.checking"),
                }}
              />
            )}
            {failed && (
              <FeedbackPanel
                tone="error"
                copy={{
                  title: t("system.monitoringSources.operationFailed"),
                  description: t("system.monitoringSources.safeFailure"),
                }}
              />
            )}
          </form>
        </DialogFrame>
      )}
      {deleteTarget && (
        <DialogFrame
          isOpen
          onOpenChange={(value) => {
            if (!value) setDeleteTarget(null);
          }}
          title={t("system.monitoringSources.confirmDelete")}
          subtitle={deleteTarget.displayName}
          width={520}
          actions={
            <>
              <ActionButton onClick={() => setDeleteTarget(null)}>
                {t("system.source.close")}
              </ActionButton>
              <ActionButton variant="primary" disabled={busy} onClick={() => void remove()}>
                {t("system.monitoringSources.delete")}
              </ActionButton>
            </>
          }
        >
          <p className={styles.content}>{t("system.monitoringSources.deleteHint")}</p>
        </DialogFrame>
      )}
    </Panel>
  );
}
