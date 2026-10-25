import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { createRuleBindingDirectory } from "../application/ruleDirectoryResources";
import { bindingQueryKey, type BindingQuery } from "../model/ruleDirectory";
import type { RuleBinding } from "../model/ruleSet";
import { RULE_KINDS } from "../model/ruleKinds";
import { useRuleCopy } from "../i18n/useRuleCopy";
import { Panel } from "../../../shared/ui/Panel";
import { FormGrid } from "../../../shared/ui/FormGrid";
import { Select, type SelectOption } from "../../../shared/ui/Select";
import { TextField } from "../../../shared/ui/TextField";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable } from "../../../shared/ui/DataTable";
import { RuleQueryView } from "./RuleQueryView";
import styles from "./RuleSetWorkspace.module.scss";
import { formatLocaleNumber } from "../../../shared/presentation/formatLocaleNumber";
/** Controlled directory filters. App supplies catalogs/selection; a page of results is never used as the application catalog. */
export function RuleBindingDirectory({
  resource,
  query,
  environments,
  applications,
  selectedId,
  locked = false,
  canRegister = false,
  onQueryChange,
  onSelect,
  onRegister,
}: {
  readonly resource: ReturnType<typeof createRuleBindingDirectory>;
  readonly query: BindingQuery;
  readonly environments: readonly SelectOption<string>[];
  readonly applications: readonly SelectOption<string>[];
  readonly selectedId: string | null;
  readonly locked?: boolean;
  readonly canRegister?: boolean;
  readonly onQueryChange: (query: BindingQuery) => void;
  readonly onSelect: (binding: RuleBinding) => void;
  readonly onRegister?: () => void;
}) {
  const { t, i18n } = useTranslation(),
    { messages } = useRuleCopy(),
    state = useExternalSnapshot(resource);
  const { environmentId, appId, kind, search, page, pageSize } = query;
  const ownedQuery = useMemo(
    () => ({ environmentId, appId, kind, search, page, pageSize }),
    [environmentId, appId, kind, search, page, pageSize],
  );
  useEffect(() => {
    void resource.load(ownedQuery).catch(() => {});
    return () => resource.cancel();
  }, [resource, ownedQuery]);
  const read = () => void resource.load(ownedQuery).catch(() => {});
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const currentPage =
    "data" in state && bindingQueryKey(state.data.query) === bindingQueryKey(ownedQuery)
      ? state.data
      : null;
  return (
    <Panel
      title={t("rules.directory.title")}
      subtitle={t("rules.directory.selectionHint")}
      action={
        <div className={styles.actions}>
          <ActionButton onClick={read}>{t("rules.directory.refresh")}</ActionButton>
          {canRegister && onRegister && (
            <ActionButton variant="primary" onClick={onRegister}>
              {t("rules.registration.open")}
            </ActionButton>
          )}
        </div>
      }
    >
      <div className={styles.content}>
        <FormGrid>
          <Select
            label={t("rules.directory.environment")}
            value={environmentId}
            options={environments}
            disabled={locked}
            onChange={(value) =>
              onQueryChange({ ...query, environmentId: value, appId: null, page: 1 })
            }
          />
          <Select
            label={t("rules.directory.application")}
            value={appId ?? ""}
            options={[{ value: "", label: t("rules.directory.allApplications") }, ...applications]}
            disabled={locked}
            onChange={(value) => onQueryChange({ ...query, appId: value || null, page: 1 })}
          />
          <Select
            label={t("rules.directory.kind")}
            value={kind ?? ""}
            options={[
              { value: "", label: t("rules.directory.allKinds") },
              ...RULE_KINDS.map((value) => ({ value, label: messages.types[value].label })),
            ]}
            disabled={locked}
            onChange={(value) =>
              onQueryChange({
                ...query,
                kind: RULE_KINDS.find((item) => item === value) ?? null,
                page: 1,
              })
            }
          />
          <TextField
            label={t("rules.directory.search")}
            value={search}
            disabled={locked}
            onChange={(value) => onQueryChange({ ...query, search: value, page: 1 })}
          />
        </FormGrid>
        {currentPage && (
          <p data-binding-total>
            {t("rules.directory.total", {
              total: formatLocaleNumber(currentPage.total, locale),
              page: formatLocaleNumber(currentPage.query.page, locale),
              shown: formatLocaleNumber(currentPage.items.length, locale),
            })}
          </p>
        )}
        <RuleQueryView snapshot={state} onRetry={read}>
          {(result) => (
            <>
              <DataTable
                heads={[
                  t("rules.workspace.binding"),
                  t("rules.directory.kind"),
                  t("rules.provider"),
                  t("rules.workspace.profile"),
                  t("rules.directory.action"),
                ]}
                rows={result.items.map((binding) => (
                  <tr key={binding.id}>
                    <td>
                      {binding.id}
                      <br />
                      {binding.location}
                    </td>
                    <td>{messages.types[binding.kind].label}</td>
                    <td>{binding.sourceLabel}</td>
                    <td>{binding.profile}</td>
                    <td>
                      <ActionButton
                        data-binding-select={binding.id}
                        aria-pressed={binding.id === selectedId}
                        disabled={locked}
                        onClick={() => onSelect(binding)}
                      >
                        {t("rules.directory.open")}
                      </ActionButton>
                    </td>
                  </tr>
                ))}
              />
            </>
          )}
        </RuleQueryView>
        <div className={styles.actions}>
          <ActionButton
            data-binding-previous
            disabled={locked || page <= 1}
            onClick={() => onQueryChange({ ...query, page: page - 1 })}
          >
            {t("rules.directory.previous")}
          </ActionButton>
          <ActionButton
            data-binding-next
            disabled={locked || !currentPage || page * pageSize >= currentPage.total}
            onClick={() => onQueryChange({ ...query, page: page + 1 })}
          >
            {t("rules.directory.next")}
          </ActionButton>
        </div>
      </div>
    </Panel>
  );
}
