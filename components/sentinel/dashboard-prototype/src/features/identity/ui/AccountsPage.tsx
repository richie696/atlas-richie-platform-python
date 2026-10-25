import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import type { AccountManagementWorkflow } from "../application/accountManagementWorkflow";
import {
  boundAccountSearch,
  type AccountListQuery,
  type AccountRecord,
} from "../model/accountManagement";
import { ACCOUNT_STATUS, nextAccountStatus } from "../model/account";
import { TextField } from "../../../shared/ui/TextField";
import { Select } from "../../../shared/ui/Select";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { DialogFrame } from "../../../shared/ui/DialogFrame";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { IdentityIntro } from "./components/IdentityIntro";
import { IdentityPanel } from "./components/IdentityPanel";
import { AccountDirectory } from "./components/AccountDirectory";
import { AccountQueryView } from "./components/AccountQueryView";
import { AccountCommandFeedback } from "./components/AccountCommandFeedback";
import { CreateAccountDialog } from "./CreateAccountDialog";
import { AccountLifecycleDialog } from "./AccountLifecycleDialog";
import { useBeforeUnloadGuard } from "../../../shared/state/useBeforeUnloadGuard";
import styles from "./Identity.module.scss";

/** URL query comes from the app; this container owns only search input and modal intent. */
export function AccountsPage({
  workflow,
  query,
  onQueryChange,
  onBindRole,
  onOwnPasswordReset,
}: {
  readonly workflow: AccountManagementWorkflow;
  readonly query: AccountListQuery;
  readonly onQueryChange: (query: AccountListQuery) => void;
  readonly onBindRole: (id: string) => void;
  readonly onOwnPasswordReset: () => void;
}) {
  const { t } = useTranslation(),
    snapshot = useExternalSnapshot(workflow);
  const [search, setSearch] = useState(() => boundAccountSearch(query.search)),
    [creating, setCreating] = useState(false),
    [target, setTarget] = useState<AccountRecord | null>(null);
  const [lifecycle, setLifecycle] = useState<{
    readonly kind: "reset_password" | "delete";
    readonly account: AccountRecord;
  } | null>(null);
  const load = () => void workflow.list(query).catch(() => {});
  useEffect(() => {
    void workflow.list(query).catch(() => {});
    return () => workflow.cancelDirectory();
  }, [workflow, query]);
  const locked =
    snapshot.inspecting || ["pending", "result-unknown"].includes(snapshot.mutation.status);
  useBeforeUnloadGuard(snapshot.authorized && locked, snapshot.authorized && locked);
  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onQueryChange({ ...query, page: 1, search: search.trim() });
  };
  const inspect = () =>
    void workflow
      .inspect()
      .then((receipt) => {
        if (receipt.status === "completed") setTarget(null);
      })
      .catch(() => {});
  if (!snapshot.authorized)
    return (
      <FeedbackPanel
        tone="warning"
        copy={{ title: t("management.title"), description: t("management.denied") }}
      />
    );
  return (
    <section data-account-management>
      <IdentityIntro
        eyebrow="SYSTEM / ACCOUNTS"
        title={t("accounts.intro.title")}
        description={t("accounts.intro.description")}
        action={
          <ActionButton disabled={locked} onClick={() => setCreating(true)}>
            {t("accounts.action.create")}
          </ActionButton>
        }
      />
      {!creating && (
        <AccountCommandFeedback snapshot={snapshot} onInspect={inspect} onReadLatest={load} />
      )}
      <IdentityPanel title={t("accounts.panel.title")} subtitle={t("accounts.panel.subtitle")}>
        <form className={styles["account-search-form"]} onSubmit={submitSearch}>
          <TextField
            label={t("management.search")}
            value={search}
            onChange={(value) => setSearch(boundAccountSearch(value))}
          />
          <Select
            label={t("accounts.head.status")}
            value={query.status ?? "all"}
            onChange={(status) =>
              onQueryChange({ ...query, page: 1, status: status === "all" ? undefined : status })
            }
            options={[
              { value: "all", label: t("management.allStatuses") },
              { value: ACCOUNT_STATUS.Active, label: t("accounts.status.active") },
              { value: ACCOUNT_STATUS.Disabled, label: t("accounts.status.disabled") },
            ]}
          />
          <ActionButton className={styles["filter-submit"]} type="submit">
            {t("management.searchAction")}
          </ActionButton>
        </form>
        <div className={styles["account-directory-inset"]}>
          <AccountQueryView snapshot={snapshot.directory} onRetry={load}>
            {(page) => (
              <AccountDirectory
                page={page}
                locked={locked}
                onBindRole={onBindRole}
                onStatus={setTarget}
                ownerAccountId={workflow.ownerAccountId}
                onResetPassword={(account) => setLifecycle({ kind: "reset_password", account })}
                onDelete={(account) => setLifecycle({ kind: "delete", account })}
                onPage={(page) => onQueryChange({ ...query, page })}
              />
            )}
          </AccountQueryView>
        </div>
      </IdentityPanel>
      {creating && <CreateAccountDialog workflow={workflow} onClose={() => setCreating(false)} />}
      {lifecycle && (
        <AccountLifecycleDialog
          workflow={workflow}
          kind={lifecycle.kind}
          account={lifecycle.account}
          onOwnPasswordReset={onOwnPasswordReset}
          onClose={() => setLifecycle(null)}
        />
      )}
      {target && (
        <DialogFrame
          isOpen
          isBusy={locked}
          onOpenChange={(open) => {
            if (!open && !locked) setTarget(null);
          }}
          title={t("management.confirmStatus")}
          subtitle={t("management.statusImpact", { username: target.username })}
          actions={
            <>
              <ActionButton disabled={locked} onClick={() => setTarget(null)}>
                {t("accountDialog.action.cancel")}
              </ActionButton>
              <ActionButton
                disabled={locked}
                onClick={() =>
                  void workflow
                    .setStatus(target, nextAccountStatus(target.status))
                    .then((receipt) => {
                      if (receipt.status === "completed") setTarget(null);
                    })
                    .catch(() => {})
                }
              >
                {t("management.confirm")}
              </ActionButton>
            </>
          }
        >
          <AccountCommandFeedback
            snapshot={snapshot}
            onInspect={inspect}
            onReadLatest={() =>
              void workflow
                .select(target.id)
                .then((latest) => setTarget(latest))
                .catch(() => {})
            }
          />
          <p>
            {t(
              target.status === ACCOUNT_STATUS.Active
                ? "management.disableImpact"
                : "management.enableImpact",
            )}
          </p>
        </DialogFrame>
      )}
    </section>
  );
}
