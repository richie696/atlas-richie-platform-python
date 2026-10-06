/**
 * 首次初始化页面容器。
 *
 * 中文
 * ----
 * 页面只做三件事：取 `useSetupFlow` 的状态机、组合四个步骤的表单区块、把用户动作映射
 * 为命令。
 *
 * 旧实现在同一个组件里摊开 8 个 `useState` 与三段内联校验，页面同时是状态机、校验器
 * 和展示层。现在：
 *
 * - 步骤迁移与草稿字段归 `state/useSetupFlow`；
 * - 「这一步允许提交什么」归 `model/setup.ts` 的 `validateSetupStep`，返回消息键 + 参数；
 * - 三个单选控件的 `value as XxxKind` 断言换成守卫收窄，非法值保持原状态；
 * - 四个步骤的 JSX 原样保留：class 由全局样式驱动，改动会直接改变展示。
 *
 * 一次性窗口的治理在**服务端**：初始化成功后服务端关闭该窗口，重复访问拒绝，客户端把
 * `#/setup` 深链重定向到登录页（`REWRITE_PLAN` §4.7）。本页没有「返回登录」入口。
 */
import { CheckCircleIcon as CheckCircle, CloudCheckIcon as CloudCheck, DatabaseIcon as Database, ArrowRightIcon as ArrowRight, LockKeyIcon as LockKey, UserCircleIcon as UserCircle } from "@phosphor-icons/react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { TextField } from "../../../shared/ui/TextField";
import { RadioGroup } from "../../../shared/ui/RadioGroup";
import {
  CONTROL_PLANE_DATABASES,
  RULE_SOURCE_AUTHENTICATION,
  RULE_SOURCE_AUTHENTICATION_OPTIONS,
  RULE_SOURCE_OPTIONS,
  RULE_SOURCE,
  SETUP_STEP,
} from "../model/setup";
import { useSetupFlow } from "../state/useSetupFlow";
import { identityIssueText } from "./identityCopy";

/**
 * First-run setup screen. Production renders it only while the server reports
 * an incomplete bootstrap phase; after success, the parent redirects to login.
 */
