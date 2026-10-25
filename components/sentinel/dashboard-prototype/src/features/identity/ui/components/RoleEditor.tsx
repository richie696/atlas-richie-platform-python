import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { useBeforeUnloadGuard } from "../../../../shared/state/useBeforeUnloadGuard";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { AccountManagementWorkflow } from "../../application/accountManagementWorkflow";
import {
  accountRoleIssue,
  createRoleDraft,
  changeRoleDraft,
  reconcileRoleDraft,
  roleDraftIsDirty,
  type AccountRecord,
} from "../../model/accountManagement";
import { ROLE_OPTIONS, roleEditRestrictionCopy } from "../../presentation/rolePresentation";
import { RadioGroup } from "../../../../shared/ui/RadioGroup";
import { ActionButton } from "../../../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../../../shared/ui/FeedbackPanel";
import { AccountCommandFeedback } from "./AccountCommandFeedback";
import {
  getRoleDraftSessionStorage,
  readRoleDraftSession,
  writeRoleDraftSession,
} from "../../state/roleDraftSession";
import styles from "../Identity.module.scss";

/**
 * Keyed by account ID (NOT revision). Refresh cannot silently advance a dirty
 * baseline. Only an explicit cancel/read-latest or confirmed write replaces it.
 * Radio edits are local; server revision and last-admin checks remain authoritative.
 */
export function RoleEditor({
  workflow,
  record,
  sessionEpoch,
}: {
  readonly workflow: AccountManagementWorkflow;
  readonly record: AccountRecord;
  readonly sessionEpoch: string;
}) {
  const { t } = useTranslation(),
    snapshot = useExternalSnapshot(workflow);
  const accountId = record.id;
  const [draft, setDraft] = useState(() => createRoleDraft(record)),
    [draftRestored, setDraftRestored] = useState(false);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      const storage = getRoleDraftSessionStorage();
      if (storage) {
        const stored = readRoleDraftSession(storage, sessionEpoch, accountId);
        if (stored) setDraft(stored);
      }
      setDraftRestored(true);
    });
    return () => {
      active = false;
    };
  }, [sessionEpoch, accountId]);
  const currentDraft = reconcileRoleDraft(record, draft),
    dirty = roleDraftIsDirty(currentDraft);
  const restrictionCopy = roleEditRestrictionCopy(record);
  const roleLocked = record.status === "disabled" || record.builtIn || record.lastActiveAdmin;
  const locked =
    !snapshot.authorized ||
    !draftRestored ||
    snapshot.inspecting ||
    ["pending", "result-unknown", "conflict"].includes(snapshot.mutation.status);
  const clearDraft = useCallback(
    (baseline: AccountRecord) => {
      const clean = createRoleDraft(baseline);
      setDraft(clean);
      const storage = getRoleDraftSessionStorage();
      if (storage) writeRoleDraftSession(storage, sessionEpoch, clean);
    },
    [sessionEpoch],
  );
  useBeforeUnloadGuard(
    dirty ||
      !draftRestored ||
      snapshot.inspecting ||
      ["pending", "result-unknown"].includes(snapshot.mutation.status),
    !draftRestored ||
      snapshot.inspecting ||
      ["pending", "result-unknown"].includes(snapshot.mutation.status),
    () => clearDraft(record),
  );
  // Persist at commit time so a queued passive effect from the prior dirty draft
  // cannot run after a confirmed save and resurrect stale edits in sessionStorage.
  useLayoutEffect(() => {
    if (!draftRestored) return;
    const storage = getRoleDraftSessionStorage();
    if (storage) writeRoleDraftSession(storage, sessionEpoch, currentDraft);
  }, [draftRestored, sessionEpoch, currentDraft]);
  const reset = () => clearDraft(record);
  const inspect = () =>
    void workflow
      .inspect()
      .then((receipt) => {
        if (receipt.status === "completed" && receipt.account.id === record.id)
          clearDraft(receipt.account);
      })
      .catch(() => {});
  const save = () =>
    void workflow
      .setRole(record, currentDraft)
      .then((receipt) => {
        if (receipt.status === "completed") clearDraft(receipt.account);
      })
      .catch(() => {});
  return (
    <section className={styles["role-editor"]} data-role-editor>
      <p
        className={styles["identity-account-summary"]}
        data-account-summary
        data-account-role={record.roleId}
      >
        {record.username} ·{" "}
        {t(record.status === "active" ? "accounts.status.active" : "accounts.status.disabled")}
      </p>
      {restrictionCopy && (
        <FeedbackPanel
          tone="warning"
          copy={{ title: t("roles.restriction.title"), description: t(restrictionCopy) }}
        />
      )}
      <AccountCommandFeedback
        snapshot={snapshot}
        onInspect={inspect}
        onReadLatest={() =>
          void workflow
            .select(record.id)
            .then((latest) => {
              if (latest) clearDraft(latest);
            })
            .catch(() => {})
        }
      />
      {snapshot.mutation.status !== "success" &&
        currentDraft.revision !== record.revision &&
        dirty && (
          <FeedbackPanel
            tone="warning"
            copy={{ title: t("management.title"), description: t("management.conflict") }}
          />
        )}
      <fieldset className={styles["role-fieldset"]} disabled={locked || roleLocked}>
        <RadioGroup
          label={t("roles.field.binding")}
          value={currentDraft.roleId}
          onChange={(roleId) =>
            setDraft((current) => changeRoleDraft(reconcileRoleDraft(record, current), roleId))
          }
          className={styles["role-options"]}
          variant="cards"
          options={ROLE_OPTIONS.map((role) => ({
            value: role.id,
            label: t(role.labelKey),
            description: t(role.descriptionKey),
          }))}
        />
      </fieldset>
      {!roleLocked && (
        <>
          <div className={styles["identity-warning"]}>{t("management.roleImpact")}</div>
          <div className={styles["identity-form-actions"]}>
            <ActionButton disabled={locked || !dirty} onClick={reset}>
              {t("management.discard")}
            </ActionButton>
            <ActionButton
              disabled={locked || !dirty || accountRoleIssue(record, currentDraft.roleId) !== null}
              onClick={save}
            >
              {t("management.saveRole")}
            </ActionButton>
          </div>
        </>
      )}
    </section>
  );
}
