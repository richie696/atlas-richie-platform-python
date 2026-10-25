import { useId, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createSourceRegistrationWorkflow } from "../application/sourceRegistrationWorkflow";
import {
  changeSourceRegistration,
  clearSourceCredentials,
  prepareSourceMutation,
  sourceRegistrationDraft,
  type RegisteredSource,
  type SourceRegistrationDraft,
} from "../model/sourceRegistration";
import {
  SOURCE_CHECK_LABEL,
  SOURCE_CHECK_REASON_LABEL,
} from "../presentation/sourceRegistrationLabels";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
import { useRetryCooldown } from "../../../shared/state/useRetryCooldown";
import { SourceRegistrationFields } from "./SourceRegistrationFields";
import { SourceOperationFeedback } from "./SourceOperationFeedback";
import styles from "./SystemObservation.module.scss";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
/** Mount per captured source revision. Closing/revocation unmounts all secrets; unresolved identity remains in the workflow. */
export function SourceRegistrationDialog({
  workflow,
  record,
  onClose,
}: {
  readonly workflow: ReturnType<typeof createSourceRegistrationWorkflow>;
  readonly record: RegisteredSource | null;
  readonly onClose: () => void;
}) {
  const { t, i18n } = useTranslation(),
    formId = useId(),
    state = useExternalSnapshot(workflow);
  const [draft, setDraft] = useState(() => sourceRegistrationDraft(record)),
    [dirty, setDirty] = useState(false),
    [invalid, setInvalid] = useState(false),
    [checkFailed, setCheckFailed] = useState(false),
    [operationFailed, setOperationFailed] = useState(false);
  const busy = state.command.status === "pending" || state.inspecting,
    unknown = state.command.status === "result-unknown";
  const checkError =
      state.check.status === "error" || state.check.status === "stale"
        ? state.check.error
        : undefined,
    commandError = state.command.status === "error" ? state.command.error : undefined,
    inspectionError = state.inspectionError;
  const checkCoolingDown = useRetryCooldown(checkError, state.checkRetryUntilMs),
    commandCoolingDown = useRetryCooldown(commandError),
    inspectionCoolingDown = useRetryCooldown(inspectionError);
  const checkLoading = state.check.status === "loading" || state.check.status === "refreshing";
  const canSubmit = !busy && !unknown && !commandCoolingDown;
  useBeforeUnloadGuard(dirty || busy || unknown, busy || unknown, () =>
    setDraft((value) => clearSourceCredentials(value)),
  );
  const change = (next: SourceRegistrationDraft) => {
    if (busy || unknown) return;
    workflow.invalidateCheck();
    setDraft(changeSourceRegistration(draft, next));
    setDirty(true);
    setInvalid(false);
    setCheckFailed(false);
    setOperationFailed(false);
  };
  const clear = () => setDraft((value) => clearSourceCredentials(value));
  const close = () => {
    if (!busy) {
      workflow.invalidateCheck();
      clear();
      onClose();
    }
  };
  const check = async () => {
    if (!prepareSourceMutation(draft, record)) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setCheckFailed(false);
    try {
      await workflow.checkSource(draft, record);
    } catch {
      setCheckFailed(true);
    }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    if (!prepareSourceMutation(draft, record)) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setOperationFailed(false);
    try {
      await workflow.submit(draft, record);
      clear();
      setDirty(false);
      onClose();
    } catch {
      if (workflow.getSnapshot().command.status === "result-unknown") clear();
      else setOperationFailed(true);
    }
  };
  const inspect = async () => {
    setOperationFailed(false);
    try {
      const value = await workflow.inspect();
      if (value.status === "completed") {
        clear();
        setDirty(false);
        onClose();
      }
    } catch {
      setOperationFailed(true);
    }
  };
  return (
    <DialogFrame
      isOpen
      onOpenChange={(open) => {
        if (!open) close();
      }}
      isBusy={busy}
      title={t(record ? "system.source.edit" : "system.source.add")}
      subtitle={t("system.source.editHint")}
      width={760}
      actions={
        <>
          <ActionButton disabled={busy} onClick={close}>
            {t("system.source.close")}
          </ActionButton>
          <ActionButton
            disabled={busy || unknown || checkLoading || checkCoolingDown}
            onClick={() => void check()}
          >
            {t("system.source.check")}
          </ActionButton>
          <ActionButton variant="primary" type="submit" form={formId} disabled={!canSubmit}>
            {t("system.source.save")}
          </ActionButton>
        </>
      }
    >
      <form id={formId} className={styles.content} onSubmit={(event) => void submit(event)}>
        <SourceRegistrationFields
          draft={draft}
          editing={record !== null && record.provider === draft.connection.provider}
          disabled={busy || unknown}
          onChange={change}
        />
        <p>{t("system.source.checkHint")}</p>
        {invalid && (
          <FeedbackPanel
            tone="error"
            copy={{
              title: t("system.source.validation"),
              description: t("system.source.validationHint"),
            }}
          />
        )}
        {state.check.status === "loading" && (
          <FeedbackPanel
            tone="info"
            isBusy
            copy={{ title: t("system.source.check"), description: t("system.source.checkPending") }}
          />
        )}
        {"data" in state.check && (
          <FeedbackPanel
            tone={state.check.data.status === "reachable" ? "success" : "warning"}
            copy={{
              title: t(
                state.check.data.status === "reachable"
                  ? "system.source.reachable"
                  : "system.source.unreachable",
              ),
              description: `${formatUtcDateTime(state.check.data.checkedAtMs, i18n.resolvedLanguage ?? i18n.language)} · ${state.check.data.status === "reachable" ? state.check.data.capabilities.map((value) => t(SOURCE_CHECK_LABEL[value])).join(" · ") : t(SOURCE_CHECK_REASON_LABEL[state.check.data.reason])}`,
            }}
          />
        )}
        {checkFailed && (
          <FeedbackPanel
            tone="error"
            copy={{
              title: t("system.source.checkFailed"),
              description: t("system.source.checkFailedHint"),
            }}
          />
        )}
        <SourceOperationFeedback
          state={state}
          failed={operationFailed}
          inspectDisabled={state.inspecting || inspectionCoolingDown}
          inspectCoolingDown={inspectionCoolingDown}
          onInspect={() => void inspect()}
          onReadLatest={() => {
            void workflow.registry.load(null).catch(() => {});
          }}
        />
      </form>
    </DialogFrame>
  );
}
