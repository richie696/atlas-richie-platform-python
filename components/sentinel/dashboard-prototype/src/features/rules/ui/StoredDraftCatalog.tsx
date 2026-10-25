import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createStoredDraftDirectory } from "../application/ruleDirectoryResources";
import type { createRuleDraftWorkflow } from "../application/ruleDraftWorkflow";
import { Panel } from "../../../shared/ui/Panel";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable } from "../../../shared/ui/DataTable";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { RuleQueryView } from "./RuleQueryView";
import styles from "./RuleSetWorkspace.module.scss";
import { formatUtcDateTime } from "../../../shared/presentation/utcDateTime";
interface Props {
  readonly bindingId: string;
  readonly resource: ReturnType<typeof createStoredDraftDirectory>;
  readonly workflow: ReturnType<typeof createRuleDraftWorkflow>;
  readonly onOpened?: () => void;
}
/** Stored drafts are independent from live snapshots. Revocation removes both read facts and unsent discard intentions. */
export function StoredDraftCatalog(props: Props) {
  const state = useExternalSnapshot(props.workflow),
    { t, i18n } = useTranslation();
  return state.authorized ? (
    <AuthorizedCatalog {...props} />
  ) : (
    <FeedbackPanel
      tone="warning"
      copy={{ title: t("rules.directory.drafts"), description: t("rules.workspace.denied") }}
    />
  );
}
function AuthorizedCatalog({ bindingId, resource, workflow, onOpened }: Props) {
  const state = useExternalSnapshot(resource),
    editing = useExternalSnapshot(workflow),
    { t, i18n } = useTranslation();
  const [intent, setIntent] = useState<{
      readonly owner: typeof workflow;
      readonly id: string;
    } | null>(null),
    [failed, setFailed] = useState(false);
  const read = () => void resource.load(bindingId).catch(() => {});
  useEffect(() => {
    void resource.load(bindingId).catch(() => {});
    return () => resource.cancel();
  }, [resource, bindingId]);
  async function open(id: string, discard = false) {
    setFailed(false);
    try {
      await workflow.openDraft(id, discard);
      setIntent(null);
      onOpened?.();
    } catch {
      setFailed(true);
    }
  }
  return (
    <Panel
      title={t("rules.directory.drafts")}
      subtitle={t("rules.directory.draftHint")}
      action={<ActionButton onClick={read}>{t("rules.directory.refreshDrafts")}</ActionButton>}
    >
      <div className={styles.content}>
        {failed && (
          <FeedbackPanel
            tone="warning"
            copy={{
              title: t("rules.workspace.actionBlocked"),
              description: t("rules.workspace.actionHint"),
            }}
          />
        )}
        <RuleQueryView snapshot={state} onRetry={read}>
          {(collection) => (
            <DataTable
              heads={[
                t("rules.directory.draftId"),
                t("rules.directory.revision"),
                t("rules.baseline"),
                t("rules.directory.updatedAt"),
                t("rules.directory.action"),
              ]}
              rows={collection.items.map((draft) => (
                <tr key={draft.id}>
                  <td>{draft.id}</td>
                  <td>{draft.revision}</td>
                  <td>{draft.baseVersionId ?? t("rules.workspace.noVersion")}</td>
                  <td>
                    <time dateTime={new Date(draft.updatedAtMs).toISOString()}>
                      {formatUtcDateTime(draft.updatedAtMs, i18n.resolvedLanguage ?? i18n.language)}
                    </time>
                  </td>
                  <td>
                    <ActionButton
                      data-draft-open={draft.id}
                      aria-pressed={editing.savedIdentity?.id === draft.id}
                      disabled={editing.locked}
                      onClick={() => {
                        if (editing.dirty) setIntent({ owner: workflow, id: draft.id });
                        else void open(draft.id);
                      }}
                    >
                      {t("rules.directory.openDraft")}
                    </ActionButton>
                  </td>
                </tr>
              ))}
            />
          )}
        </RuleQueryView>
      </div>
      {intent?.owner === workflow && (
        <DialogFrame
          isOpen
          title={t("rules.directory.switchDraft")}
          subtitle={intent.id}
          isBusy={editing.locked}
          onOpenChange={(value) => {
            if (!value) setIntent(null);
          }}
          actions={
            <>
              <ActionButton disabled={editing.locked} onClick={() => setIntent(null)}>
                {t("rules.workspace.keepEditing")}
              </ActionButton>
              <ActionButton
                data-draft-confirm-switch
                disabled={editing.locked}
                onClick={() => void open(intent.id, true)}
              >
                {t("rules.directory.discardAndOpen")}
              </ActionButton>
            </>
          }
        >
          <p>{t("rules.directory.discardHint")}</p>
          {failed && (
            <FeedbackPanel
              tone="warning"
              copy={{
                title: t("rules.workspace.actionBlocked"),
                description: t("rules.workspace.actionHint"),
              }}
            />
          )}
        </DialogFrame>
      )}
    </Panel>
  );
}
