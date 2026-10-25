import { useTranslation } from "react-i18next";
import type { AccountPage, AccountRecord } from "../../model/accountManagement";
import { ACCOUNT_STATUS } from "../../model/account";
import { rolePresentationFor } from "../../presentation/rolePresentation";
import { accountStatusRestrictionCopy } from "../../presentation/accountStatusPresentation";
import { formatAccountLastLogin } from "../../presentation/accountTime";
import { DataTable } from "../../../../shared/ui/DataTable";
import { ActionButton } from "../../../../shared/ui/ActionButton";
import styles from "../Identity.module.scss";

/** Directory actions use server revisions; resetting the signed-in account requires reauthentication. */
export function AccountDirectory({
  page,
  locked,
  onBindRole,
  onStatus,
  ownerAccountId,
  onResetPassword,
  onDelete,
  onPage,
}: {
  readonly page: AccountPage;
  readonly locked: boolean;
  readonly onBindRole: (id: string) => void;
  readonly onStatus: (record: AccountRecord) => void;
  readonly ownerAccountId: string;
  readonly onResetPassword: (record: AccountRecord) => void;
  readonly onDelete: (record: AccountRecord) => void;
  readonly onPage: (page: number) => void;
}) {
  const { t, i18n } = useTranslation();
  return (
    <>
      <DataTable
        className={styles["identity-table"]}
        heads={[
          t("accounts.head.username"),
          t("accounts.head.role"),
          t("accounts.head.status"),
          t("accounts.head.lastLogin"),
          t("accounts.head.type"),
          t("accounts.head.actions"),
        ]}
        rows={page.items.map((record) => {
          const statusRestriction = accountStatusRestrictionCopy(record);
          return (
            <tr key={record.id} data-account-id={record.id}>
              <td>{record.username}</td>
              <td>{t(rolePresentationFor(record.roleId).labelKey)}</td>
              <td>
                {t(
                  record.status === ACCOUNT_STATUS.Active
                    ? "accounts.status.active"
                    : "accounts.status.disabled",
                )}
              </td>
              <td>
                {record.lastLoginAt
                  ? formatAccountLastLogin(
                      record.lastLoginAt,
                      i18n.resolvedLanguage ?? i18n.language,
                    )
                  : t("management.neverLoggedIn")}
              </td>
              <td>{t(record.builtIn ? "accounts.type.builtIn" : "accounts.type.normal")}</td>
              <td>
                <div className={styles["account-row-actions"]}>
                  <div className={styles["identity-actions"]}>
                    <ActionButton disabled={locked} onClick={() => onBindRole(record.id)}>
                      {t("accounts.action.bindRole")}
                    </ActionButton>
                    <ActionButton
                      disabled={locked || (record.builtIn && record.id !== ownerAccountId)}
                      onClick={() => onResetPassword(record)}
                    >
                      {t("accounts.action.resetPassword")}
                    </ActionButton>
                    <ActionButton
                      disabled={
                        locked ||
                        record.builtIn ||
                        record.lastActiveAdmin ||
                        record.id === ownerAccountId
                      }
                      onClick={() => onDelete(record)}
                    >
                      {t("accounts.action.delete")}
                    </ActionButton>
                    <ActionButton
                      disabled={locked || statusRestriction !== null}
                      onClick={() => onStatus(record)}
                    >
                      {t(
                        record.status === ACCOUNT_STATUS.Active
                          ? "accounts.action.disable"
                          : "accounts.action.enable",
                      )}
                    </ActionButton>
                  </div>
                  {(record.id === ownerAccountId || statusRestriction) && (
                    <div className={styles["account-action-notes"]}>
                      {record.id === ownerAccountId && (
                        <small role="note">{t("management.useOwnPassword")}</small>
                      )}
                      {statusRestriction && (
                        <small className={styles["account-status-restriction"]} role="note">
                          {t(statusRestriction)}
                        </small>
                      )}
                    </div>
                  )}
                </div>
              </td>
            </tr>
          );
        })}
      />
      <div className={styles["identity-form-actions"]}>
        <span>{t("management.page", { page: page.page, total: page.total })}</span>
        <ActionButton disabled={locked || page.page === 1} onClick={() => onPage(page.page - 1)}>
          {t("management.previous")}
        </ActionButton>
        <ActionButton
          disabled={locked || page.page * page.pageSize >= page.total}
          onClick={() => onPage(page.page + 1)}
        >
          {t("management.next")}
        </ActionButton>
      </div>
    </>
  );
}
