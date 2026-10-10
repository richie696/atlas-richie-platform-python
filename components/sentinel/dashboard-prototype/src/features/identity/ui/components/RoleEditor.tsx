import { useState } from "react";
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
import styles from "../Identity.module.scss";

/**
 * Keyed by account ID (NOT revision). Refresh cannot silently advance a dirty
 * baseline. Only an explicit cancel/read-latest or confirmed write replaces it.
 * Radio edits are local; server revision and last-admin checks remain authoritative.
 */
export function RoleEditor({
  workflow,
  record,
}: {
  readonly workflow: AccountManagementWorkflow;
  readonly record: AccountRecord;
}) {
  const { t } = useTranslation(),
    snapshot = useExternalSnapshot(workflow);
  const [draft, setDraft] = useState(() => createRoleDraft(record));
  const currentDraft = reconcileRoleDraft(record, draft),
    dirty = roleDraftIsDirty(currentDraft);
  const restrictionCopy = roleEditRestrictionCopy(record);
  const locked =
    !snapshot.authorized ||
    snapshot.inspecting ||
    ["pending", "result-unknown"].includes(snapshot.mutation.status);
  useBeforeUnloadGuard(
    dirty ||
      snapshot.inspecting ||
      ["pending", "result-unknown"].includes(snapshot.mutation.status),
    snapshot.inspecting || ["pending", "result-unknown"].includes(snapshot.mutation.status),
    () => setDraft(createRoleDraft(record)),
  );
  const reset = () => setDraft(createRoleDraft(record));
  const inspect = () =>
    void workflow
      .inspect()
      .then((receipt) => {
        if (receipt.status === "completed" && receipt.account.id === record.id)
          setDraft(createRoleDraft(receipt.account));
      })
      .catch(() => {});
  const save = () =>
    void workflow
      .setRole(record, currentDraft)
      .then((receipt) => {
        if (receipt.status === "completed") setDraft(createRoleDraft(receipt.account));
      })
      .catch(() => {});
  return (
    <section data-role-editor>
      <p className={styles["identity-account-summary"]}>
        {record.username} ·{" "}
        {t(record.status === "active" ? "accounts.status.active" : "accounts.status.disabled")}
      </p>
      {restrictionCopy && (
        <FeedbackPanel
          tone="warning"
          copy={{ title: t("roles.bindingPanel.title"), description: t(restrictionCopy) }}
        />
      )}
      <AccountCommandFeedback
        snapshot={snapshot}
        onInspect={inspect}
        onReadLatest={() =>
          void workflow
            .select(record.id)
            .then((latest) => {
              if (latest) setDraft(createRoleDraft(latest));
            })
            .catch(() => {})
        }
      />
      {currentDraft.revision !== record.revision && dirty && (
        <FeedbackPanel
          tone="warning"
          copy={{ title: t("management.title"), description: t("management.conflict") }}
        />
      )}
      <fieldset
        className={styles["role-fieldset"]}
        disabled={
          locked || record.status === "disabled" || record.builtIn || record.lastActiveAdmin
        }
      >
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
    </section>
  );
}
