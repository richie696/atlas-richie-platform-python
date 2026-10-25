import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { AccountManagementWorkflow } from "../application/accountManagementWorkflow";
import { boundAccountSearch, type AccountListQuery } from "../model/accountManagement";
import { TextField } from "../../../shared/ui/TextField";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { IdentityIntro } from "./components/IdentityIntro";
import { IdentityPanel } from "./components/IdentityPanel";
import { AccountQueryView } from "./components/AccountQueryView";
import { RoleEditor } from "./components/RoleEditor";
import { RadioGroup } from "../../../shared/ui/RadioGroup";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { roleTargetFallbackCopy } from "../presentation/rolePresentation";
import styles from "./Identity.module.scss";

const ACCOUNT_PAGE_SIZE = 10;
const INITIAL_DIRECTORY: AccountListQuery = Object.freeze({
  page: 1,
  pageSize: ACCOUNT_PAGE_SIZE,
  search: "",
});
/** Explicit URL target, no default-account fallback; app navigation owns unsaved-change confirmation. */
export function RoleManagementPage({
  workflow,
  accountId,
  sessionEpoch,
  onAccountSelection,
  onBack,
}: {
  readonly workflow: AccountManagementWorkflow;
  readonly accountId?: string;
  readonly sessionEpoch: string;
  readonly onAccountSelection: (id: string) => void;
  readonly onBack: () => void;
}) {
  const { t } = useTranslation(),
    snapshot = useExternalSnapshot(workflow);
  const [directoryQuery, setDirectoryQuery] = useState(INITIAL_DIRECTORY),
    [search, setSearch] = useState(INITIAL_DIRECTORY.search);
  useEffect(() => {
    void workflow.list(directoryQuery).catch(() => {});
    return () => workflow.cancelDirectory();
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
        action={<ActionButton onClick={onBack}>{t("roles.action.back")}</ActionButton>}
      />
      <div className={styles["identity-split"]}>
        <IdentityPanel
          title={t("roles.accountPanel.title")}
          subtitle={t("roles.accountPanel.subtitle")}
        >
          <div className={styles["role-panel-content"]}>
            <form className={styles["role-search-form"]} onSubmit={submitSearch}>
              <TextField
                label={t("management.search")}
                value={search}
                onChange={(value) => setSearch(boundAccountSearch(value))}
              />
              <ActionButton className={styles["filter-submit"]} disabled={locked} type="submit">
                {t("management.searchAction")}
              </ActionButton>
            </form>
            <AccountQueryView
              snapshot={snapshot.directory}
              onRetry={() => void workflow.list(directoryQuery).catch(() => {})}
            >
              {(page) => (
                <>
                  {(page.items.length > 0 || accountId) && (
                    <fieldset className={styles["role-account-fieldset"]} disabled={locked}>
                      <RadioGroup
                        label={t("roles.field.account")}
                        value={accountId ?? ""}
                        onChange={(id) => {
                          if (id !== accountId) onAccountSelection(id);
                        }}
                        className={styles["role-account-list"]}
                        variant="cards"
                        options={[
                          ...(!page.items.some((record) => record.id === accountId) && accountId
                            ? [{ value: accountId, label: selectedTargetLabel }]
                            : []),
                          ...page.items.map((record) => ({
                            value: record.id,
                            label: record.username,
                          })),
                        ]}
                      />
                    </fieldset>
                  )}
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
          </div>
        </IdentityPanel>
        <IdentityPanel
          title={t("roles.bindingPanel.title")}
          subtitle={t("roles.bindingPanel.subtitle")}
        >
          <div className={styles["role-panel-content"]}>
            {accountId ? (
              <AccountQueryView
                snapshot={snapshot.detail}
                onRetry={() => void workflow.select(accountId).catch(() => {})}
              >
                {(record) =>
                  record && record.id === accountId ? (
                    <RoleEditor
                      key={`${sessionEpoch}:${record.id}`}
                      workflow={workflow}
                      record={record}
                      sessionEpoch={sessionEpoch}
                    />
                  ) : null
                }
              </AccountQueryView>
            ) : (
              <FeedbackPanel
                copy={{ title: t("management.title"), description: t("management.chooseAccount") }}
              />
            )}
          </div>
        </IdentityPanel>
      </div>
    </section>
  );
}
