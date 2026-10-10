import { useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type {
  createRuleBindingRegistrationCommand,
  createRuleSourceCatalogResource,
} from "../application/ruleBindingRegistration";
import {
  DEFAULT_NACOS_RULE_GROUP,
  DEFAULT_SENTINEL_RULE_PROFILE,
  prepareRuleBindingRegistration,
  type RuleBindingRegistrationDraft,
  type RuleSourceCatalog,
  type RuleSourceOption,
} from "../model/ruleBindingRegistration";
import { RULE_KINDS, RULE_TYPE_META, type RuleKind } from "../model/ruleKinds";
import type { RuleBinding } from "../model/ruleSet";
import { useRuleCopy } from "../i18n/useRuleCopy";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { FormGrid } from "../../../shared/ui/FormGrid";
import { Select } from "../../../shared/ui/Select";
import { TextField } from "../../../shared/ui/TextField";
import styles from "./RuleSetWorkspace.module.scss";

type SourceCatalogResource = ReturnType<typeof createRuleSourceCatalogResource>;
type RegistrationCommand = ReturnType<typeof createRuleBindingRegistrationCommand>;
const EMPTY_SOURCES: readonly RuleSourceOption[] = Object.freeze([]);

function initialDraft(
  environmentId: string,
  applications: readonly { readonly id: string }[],
  defaultKind: RuleKind,
): RuleBindingRegistrationDraft {
  return {
    bindingId: "",
    environmentId,
    appId: applications.length === 1 ? applications[0].id : "",
    kind: defaultKind,
    profile: DEFAULT_SENTINEL_RULE_PROFILE,
    sourceId: "",
    namespace: "",
    group: DEFAULT_NACOS_RULE_GROUP,
    dataId: "",
    datacenter: "",
    key: "",
  };
}

function targetForSource(source: RuleSourceOption | undefined) {
  return source?.provider === "nacos"
    ? { namespace: source.namespace, datacenter: "" }
    : source?.provider === "consul"
      ? { namespace: "", datacenter: source.datacenter }
      : { namespace: "", datacenter: "" };
}

/** Admin-only rules feature dialog; shared DialogFrame owns modal anatomy and focus behavior. */
export function RuleBindingRegistrationDialog({
  environmentId,
  environments,
  applications,
  defaultKind,
  sourceResource,
  command,
  onClose,
  onCreated,
}: {
  readonly environmentId: string;
  readonly environments: readonly { readonly id: string; readonly name: string }[];
  readonly applications: readonly { readonly id: string; readonly name: string }[];
  readonly defaultKind: RuleKind;
  readonly sourceResource: SourceCatalogResource;
  readonly command: RegistrationCommand;
  readonly onClose: () => void;
  readonly onCreated: (binding: RuleBinding) => void;
}) {
  const { t } = useTranslation();
  const { messages } = useRuleCopy();
  const formId = useId();
  const sourceState = useExternalSnapshot(sourceResource);
  const commandState = useExternalSnapshot(command);
  const [draft, setDraft] = useState(() => initialDraft(environmentId, applications, defaultKind));
  const [invalid, setInvalid] = useState(false);
  const [submitted, setSubmitted] = useState<{
    readonly command: NonNullable<ReturnType<typeof prepareRuleBindingRegistration>>;
    readonly sourceCatalog: RuleSourceCatalog;
  } | null>(null);

  useEffect(() => {
    void sourceResource.load(null).catch(() => undefined);
    return () => sourceResource.cancel();
  }, [sourceResource]);
  const sources = "data" in sourceState ? sourceState.data.items : EMPTY_SOURCES;
  const selectedSource = sources.find((source) => source.id === draft.sourceId);
  const busy = commandState.status === "pending";
  const unknown = commandState.status === "result-unknown";
  const registrationFailed = commandState.status === "error" || commandState.status === "conflict";
  const sourceReadFailed = sourceState.status === "error" || sourceState.status === "stale";
  const canSubmit =
    !!selectedSource && applications.some((application) => application.id === draft.appId);

  const change = (patch: Partial<RuleBindingRegistrationDraft>) => {
    if (busy || unknown) return;
    if (commandState.status !== "idle") command.reset();
    setDraft((current) => ({ ...current, ...patch }));
    setInvalid(false);
  };

  const submitCommand = async (submission: NonNullable<typeof submitted>, isRetry: boolean) => {
    try {
      if (isRetry) command.reset();
      const binding = await command.run(submission);
      onCreated(binding);
    } catch {
      // The workflow exposes a redacted command snapshot with a stable failure class.
    }
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || !("data" in sourceState)) {
      setInvalid(true);
      return;
    }
    const registration = prepareRuleBindingRegistration(draft, selectedSource, crypto.randomUUID());
    if (!registration) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    const input = { command: registration, sourceCatalog: sourceState.data };
    setSubmitted(input);
    await submitCommand(input, false);
  };

  const close = () => {
    if (busy || unknown) return;
    command.reset();
    onClose();
  };

  const sourceOptions = useMemo(
    () =>
      sources.map((source) => ({
        value: source.id,
        label: `${source.name} · ${
          source.provider === "nacos"
            ? t("rules.registration.provider.nacos")
            : t("rules.registration.provider.consul")
        }`,
      })),
    [sources, t],
  );

  return (
    <DialogFrame
      isOpen
      onOpenChange={(open) => {
        if (!open) close();
      }}
      isBusy={busy || unknown}
      title={t("rules.registration.title")}
      subtitle={t("rules.registration.subtitle")}
      width={820}
      actions={
        <>
          <ActionButton disabled={busy || unknown} onClick={close}>
            {t("rules.registration.cancel")}
          </ActionButton>
          <ActionButton
            variant="primary"
            type="submit"
            form={formId}
            disabled={busy || unknown || !canSubmit}
            isLoading={busy}
          >
            {t("rules.registration.submit")}
          </ActionButton>
        </>
      }
    >
      <form id={formId} className={styles.content} onSubmit={(event) => void submit(event)}>
        {sourceReadFailed && (
          <FeedbackPanel
            tone="error"
            copy={{
              title: t("rules.registration.sourcesFailed"),
              description: t("rules.registration.sourcesFailedHint"),
            }}
            actions={
              <ActionButton onClick={() => void sourceResource.load(null).catch(() => undefined)}>
                {t("rules.registration.refreshSources")}
              </ActionButton>
            }
          />
        )}
        {sourceState.status === "loading" && (
          <FeedbackPanel
            tone="info"
            isBusy
            copy={{
              title: t("rules.registration.sourcesLoading"),
              description: t("rules.registration.sourcesLoadingHint"),
            }}
          />
        )}
        {"data" in sourceState && sources.length === 0 && (
          <FeedbackPanel
            tone="warning"
            copy={{
              title: t("rules.registration.sourcesEmpty"),
              description: t("rules.registration.sourcesEmptyHint"),
            }}
          />
        )}
        <FormGrid>
          <TextField
            label={t("rules.registration.bindingId")}
            value={draft.bindingId}
            disabled={busy || unknown}
            onChange={(bindingId) => change({ bindingId })}
          />
          <Select
            label={t("rules.registration.environment")}
            value={draft.environmentId}
            options={environments.map(({ id, name }) => ({ value: id, label: name }))}
            disabled={busy || unknown}
            onChange={(environmentId) => change({ environmentId })}
          />
          <Select
            label={t("rules.registration.application")}
            value={draft.appId}
            options={applications.map(({ id, name }) => ({ value: id, label: name }))}
            disabled={busy || unknown || applications.length === 0}
            onChange={(appId) => change({ appId })}
          />
          <Select
            label={t("rules.registration.kind")}
            value={draft.kind}
            options={RULE_KINDS.map((kind) => ({
              value: kind,
              label: messages.types[kind].label,
            }))}
            disabled={busy || unknown}
            onChange={(kind) => change({ kind })}
          />
          <TextField
            label={t("rules.registration.profile")}
            value={draft.profile}
            hint={t("rules.registration.profileHint")}
            disabled={busy || unknown}
            onChange={(profile) => change({ profile })}
          />
          <Select
            label={t("rules.registration.source")}
            value={draft.sourceId}
            options={sourceOptions}
            disabled={busy || unknown || sources.length === 0}
            onChange={(sourceId) => {
              const source = sources.find((item) => item.id === sourceId);
              change({ sourceId, ...targetForSource(source) });
            }}
          />
          {selectedSource?.provider === "nacos" ? (
            <>
              <TextField
                label={t("rules.registration.namespace")}
                value={draft.namespace}
                disabled={busy || unknown}
                onChange={(namespace) => change({ namespace })}
              />
              <TextField
                label={t("rules.registration.group")}
                value={draft.group}
                disabled={busy || unknown}
                onChange={(group) => change({ group })}
              />
              <TextField
                label={t("rules.registration.dataId")}
                value={draft.dataId}
                placeholder={RULE_TYPE_META[draft.kind].configName}
                disabled={busy || unknown}
                onChange={(dataId) => change({ dataId })}
              />
            </>
          ) : selectedSource?.provider === "consul" ? (
            <>
              <TextField
                label={t("rules.registration.datacenter")}
                value={draft.datacenter}
                hint={t("rules.registration.datacenterHint")}
                disabled={busy || unknown}
                onChange={(datacenter) => change({ datacenter })}
              />
              <TextField
                label={t("rules.registration.key")}
                value={draft.key}
                disabled={busy || unknown}
                onChange={(key) => change({ key })}
              />
            </>
          ) : null}
        </FormGrid>
        {invalid && (
          <FeedbackPanel
            tone="error"
            copy={{
              title: t("rules.registration.invalid"),
              description: t("rules.registration.invalidHint"),
            }}
          />
        )}
        {registrationFailed && (
          <FeedbackPanel
            tone="error"
            copy={{
              title: t(
                commandState.error.status === 409
                  ? "rules.registration.conflict"
                  : "rules.registration.failed",
              ),
              description: t(
                commandState.error.status === 409
                  ? "rules.registration.conflictHint"
                  : "rules.registration.failedHint",
              ),
            }}
          />
        )}
        {unknown && (
          <FeedbackPanel
            tone="warning"
            copy={{
              title: t("rules.registration.unknown"),
              description: t("rules.registration.unknownHint"),
            }}
            actions={
              <ActionButton
                variant="primary"
                onClick={() => submitted && void submitCommand(submitted, true)}
                disabled={!submitted}
              >
                {t("rules.registration.retrySame")}
              </ActionButton>
            }
          />
        )}
      </form>
    </DialogFrame>
  );
}
