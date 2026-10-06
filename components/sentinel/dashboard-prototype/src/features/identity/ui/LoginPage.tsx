/**
 * 登录页面容器。
 *
 * 中文
 * ----
 * 登录态由 `core/session` 拥有（阶段 1.4），本页面当前只做演示：本地必填校验通过后
 * 调用路由层的 `navigate`。凭证校验、失败次数限制与令牌下发都必须由服务端完成。
 *
 * 两个字段是页面局部状态，不进任何 store——它们离开本页面即失效，也不该被记住。
 * 必填判断在 `model/account.ts` 的 `validateLoginCredentials`，翻译在
 * `ui/identityCopy`。
 *
 * 页面不套应用壳：没有导航、没有全局筛选，因此也不展示「示例回放」横幅。
 */
import { useState, type FormEvent } from "react";
import { useConsoleGateway } from "../../../core/api/GatewayProvider";
import { useTranslation } from "react-i18next";
import { LockKeyIcon as LockKey } from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { TextField } from "../../../shared/ui/TextField";
import { ROUTE } from "../../../app/router/route.constants";
import type { Navigate } from "../../../shared/types/dashboard";
import { validateLoginCredentials, type LoginCredentials } from "../model/account";
import { useSessionRoleSetter, type SessionRoleId } from "../../../core/session";

const EMPTY_CREDENTIALS: LoginCredentials = { username: "", password: "" };

/** 品牌标记。与初始化页使用同一符号。 */
function ChartLineUpIcon() {
  return <span className="login-mark" aria-hidden="true">↗</span>;
}

export function LoginPage({ navigate }: { navigate: Navigate }) {
  const [credentials, setCredentials] = useState<LoginCredentials>(EMPTY_CREDENTIALS);
  const [message, setMessage] = useState("");
  const { t } = useTranslation();
  // 数据从 gateway 取，页面不感知来源。
  const {accounts: identityAccounts} = useConsoleGateway().readAccountsSync();
  const setRole = useSessionRoleSetter();

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const issues = validateLoginCredentials(credentials);
    if (issues.length > 0) {
      setMessage(t(issues[0].key));
      return;
    }
    // 演示登录：账号名决定角色，角色决定能力快照（`core/session`）。
    // 匹配不到账号时给全量权限——原型没有真实认证，保持「任意用户名可进入」的
    // 既有行为，不在这里制造一个假的登录失败。
    const account = identityAccounts.find(
      (item) => item.username === credentials.username.trim(),
    );
    setRole((account?.roleId ?? "admin") as SessionRoleId);
    navigate(ROUTE.Overview);
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand"><ChartLineUpIcon /><span>Atlas Richie <b>Sentinel</b></span></div>
        <span className="eyebrow">OPERATIONS CONSOLE</span><h1>{t("login.title")}</h1>{/*
          演示账号说明。`core/session` 的受限身份（缺 `rules:write`）如果没有任何
          入口，权限门禁就只是代码里的分支，无法被演示也无法被人工核对。

          这一句随 identity 整页迁 `i18n` 时改写成语言键——本 feature 尚未迁移，
          页面上其它文案目前也都是硬编码，单独为一句建包会让这个文件的文案来源
          更难分辨，而不是更清楚。
        */}
        <p className="login-description">
          {t("login.description")}
        </p>
        {message && <div className="identity-notice" role="alert">{message}</div>}
        <form className="password-form" onSubmit={submit}>
          <TextField label={t("login.field.username")} autoComplete="username" value={credentials.username} onChange={(value) => setCredentials({ ...credentials, username: value })} />
          <TextField label={t("login.field.password")} type="password" autoComplete="current-password" value={credentials.password} onChange={(value) => setCredentials({ ...credentials, password: value })} />
          <ActionButton className="primary-button login-submit" type="submit"><LockKey size={17} /> {t("login.submit")}</ActionButton>
        </form>
      </div>
    </div>
  );
}
