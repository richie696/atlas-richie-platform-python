import {
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowLeftIcon as ArrowLeft,
  ArrowRightIcon as ArrowRight,
  CheckCircleIcon as CheckCircle,
  CloudCheckIcon as CloudCheck,
  DatabaseIcon as Database,
  KeyIcon as Key,
  LockKeyIcon as LockKey,
  PlusIcon as Plus,
  ShieldCheckIcon as ShieldCheck,
  UserCircleIcon as UserCircle,
} from "@phosphor-icons/react";
import {
  CONTROL_PLANE_DATABASES,
  INITIAL_ACCOUNTS,
  IDENTITY_ROLES,
  INITIALIZATION_STEPS,
  controlPlaneDatabaseFor,
  roleFor,
} from "../model/identityData";
import type {
  AccountSummary,
  ControlPlaneDatabaseKind,
  IdentityRoleId,
} from "../model/identityData";

type Navigate = (next: string, contextId?: string) => void;
type IdentityIntroProps = {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
};
type IdentityPanelProps = {
  title: string;
  subtitle?: string;
  children: ReactNode;
};
type AccountDraft = {
  username: string;
  displayName: string;
  roleId: IdentityRoleId;
};

function IdentityIntro({ eyebrow, title, description, action }: IdentityIntroProps) {
  return (
    <div className="intro identity-intro">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

function IdentityPanel({ title, subtitle, children }: IdentityPanelProps) {
  return (
    <section className="panel identity-panel">
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

function roleLabel(roleId: IdentityRoleId) {
  return roleFor(roleId).label;
}

export function AccountMaintenancePage({ navigate }: { navigate: Navigate }) {
  const [accounts, setAccounts] = useState<AccountSummary[]>(() => INITIAL_ACCOUNTS.map((item) => ({ ...item })));
  const [showCreate, setShowCreate] = useState(false);
  const [notice, setNotice] = useState("");
  const [draft, setDraft] = useState<AccountDraft>({ username: "", displayName: "", roleId: "view" });

  const createAccount = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft.username.trim() || !draft.displayName.trim()) {
      setNotice("请填写登录名和显示名称。");
      return;
    }
    setAccounts((current) => [
      ...current,
      {
        id: `account-${Date.now()}`,
        username: draft.username.trim(),
        displayName: draft.displayName.trim(),
        roleId: draft.roleId,
        status: "active",
        builtIn: false,
        lastLoginAt: "从未登录",
      },
    ]);
    setDraft({ username: "", displayName: "", roleId: "view" });
    setShowCreate(false);
    setNotice("账号已加入演示列表；真实环境需由后台 API 创建并审计。");
  };

  const toggleStatus = (id: string) => {
    setAccounts((current) =>
      current.map((account) =>
        account.id === id
          ? { ...account, status: account.status === "active" ? "disabled" : "active" }
          : account,
      ),
    );
    setNotice("状态变更仅作用于当前演示页面，未写入服务端。");
  };

  return (
    <>
      <IdentityIntro
        eyebrow="SYSTEM / ACCOUNTS"
        title="账户维护"
        description="维护登录身份、状态与角色入口。密码只在后端保存，页面不展示或回显任何凭证。"
        action={
          <button className="primary-button" type="button" onClick={() => setShowCreate((value) => !value)}>
            <Plus size={16} /> 新增账号
          </button>
        }
      />
      {notice && <div className="identity-notice" role="status">{notice}</div>}
      {showCreate && (
        <IdentityPanel title="新增账号" subtitle="创建后由账号本人通过首次登录流程设置密码。">
          <form className="identity-form" onSubmit={createAccount}>
            <label>登录名<input value={draft.username} onChange={(event) => setDraft({ ...draft, username: event.target.value })} autoComplete="off" /></label>
            <label>显示名称<input value={draft.displayName} onChange={(event) => setDraft({ ...draft, displayName: event.target.value })} /></label>
            <label>初始角色<select value={draft.roleId} onChange={(event) => setDraft({ ...draft, roleId: event.target.value as IdentityRoleId })}>{IDENTITY_ROLES.map((role) => <option key={role.id} value={role.id}>{role.label}</option>)}</select></label>
            <div className="identity-form-actions"><button className="secondary-button" type="button" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button" type="submit">创建账号</button></div>
          </form>
        </IdentityPanel>
      )}
      <IdentityPanel title="账号列表" subtitle="内置管理员不可删除；停用账号会立即拒绝新的登录请求。">
        <div className="table-scroll">
          <table className="data-table identity-table">
            <thead><tr><th>账号</th><th>角色</th><th>状态</th><th>最近登录</th><th>类型</th><th>操作</th></tr></thead>
            <tbody>{accounts.map((account) => (
              <tr key={account.id}>
                <td><div className="identity-user"><UserCircle size={23} /><span><b>{account.displayName}</b><small>{account.username}</small></span></div></td>
                <td><span className="role-chip"><ShieldCheck size={14} />{roleLabel(account.roleId)}</span></td>
                <td><span className={`status ${account.status === "active" ? "status-healthy" : "status-critical"}`}>{account.status === "active" ? "启用" : "已停用"}</span></td>
                <td>{account.lastLoginAt}</td>
                <td>{account.builtIn ? "内置账号" : "普通账号"}</td>
                <td><div className="identity-actions"><button className="link-button" type="button" onClick={() => navigate("roles", account.id)}>角色绑定</button><button className="link-button" type="button" onClick={() => navigate("change-password", account.id)}>修改密码</button><button className="link-button" type="button" onClick={() => toggleStatus(account.id)}>{account.status === "active" ? "停用" : "启用"}</button></div></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </IdentityPanel>
    </>
  );
}

export function RoleBindingPage({ navigate, selectedAccountId = "account-admin" }: { navigate: Navigate; selectedAccountId?: string }) {
  const [accounts, setAccounts] = useState<AccountSummary[]>(() => INITIAL_ACCOUNTS.map((item) => ({ ...item })));
  const [accountId, setAccountId] = useState(selectedAccountId);
  const selected = accounts.find((account) => account.id === accountId) ?? accounts[0];
  const role = roleFor(selected.roleId);
  const saveRole = (event: ChangeEvent<HTMLInputElement>) => {
    const roleId = event.target.value as IdentityRoleId;
    setAccounts((current) => current.map((account) => account.id === selected.id ? { ...account, roleId } : account));
  };

  return (
    <>
      <IdentityIntro eyebrow="SYSTEM / ROLE BINDING" title="角色绑定" description="角色是唯一授权入口：admin 可维护规则，view 只能查看指标和事件。" action={<button className="secondary-button" type="button" onClick={() => navigate("accounts")}><ArrowLeft size={16} /> 返回账户维护</button>} />
      <div className="identity-split">
        <IdentityPanel title="选择账号" subtitle="一个账号当前只绑定一个角色，避免权限组合产生歧义。">
          <label className="identity-select">账号<select value={accountId} onChange={(event) => setAccountId(event.target.value)}>{accounts.map((account) => <option key={account.id} value={account.id}>{account.displayName}（{account.username}）</option>)}</select></label>
          <div className="identity-account-summary"><UserCircle size={30} /><div><b>{selected.displayName}</b><small>{selected.builtIn ? "内置管理员账号" : "普通运维账号"}</small></div><span className={`status ${selected.status === "active" ? "status-healthy" : "status-critical"}`}>{selected.status === "active" ? "启用" : "停用"}</span></div>
        </IdentityPanel>
        <IdentityPanel title="绑定角色" subtitle="修改后需要后端记录操作者、原因与生效时间。">
          <div className="role-options">{IDENTITY_ROLES.map((item) => <label className={`role-option ${item.id === role.id ? "selected" : ""}`} key={item.id}><input type="radio" name="role" value={item.id} checked={item.id === role.id} onChange={saveRole} /><span><b>{item.label}</b><small>{item.description}</small><em>{item.permissions.join(" · ")}</em></span></label>)}</div>
          <div className="identity-warning"><ShieldCheck size={18} /> 前端选择只改变演示状态；服务端必须在每次请求重新校验权限。</div>
        </IdentityPanel>
      </div>
    </>
  );
}

export function ChangePasswordPage({ navigate, accountId = "account-admin" }: { navigate: Navigate; accountId?: string }) {
  const account = useMemo(() => INITIAL_ACCOUNTS.find((item) => item.id === accountId) ?? INITIAL_ACCOUNTS[0], [accountId]);
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [message, setMessage] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (form.next.length < 12) return setMessage("新密码至少 12 位，并应包含多种字符类型。");
    if (form.next !== form.confirm) return setMessage("两次输入的新密码不一致。");
    setMessage("演示校验通过；真实环境将调用修改密码 API，不会在页面保存密码。");
    setForm({ current: "", next: "", confirm: "" });
  };
  return (
    <>
      <IdentityIntro eyebrow="SYSTEM / PASSWORD" title="修改密码" description={`为 ${account.displayName}（${account.username}）设置新的登录密码。密码只提交给后端校验，不进入 URL、日志或浏览器存储。`} action={<button className="secondary-button" type="button" onClick={() => navigate("accounts")}><ArrowLeft size={16} /> 返回账户维护</button>} />
      {message && <div className="identity-notice" role="status">{message}</div>}
      <IdentityPanel title="更新登录密码" subtitle="建议使用密码管理器生成唯一密码；修改成功后可使其它会话失效。">
        <form className="password-form" onSubmit={submit}>
          <label><span>当前密码</span><input type="password" autoComplete="current-password" value={form.current} onChange={(event) => setForm({ ...form, current: event.target.value })} /></label>
          <label><span>新密码</span><input type="password" autoComplete="new-password" value={form.next} onChange={(event) => setForm({ ...form, next: event.target.value })} /><small>至少 12 位；不要使用账号名或环境名称。</small></label>
          <label><span>确认新密码</span><input type="password" autoComplete="new-password" value={form.confirm} onChange={(event) => setForm({ ...form, confirm: event.target.value })} /></label>
          <div className="identity-form-actions"><button className="primary-button" type="submit"><Key size={16} /> 保存新密码</button></div>
        </form>
      </IdentityPanel>
    </>
  );
}

export function LoginPage({ navigate }: { navigate: Navigate }) {
  const [credentials, setCredentials] = useState({ username: "", password: "" });
  const [message, setMessage] = useState("");
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (!credentials.username || !credentials.password) return setMessage("请输入登录名和密码。"); navigate("overview"); };
  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand"><ChartLineUpIcon /><span>Atlas Richie <b>Sentinel</b></span></div>
        <span className="eyebrow">OPERATIONS CONSOLE</span><h1>登录控制台</h1><p className="login-description">登录后查看实例运行状态、流量趋势和规则版本。</p>
        {message && <div className="identity-notice" role="alert">{message}</div>}
        <form className="password-form" onSubmit={submit}>
          <label><span>登录名</span><input autoComplete="username" value={credentials.username} onChange={(event) => setCredentials({ ...credentials, username: event.target.value })} /></label>
          <label><span>密码</span><input type="password" autoComplete="current-password" value={credentials.password} onChange={(event) => setCredentials({ ...credentials, password: event.target.value })} /></label>
          <button className="primary-button login-submit" type="submit"><LockKey size={17} /> 登录</button>
        </form>
      </div>
    </div>
  );
}

/**
 * First-run setup screen. Production renders it only while the server reports
 * an incomplete bootstrap phase; after success, the parent redirects to login.
 */
export function SystemInitializationPage({ onInitialized }: { onInitialized: () => void }) {
  const [stepIndex, setStepIndex] = useState(0);
  const [databaseKind, setDatabaseKind] = useState<ControlPlaneDatabaseKind>("postgresql");
  const selectedDatabase = controlPlaneDatabaseFor(databaseKind);
  const [databasePort, setDatabasePort] = useState(selectedDatabase.defaultPort);
  const [sourceKind, setSourceKind] = useState("nacos");
  const [notice, setNotice] = useState("");
  const [admin, setAdmin] = useState({ username: "admin", displayName: "系统管理员", password: "", confirm: "" });
  const step = INITIALIZATION_STEPS[stepIndex];
  const isLastStep = stepIndex === INITIALIZATION_STEPS.length - 1;

  const next = () => {
    if (step.id === "admin") {
      if (!admin.username.trim() || !admin.displayName.trim() || admin.password.length < 12) {
        setNotice("请填写管理员信息，并设置至少 12 位的密码。");
        return;
      }
      if (admin.password !== admin.confirm) {
        setNotice("两次输入的管理员密码不一致。");
        return;
      }
    }
    setNotice("");
    setStepIndex((current) => Math.min(current + 1, INITIALIZATION_STEPS.length - 1));
  };

  const complete = () => {
    onInitialized();
  };

  const selectDatabase = (nextDatabaseKind: ControlPlaneDatabaseKind) => {
    const nextDatabase = controlPlaneDatabaseFor(nextDatabaseKind);
    setDatabaseKind(nextDatabase.id);
    setDatabasePort(nextDatabase.defaultPort);
  };

  return (
    <div className="setup-page">
      <section className="setup-shell">
        <div className="setup-brand"><span className="login-mark" aria-hidden="true">↗</span><span>Atlas Richie <b>Sentinel</b></span></div>
        <div className="setup-heading"><span className="eyebrow">FIRST-RUN SETUP</span><h1>初始化控制面</h1><p>先建立本系统的持久化基础，再创建内置管理员并登记规则配置中心。</p></div>
        <div className="setup-layout">
          <ol className="setup-steps" aria-label="初始化步骤">
            {INITIALIZATION_STEPS.map((item, index) => <li key={item.id} className={index === stepIndex ? "active" : index < stepIndex ? "complete" : ""}><span>{index < stepIndex ? <CheckCircle size={17} weight="fill" /> : `0${index + 1}`}</span><div><b>{item.label}</b><small>{item.description}</small></div></li>)}
          </ol>
          <div className="setup-workspace">
            {notice && <div className="identity-notice" role="status">{notice}</div>}
            {step.id === "storage" && <>
              <div className="setup-title"><Database size={25} /><div><h2>配置系统数据库</h2><p>账户、角色、审计、草稿、规则版本与发布计划需要关系数据库；活动规则仍不直接写入数据库。</p></div></div>
              <div className="setup-choice">{CONTROL_PLANE_DATABASES.map((database) => <label key={database.id}><input type="radio" name="database-kind" checked={databaseKind === database.id} onChange={() => selectDatabase(database.id)} /><span><b>{database.label}</b><small>{database.description}</small></span></label>)}</div>
              {selectedDatabase.requiresNetworkConfiguration ? <div className="setup-form-grid"><label>主机<input placeholder="db.internal.example" autoComplete="off" /></label><label>端口<input value={databasePort} onChange={(event) => setDatabasePort(event.target.value)} inputMode="numeric" /></label><label>数据库名<input defaultValue="sentinel_control" autoComplete="off" /></label><label>用户名<input autoComplete="username" /></label><label className="wide">密码<input type="password" autoComplete="new-password" /></label></div> : <div className="setup-local-note">SQLite 数据文件会保存在服务端的受控数据目录中；浏览器不会保存数据库内容。</div>}
              <button className="secondary-button" type="button" onClick={() => setNotice("演示连接检查通过；真实服务会建立连接、执行迁移并返回 requestId。")}>测试连接并准备数据结构</button>
            </>}
            {step.id === "admin" && <>
              <div className="setup-title"><UserCircle size={25} /><div><h2>创建内置管理员</h2><p>该账号是首个 admin；系统不会生成、展示或保留任何默认密码。</p></div></div>
              <div className="setup-form-grid"><label>登录名<input autoComplete="username" value={admin.username} onChange={(event) => setAdmin({ ...admin, username: event.target.value })} /></label><label>显示名称<input value={admin.displayName} onChange={(event) => setAdmin({ ...admin, displayName: event.target.value })} /></label><label>管理员密码<input type="password" autoComplete="new-password" value={admin.password} onChange={(event) => setAdmin({ ...admin, password: event.target.value })} /></label><label>确认管理员密码<input type="password" autoComplete="new-password" value={admin.confirm} onChange={(event) => setAdmin({ ...admin, confirm: event.target.value })} /></label></div>
            </>}
            {step.id === "sources" && <>
              <div className="setup-title"><CloudCheck size={25} /><div><h2>登记规则配置中心</h2><p>选择本次部署的首个规则来源；稍后可在系统管理中补充另一个来源。</p></div></div>
              <div className="setup-choice"><label><input type="radio" name="source-kind" checked={sourceKind === "nacos"} onChange={() => setSourceKind("nacos")} /><span><b>Nacos</b><small>管理服务通过受控写回流程发布完整规则快照。</small></span></label><label><input type="radio" name="source-kind" checked={sourceKind === "consul"} onChange={() => setSourceKind("consul")} /><span><b>Consul</b><small>与 Nacos 同为规则事实来源，不作为账户或审计存储。</small></span></label></div>
              <div className="setup-form-grid"><label className="wide">服务地址<input placeholder={sourceKind === "nacos" ? "https://nacos.example.com" : "https://consul.example.com"} autoComplete="off" /></label><label>命名空间 / 数据中心<input autoComplete="off" /></label><label>凭证引用<input placeholder="由部署密钥管理系统提供" autoComplete="off" /></label></div>
            </>}
            {step.id === "complete" && <>
              <div className="setup-title"><CheckCircle size={25} /><div><h2>确认并完成</h2><p>完成后，系统写入初始化状态、创建内置管理员并开放登录与控制台 API。</p></div></div>
              <div className="setup-summary"><div><b>系统存储</b><span>{selectedDatabase.usage === "production" ? `${selectedDatabase.label}（生产可用）` : `${selectedDatabase.label}（本地开发）`}</span></div><div><b>内置账号</b><span>{admin.username || "admin"} · admin</span></div><div><b>规则来源</b><span>{sourceKind === "nacos" ? "Nacos" : "Consul"}</span></div></div>
              <div className="identity-warning"><LockKey size={18} /> 初始化是一次性受保护操作。生产环境必须由部署侧提供启动密钥或受管密钥，服务端不得以明文文件保存数据库口令。</div>
            </>}
            <div className="setup-actions"><button className="secondary-button" type="button" disabled={stepIndex === 0} onClick={() => setStepIndex((current) => Math.max(0, current - 1))}>上一步</button>{isLastStep ? <button className="primary-button" type="button" onClick={complete}>完成初始化</button> : <button className="primary-button" type="button" onClick={next}>下一步 <ArrowRight size={16} /></button>}</div>
          </div>
        </div>
      </section>
    </div>
  );
}

function ChartLineUpIcon() { return <span className="login-mark" aria-hidden="true">↗</span>; }
