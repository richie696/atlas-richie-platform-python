/**
 * 账户维护页面容器。
 *
 * 中文
 * ----
 * 页面只做三件事：订阅 feature 状态、组合区域、把用户动作映射为命令。
 *
 * 与旧实现的关键差别在**状态归属**：账号列表不再由本页面 `useState` 持有，而是订阅
 * `state/accountStore`。旧实现在这里和 `RoleBindingPage` 各存一份 `INITIAL_ACCOUNTS`
 * 副本，于是「新建的账号在角色绑定页消失」「改过的角色回到本页又变回去」；现在列表
 * 只有一份，命令也只有 `add` / `setStatus` 两个入口。
 *
 * `notice` 与「是否打开对话框」是页面局部交互状态，按 `REACT_CODING_STANDARD` §3
 * 留在最近的组件里，不进 store。
 */
import { useState } from "react";
import { fixtureGateway } from "../../../core/api/fixtureGateway";
import { useTranslation } from "react-i18next";
import {
  PlusIcon as Plus,
  ShieldCheckIcon as ShieldCheck,
  UserCircleIcon as UserCircle,
} from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { DataTable } from "../../../shared/ui/DataTable";
import { ROUTE } from "../../../app/router/route.constants";
import type { Navigate } from "../../../shared/types/dashboard";
import {
  ACCOUNT_STATUS,
  nextAccountStatus,
  roleFor,
  toAccountSummary,
  type AccountDraft,
} from "../model/account";
import { loadAccounts, useAccounts } from "../state/accountStore";
import { AccountCreateDialog } from "./AccountCreateDialog";
import { IdentityIntro } from "./components/IdentityIntro";
import { IdentityPanel } from "./components/IdentityPanel";

// 演示装配：把示例账号装载进 feature store，模块初始化时执行一次。
// 生产实现由 `identity.gateway` 在会话建立后调用同一个 `loadAccounts`，
// 页面不再需要知道数据来源。

// 数据从 gateway 取，页面不感知来源（见 `core/api/fixtureGateway.ts`）。
// 模块级：账号在会话建立时装载一次，与原实现同为模块初始化时执行。
const { accounts: initialAccounts, newAccountLastLogin } = fixtureGateway.readAccountsSync();

loadAccounts(initialAccounts);

export function AccountMaintenancePage({ navigate }: { navigate: Navigate }) {
  const { t } = useTranslation();
  const { accounts, add, setStatus } = useAccounts();
  const [showCreate, setShowCreate] = useState(false);
  const [notice, setNotice] = useState("");

  const createAccount = (draft: AccountDraft) => {
    // id 与「最近登录」都由服务端在真实实现里返回；演示环境在页面侧生成。
    add(
      toAccountSummary(`account-${Date.now()}`, draft, newAccountLastLogin),
    );
    setNotice(t("accounts.notice.created"));
  };

  const toggleStatus = (id: string) => {
    const account = accounts.find((item) => item.id === id);
    if (!account) return;
    setStatus(id, nextAccountStatus(account.status));
    setNotice(t("accounts.notice.statusChanged"));
  };

  return (
    <>
      <IdentityIntro
        eyebrow="SYSTEM / ACCOUNTS"
        title={t("accounts.intro.title")}
        description={t("accounts.intro.description")}
        action={
          <ActionButton className="primary-button" type="button" onClick={() => setShowCreate(true)}>
            <Plus size={16} /> {t("accounts.action.create")}
          </ActionButton>
        }
      />
      {notice && <div className="identity-notice" role="status">{notice}</div>}
      <AccountCreateDialog
        isOpen={showCreate}
        onOpenChange={setShowCreate}
        onCreate={createAccount}
        onValidationError={setNotice}
      />
      <IdentityPanel title={t("accounts.panel.title")} subtitle={t("accounts.panel.subtitle")}>
        <DataTable className="identity-table" heads={[
            t("accounts.head.username"),
            t("accounts.head.role"),
            t("accounts.head.status"),
            t("accounts.head.lastLogin"),
            t("accounts.head.type"),
            t("accounts.head.actions"),
          ]} rows={accounts.map((account) => (
              <tr key={account.id}>
                <td><div className="identity-user"><UserCircle size={23} /><span><b>{account.username}</b><small>{t(account.builtIn ? "accounts.type.builtInAdmin" : "accounts.type.normal")}</small></span></div></td>
                <td><span className="role-chip"><ShieldCheck size={14} />{t(roleFor(account.roleId).labelKey)}</span></td>
                <td><span className={`status ${account.status === ACCOUNT_STATUS.Active ? "status-healthy" : "status-critical"}`}>{t(account.status === ACCOUNT_STATUS.Active ? "accounts.status.active" : "accounts.status.disabled")}</span></td>
                <td>{account.lastLoginAt}</td>
                <td>{t(account.builtIn ? "accounts.type.builtIn" : "accounts.type.normal")}</td>
                <td><div className="identity-actions"><ActionButton className="link-button" type="button" onClick={() => navigate(ROUTE.Roles, { accountId: account.id })}>{t("accounts.action.bindRole")}</ActionButton><ActionButton className="link-button" type="button" onClick={() => navigate(ROUTE.ChangePassword, { accountId: account.id })}>{t("accounts.action.changePassword")}</ActionButton><ActionButton className="link-button" type="button" onClick={() => toggleStatus(account.id)}>{t(account.status === ACCOUNT_STATUS.Active ? "accounts.action.disable" : "accounts.action.enable")}</ActionButton></div></td>
              </tr>
            ))} />
      </IdentityPanel>
    </>
  );
}
