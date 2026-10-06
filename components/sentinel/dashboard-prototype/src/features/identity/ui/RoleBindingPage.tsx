/**
 * 角色绑定页面容器。
 *
 * 中文
 * ----
 * 页面只做三件事：订阅账号列表、组合左右两个面板、把单选结果映射为 store 命令。
 *
 * 与旧实现的两处差别：
 *
 * 1. **状态归属**：账号列表改为订阅 `state/accountStore`，不再是本页面私有的
 *    `useState` 副本，因此在账户维护页新建的账号在这里立即可选，改过的角色回到账户
 *    维护页也不会回退。
 * 2. **协议值收窄**：旧的 `const roleId = roleIdValue as IdentityRoleId` 让任意字符串
 *    都能变成角色 id。现在交给 `isIdentityRoleId` 守卫——不是受支持的协议值就保持当前
 *    选择，而不是把未知值写进账号。
 *
 * `accountId` 是**可分享的导航上下文**（URL query），因此由路由层持有并作为 prop 传入，
 * 不在页面里另存一份。
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowLeftIcon as ArrowLeft,
  ShieldCheckIcon as ShieldCheck,
  UserCircleIcon as UserCircle,
} from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { Select } from "../../../shared/ui/Select";
import { RadioGroup } from "../../../shared/ui/RadioGroup";
import { ROUTE } from "../../../app/router/route.constants";
import type { Navigate } from "../../../shared/types/dashboard";
import { ACCOUNT_STATUS, IDENTITY_ROLES, isIdentityRoleId, roleFor } from "../model/account";
import { INITIAL_ACCOUNTS } from "../fixtures/identityFixtures";
import { loadAccounts, useAccounts } from "../state/accountStore";
import { IdentityIntro } from "./components/IdentityIntro";
import { IdentityPanel } from "./components/IdentityPanel";

// 与 `AccountMaintenancePage` 相同的演示装配，命令幂等：先执行者生效。
// 生产实现由 `identity.gateway` 装载真实快照。
loadAccounts(INITIAL_ACCOUNTS);

/** 未指定账号时的演示默认值。真实默认值来自会话。 */
const DEFAULT_ACCOUNT_ID = "account-admin";

export function RoleBindingPage({ navigate, selectedAccountId = DEFAULT_ACCOUNT_ID }: { navigate: Navigate; selectedAccountId?: string }) {
  const { t } = useTranslation();
  const { accounts, setRole } = useAccounts();
  const [accountId, setAccountId] = useState(selectedAccountId);
  const selected = accounts.find((account) => account.id === accountId) ?? accounts[0];
  const role = roleFor(selected.roleId);

  const saveRole = (roleIdValue: string) => {
    if (!isIdentityRoleId(roleIdValue)) return;
    setRole(selected.id, roleIdValue);
  };

  return (
    <>
      <IdentityIntro eyebrow="SYSTEM / ROLE BINDING" title={t("roles.intro.title")} description={t("roles.intro.description")} action={<ActionButton className="secondary-button" type="button" onClick={() => navigate(ROUTE.Accounts)}><ArrowLeft size={16} /> {t("roles.action.back")}</ActionButton>} />
      <div className="identity-split">
        <IdentityPanel title={t("roles.accountPanel.title")} subtitle={t("roles.accountPanel.subtitle")}>
          <div className="identity-select">
            <Select label={t("roles.field.account")} value={accountId} onChange={setAccountId} options={accounts.map((account) => ({ value: account.id, label: account.username }))} />
          </div>
          <div className="identity-account-summary"><UserCircle size={30} /><div><b>{selected.username}</b><small>{t(selected.builtIn ? "accounts.type.builtInAdmin" : "accounts.type.normal")}</small></div><span className={`status ${selected.status === ACCOUNT_STATUS.Active ? "status-healthy" : "status-critical"}`}>{t(selected.status === ACCOUNT_STATUS.Active ? "accounts.status.active" : "accounts.status.disabled")}</span></div>
        </IdentityPanel>
        <IdentityPanel title={t("roles.bindingPanel.title")} subtitle={t("roles.bindingPanel.subtitle")}>
          <RadioGroup label={t("roles.field.binding")} value={role.id} onChange={saveRole} className="role-options" options={IDENTITY_ROLES.map((item) => ({ value: item.id, label: t(item.labelKey), description: <>{t(item.descriptionKey)}<br /><em>{item.permissions.join(" · ")}</em></> }))} />
          <div className="identity-warning"><ShieldCheck size={18} /> {t("roles.warning")}</div>
        </IdentityPanel>
      </div>
    </>
  );
}
