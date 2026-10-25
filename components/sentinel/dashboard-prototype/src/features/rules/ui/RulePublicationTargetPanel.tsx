import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createRuleDeploymentWorkflow } from "../application/ruleDeploymentWorkflow";
import type { RuleMutationTarget } from "../model/ruleSetOperations";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { Select } from "../../../shared/ui/Select";
import { TextField } from "../../../shared/ui/TextField";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import styles from "./RuleSetWorkspace.module.scss";

/** Edit only the provider location; registered credentials remain owned by the server. */
export function RulePublicationTargetPanel({
  workflow,
}: {
  readonly workflow: ReturnType<typeof createRuleDeploymentWorkflow>;
}) {
  const state = useExternalSnapshot(workflow);
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState<"nacos" | "consul">("nacos");
  const [namespace, setNamespace] = useState("");
  const [group, setGroup] = useState("SENTINEL_GROUP");
  const [dataId, setDataId] = useState("");
  const [key, setKey] = useState("");
  const [failed, setFailed] = useState(false);
  const targetState = state.publicationTarget;
  const saved =
    targetState.status === "ready" && "data" in targetState ? targetState.data.target : null;

  function edit() {
    setProvider(saved?.provider ?? "nacos");
    setNamespace(saved?.provider === "nacos" ? saved.namespace : "");
    setGroup(saved?.provider === "nacos" ? saved.group : "SENTINEL_GROUP");
    setDataId(saved?.provider === "nacos" ? saved.dataId : "");
    setKey(saved?.provider === "consul" ? saved.key : "");
    setFailed(false);
    setOpen(true);
  }

  async function submit() {
    const target: RuleMutationTarget | null =
      provider === "nacos"
        ? namespace.trim() && group.trim() && dataId.trim()
          ? {
              provider,
              sourceId: workflow.binding.sourceId,
              namespace: namespace.trim(),
              group: group.trim(),
              dataId: dataId.trim(),
            }
          : null
        : key.trim()
          ? { provider, sourceId: workflow.binding.sourceId, key: key.trim() }
          : null;
    if (!target) {
      setFailed(true);
      return;
    }
    setFailed(false);
    try {
      await workflow.configurePublicationTarget(target);
      await workflow.refreshPublicationTarget();
      setOpen(false);
    } catch {
      setFailed(true);
    }
  }

  return (
    <section className={styles.content} aria-labelledby="rule-publication-target-title">
      <header>
        <h3 id="rule-publication-target-title">{t("rules.target.title")}</h3>
        <p>{t("rules.target.description")}</p>
      </header>
      {saved ? (
        <dl className={styles.facts}>
          <div>
            <dt>{t("rules.target.provider")}</dt>
            <dd>{saved.provider === "nacos" ? "Nacos" : "Consul"}</dd>
          </div>
          <div>
            <dt>{t("rules.target.location")}</dt>
            <dd>
              {saved.provider === "nacos"
                ? `${saved.namespace} / ${saved.group} / ${saved.dataId}`
                : saved.key}
            </dd>
          </div>
          <div>
            <dt>{t("rules.target.revision")}</dt>
            <dd>
              {targetState.status === "ready" &&
              "data" in targetState &&
              targetState.data.target !== null
                ? targetState.data.targetRevision
                : ""}
            </dd>
          </div>
        </dl>
      ) : (
        <p>{t("rules.target.unconfigured")}</p>
      )}
      <ActionButton disabled={!state.writable || state.locked} onClick={edit}>
        {saved ? t("rules.target.edit") : t("rules.target.configure")}
      </ActionButton>
      {open && (
        <DialogFrame
          isOpen
          title={t("rules.target.dialogTitle")}
          subtitle={t("rules.target.dialogHint")}
          isBusy={state.locked}
          onOpenChange={(visible) => setOpen(visible)}
          actions={
            <>
              <ActionButton disabled={state.locked} onClick={() => setOpen(false)}>
                {t("rules.workspace.keepEditing")}
              </ActionButton>
              <ActionButton
                disabled={state.locked || !state.writable}
                onClick={() => void submit()}
              >
                {t("rules.target.save")}
              </ActionButton>
            </>
          }
        >
          {failed && (
            <FeedbackPanel
              tone="warning"
              copy={{
                title: t("rules.workspace.actionBlocked"),
                description: t("rules.target.saveFailed"),
              }}
            />
          )}
          <Select
            label={t("rules.target.provider")}
            value={provider}
            onChange={setProvider}
            options={[
              { value: "nacos", label: "Nacos" },
              { value: "consul", label: "Consul" },
            ]}
          />
          {provider === "nacos" ? (
            <>
              <TextField
                label={t("rules.target.namespace")}
                value={namespace}
                onChange={setNamespace}
              />
              <TextField label={t("rules.target.group")} value={group} onChange={setGroup} />
              <TextField label={t("rules.target.dataId")} value={dataId} onChange={setDataId} />
            </>
          ) : (
            <TextField label={t("rules.target.key")} value={key} onChange={setKey} />
          )}
        </DialogFrame>
      )}
    </section>
  );
}