export function SystemInitializationPage({ onInitialized }: { onInitialized: () => void }) {
  const flow = useSetupFlow();
  const { draft, selectedDatabase, step, stepIndex, isLastStep } = flow;
  const notice =
    flow.notice === null
      ? ""
      : flow.notice.kind === "issue"
        ? identityIssueText(flow.notice.issue)
        : flow.notice.text;

  return (
    <div className="setup-page">
      <section className="setup-shell">
        <div className="setup-brand"><span className="login-mark" aria-hidden="true">↗</span><span>Atlas Richie <b>Sentinel</b></span></div>
        <div className="setup-heading"><span className="eyebrow">FIRST-RUN SETUP</span><h1>初始化控制面</h1><p>先建立本系统的持久化基础，再创建内置管理员并登记规则配置中心。</p></div>
        <div className="setup-layout">
          <ol className="setup-steps" aria-label="初始化步骤">
            {flow.steps.map((item, index) => <li key={item.id} className={index === stepIndex ? "active" : index < stepIndex ? "complete" : ""}><span>{index < stepIndex ? <CheckCircle size={17} weight="fill" /> : `0${index + 1}`}</span><div><b>{item.label}</b><small>{item.description}</small></div></li>)}
          </ol>
          <div className="setup-workspace">
            {notice && <div className="identity-notice" role="status">{notice}</div>}
            {step.id === SETUP_STEP.Storage && <>
              <div className="setup-title"><Database size={25} /><div><h2>配置系统数据库</h2><p>账户、角色、审计、草稿、规则版本与发布计划需要关系数据库；活动规则仍不直接写入数据库。</p></div></div>
              <RadioGroup label="系统数据库" value={draft.databaseKind} onChange={flow.selectDatabase} className="setup-choice" options={CONTROL_PLANE_DATABASES.map((database) => ({ value: database.id, label: database.label, description: database.description }))} />
              {selectedDatabase.requiresNetworkConfiguration ? <div className="setup-form-grid"><TextField label="主机" value={draft.database.host} onChange={(value) => flow.patchDatabase({ host: value })} placeholder="db.internal.example" autoComplete="off" /><TextField label="端口" value={draft.databasePort} onChange={flow.setDatabasePort} /><TextField label="数据库名" value={draft.database.name} onChange={(value) => flow.patchDatabase({ name: value })} autoComplete="off" /><TextField label="用户名" value={draft.database.username} onChange={(value) => flow.patchDatabase({ username: value })} autoComplete="username" /><TextField label="密码" type="password" value={draft.database.password} onChange={(value) => flow.patchDatabase({ password: value })} autoComplete="new-password" className="wide" /></div> : <div className="setup-local-note">SQLite 数据文件会保存在服务端的受控数据目录中；浏览器不会保存数据库内容。</div>}
              <ActionButton className="secondary-button" type="button" onClick={() => flow.reportInfo("演示连接检查通过；真实服务会建立连接、执行迁移并返回 requestId。")}>测试连接并准备数据结构</ActionButton>
            </>}
            {step.id === SETUP_STEP.Admin && <>
              <div className="setup-title"><UserCircle size={25} /><div><h2>创建内置管理员</h2><p>该账号是首个 admin；系统不会生成、展示或保留任何默认密码。</p></div></div>
              <div className="setup-form-grid"><TextField label="账号名" autoComplete="username" value={draft.admin.username} onChange={(value) => flow.patchAdmin({ username: value })} /><TextField label="管理员密码" type="password" autoComplete="new-password" value={draft.admin.password} onChange={(value) => flow.patchAdmin({ password: value })} /><TextField label="确认管理员密码" type="password" autoComplete="new-password" value={draft.admin.confirm} onChange={(value) => flow.patchAdmin({ confirm: value })} /></div>
            </>}
            {step.id === SETUP_STEP.Sources && <>
              <div className="setup-title"><CloudCheck size={25} /><div><h2>登记规则配置中心</h2><p>选择本次部署的首个规则来源；稍后可在系统管理中补充另一个来源。</p></div></div>
              <RadioGroup label="规则来源" value={draft.sourceKind} onChange={flow.selectRuleSource} className="setup-choice" options={RULE_SOURCE_OPTIONS.map((source) => ({ value: source.id, label: source.label, description: source.description }))} />
              <div className="setup-form-grid"><TextField label="服务地址" placeholder={draft.sourceKind === RULE_SOURCE.Nacos ? "https://nacos.example.com" : "https://consul.example.com"} autoComplete="off" value={draft.source.address} onChange={(value) => flow.patchRuleSource({ address: value })} className="wide" /><TextField label="命名空间 / 数据中心" autoComplete="off" value={draft.source.namespace} onChange={(value) => flow.patchRuleSource({ namespace: value })} /></div>
              <fieldset className="setup-authentication"><legend>认证方式</legend><RadioGroup label="认证方式" value={draft.sourceAuthenticationMode} onChange={flow.selectAuthenticationMode} className="setup-choice" options={RULE_SOURCE_AUTHENTICATION_OPTIONS.map((option) => ({ value: option.id, label: option.label, description: option.description }))} /></fieldset>
              {draft.sourceAuthenticationMode === RULE_SOURCE_AUTHENTICATION.CredentialReference && <div className="setup-form-grid"><TextField label="部署凭证引用" value={draft.sourceCredentials.reference} onChange={(value) => flow.patchSourceCredentials({ reference: value })} placeholder={draft.sourceKind === RULE_SOURCE.Nacos ? "例如：secret://sentinel/nacos-prod" : "例如：secret://sentinel/consul-prod"} autoComplete="off" className="wide" hint="填写密钥管理系统、Kubernetes Secret 或部署配置中的引用地址；不要填写密码、Token 或私钥。" /></div>}
              {draft.sourceAuthenticationMode === RULE_SOURCE_AUTHENTICATION.Direct && <div className="setup-form-grid"><div className="wide setup-security-note"><LockKey size={17} /><span>适用于受控内网。凭证只会通过 TLS 写入式提交给后台；浏览器不会保存、回显或再次读取它。</span></div>{draft.sourceKind === RULE_SOURCE.Nacos ? <><TextField label="Nacos 用户名" value={draft.sourceCredentials.username} onChange={(value) => flow.patchSourceCredentials({ username: value })} autoComplete="username" /><TextField label="Nacos 密码" type="password" value={draft.sourceCredentials.password} onChange={(value) => flow.patchSourceCredentials({ password: value })} autoComplete="new-password" /></> : <TextField label="Consul ACL Token" type="password" value={draft.sourceCredentials.consulToken} onChange={(value) => flow.patchSourceCredentials({ consulToken: value })} autoComplete="new-password" className="wide" />}</div>}
              {draft.sourceAuthenticationMode === RULE_SOURCE_AUTHENTICATION.None && <div className="setup-security-note"><LockKey size={17} /><span>将以匿名方式连接 {draft.sourceKind === RULE_SOURCE.Nacos ? "Nacos" : "Consul"}。请仅在网络隔离、访问控制与 TLS 已由部署环境保障时使用。</span></div>}
            </>}
            {step.id === SETUP_STEP.Complete && <>
              <div className="setup-title"><CheckCircle size={25} /><div><h2>确认并完成</h2><p>完成后，系统写入初始化状态、创建内置管理员并开放登录与控制台 API。</p></div></div>
              <div className="setup-summary"><div><b>系统存储</b><span>{selectedDatabase.usage === "production" ? `${selectedDatabase.label}（生产可用）` : `${selectedDatabase.label}（本地开发）`}</span></div><div><b>内置账号</b><span>{draft.admin.username || "admin"} · admin</span></div><div><b>规则来源</b><span>{draft.sourceKind === RULE_SOURCE.Nacos ? "Nacos" : "Consul"}</span></div></div>
              <div className="identity-warning"><LockKey size={18} /> 初始化是一次性受保护操作。生产环境必须由部署侧提供启动密钥或受管密钥，服务端不得以明文文件保存数据库口令。</div>
            </>}
            <div className="setup-actions"><ActionButton className="secondary-button" type="button" disabled={flow.isFirstStep} onClick={flow.goBack}>上一步</ActionButton>{isLastStep ? <ActionButton className="primary-button" type="button" onClick={onInitialized}>完成初始化</ActionButton> : <ActionButton className="primary-button" type="button" onClick={flow.goNext}>下一步 <ArrowRight size={16} /></ActionButton>}</div>
          </div>
        </div>
      </section>
    </div>
  );
}
