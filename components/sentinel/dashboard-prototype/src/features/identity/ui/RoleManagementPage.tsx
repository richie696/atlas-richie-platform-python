import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { AccountManagementWorkflow } from "../application/accountManagementWorkflow";
import type { AccountListQuery } from "../model/accountManagement";
import { TextField } from "../../../shared/ui/TextField";
import { FormGrid } from "../../../shared/ui/FormGrid";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { IdentityIntro } from "./components/IdentityIntro";
import { IdentityPanel } from "./components/IdentityPanel";
import { AccountQueryView } from "./components/AccountQueryView";
import { RoleEditor } from "./components/RoleEditor";
import { Select } from "../../../shared/ui/Select";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { roleTargetFallbackCopy } from "../presentation/rolePresentation";
import styles from "./Identity.module.scss";

const ACCOUNT_PAGE_SIZE = 20;
const INITIAL_DIRECTORY: AccountListQuery = Object.freeze({
  page: 1,
  pageSize: ACCOUNT_PAGE_SIZE,
  search: "",
});
/** Explicit URL target, no default-account fallback; app navigation owns unsaved-change confirmation. */
export function RoleManagementPage({
  workflow,
  accountId,
  onAccountSelection,
}: {
  readonly workflow: AccountManagementWorkflow;
  readonly accountId?: string;
  readonly onAccountSelection: (id: string) => void;
}) {
  const { t } = useTranslation(),
    snapshot = useExternalSnapshot(workflow);
  const [directoryQuery, setDirectoryQuery] = useState(INITIAL_DIRECTORY),
    [search, setSearch] = useState(INITIAL_DIRECTORY.search);
  useEffect(() => {
    void workflow.list(directoryQuery).catch(() => {});
    return () => workflow.cancel();
  }, [workflow, directoryQuery]);
  useEffect(() => {
    if (accountId) void workflow.select(accountId).catch(() => {});
  }, [workflow, accountId]);
  const locked =
    snapshot.inspecting || ["pending", "result-unknown"].includes(snapshot.mutation.status);
  const selectedRecord =
    accountId && "data" in snapshot.detail && snapshot.detail.data?.id === accountId
      ? snapshot.detail.data
      : null;
  const selectedTargetLabel =
    selectedRecord?.username ?? t(roleTargetFallbackCopy(snapshot.detail));
  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setDirectoryQuery((current) => ({ ...current, page: 1, search: search.trim() }));
  };
  if (!snapshot.authorized)
    return (
      <FeedbackPanel
        tone="warning"
        copy={{ title: t("management.title"), description: t("management.denied") }}
      />
    );
  return (
    <section data-role-management>
      <IdentityIntro
        eyebrow="SYSTEM / ROLE BINDING"
        title={t("roles.intro.title")}
        description={t("roles.intro.description")}
      />
      <div className={styles["identity-split"]}>
        <IdentityPanel
          title={t("roles.accountPanel.title")}
          subtitle={t("roles.accountPanel.subtitle")}
        >
          <form onSubmit={submitSearch}>
            <FormGrid columns={1}>
              <TextField label={t("management.search")} value={search} onChange={setSearch} />
            </FormGrid>
            <div className={styles["identity-form-actions"]}>
              <ActionButton type="submit">{t("management.searchAction")}</ActionButton>
            </div>
          </form>
          <AccountQueryView
            snapshot={snapshot.directory}
            onRetry={() => void workflow.list(directoryQuery).catch(() => {})}
          >
            {(page) => (
              <>
                <Select
                  label={t("roles.field.account")}
                  value={accountId ?? ""}
                  disabled={locked}
                  onChange={(id) => {
                    if (id !== accountId) onAccountSelection(id);
                  }}
                  options={[
                    ...(!page.items.some((record) => record.id === accountId) && accountId
                      ? [
                          {
                            value: accountId,
                            label: selectedTargetLabel,
                          },
                        ]
                      : []),
                    ...page.items.map((record) => ({ value: record.id, label: record.username })),
                  ]}
                />
                <div className={styles["identity-form-actions"]}>
                  <span>{t("management.page", { page: page.page, total: page.total })}</span>
                  <ActionButton
                    disabled={locked || page.page === 1}
                    onClick={() =>
                      setDirectoryQuery((current) => ({ ...current, page: current.page - 1 }))
                    }
                  >
                    {t("management.previous")}
                  </ActionButton>
                  <ActionButton
                    disabled={locked || page.page * page.pageSize >= page.total}
                    onClick={() =>
                      setDirectoryQuery((current) => ({ ...current, page: current.page + 1 }))
                    }
                  >
                    {t("management.next")}
                  </ActionButton>
                </div>
              </>
            )}
          </AccountQueryView>
        </IdentityPanel>
        <IdentityPanel
          title={t("roles.bindingPanel.title")}
          subtitle={t("roles.bindingPanel.subtitle")}
        >
          {accountId ? (
            <AccountQueryView
              snapshot={snapshot.detail}
              onRetry={() => void workflow.select(accountId).catch(() => {})}
            >
              {(record) =>
                record && record.id === accountId ? (
                  <RoleEditor key={record.id} workflow={workflow} record={record} />
                ) : null
              }
            </AccountQueryView>
          ) : (
            <FeedbackPanel
              copy={{ title: t("management.title"), description: t("management.chooseAccount") }}
            />
          )}
        </IdentityPanel>
      </div>
    </section>
  );
}
