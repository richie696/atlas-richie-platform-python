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
import { LockKeyIcon as LockKey } from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { TextField } from "../../../shared/ui/TextField";
import { ROUTE } from "../../../app/router/route.constants";
import type { Navigate } from "../../../shared/types/dashboard";
import { validateLoginCredentials, type LoginCredentials } from "../model/account";
import { identityIssueText } from "./identityCopy";

const EMPTY_CREDENTIALS: LoginCredentials = { username: "", password: "" };

/** 品牌标记。与初始化页使用同一符号。 */
function ChartLineUpIcon() {
  return <span className="login-mark" aria-hidden="true">↗</span>;
}

export function LoginPage({ navigate }: { navigate: Navigate }) {
  const [credentials, setCredentials] = useState<LoginCredentials>(EMPTY_CREDENTIALS);
  const [message, setMessage] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const issues = validateLoginCredentials(credentials);
    if (issues.length > 0) {
      setMessage(identityIssueText(issues[0]));
      return;
    }
    navigate(ROUTE.Overview);
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand"><ChartLineUpIcon /><span>Atlas Richie <b>Sentinel</b></span></div>
        <span className="eyebrow">OPERATIONS CONSOLE</span><h1>登录控制台</h1><p className="login-description">登录后查看实例运行状态、流量趋势和规则版本。</p>
        {message && <div className="identity-notice" role="alert">{message}</div>}
        <form className="password-form" onSubmit={submit}>
          <TextField label="登录名" autoComplete="username" value={credentials.username} onChange={(value) => setCredentials({ ...credentials, username: value })} />
          <TextField label="密码" type="password" autoComplete="current-password" value={credentials.password} onChange={(value) => setCredentials({ ...credentials, password: value })} />
          <ActionButton className="primary-button login-submit" type="submit"><LockKey size={17} /> 登录</ActionButton>
        </form>
      </div>
    </div>
  );
}
