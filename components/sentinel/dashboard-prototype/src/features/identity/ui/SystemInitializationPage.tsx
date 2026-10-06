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
import { useTranslator } from "../../../core/i18n/useTranslator";

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

/**
 * First-run setup screen. Production renders it only while the server reports
 * an incomplete bootstrap phase; after success, the parent redirects to login.
 */
export function SystemInitializationPage({ onInitialized }: { onInitialized: () => void }) {
  const t = useTranslator();
  const flow = useSetupFlow();
  const { draft, selectedDatabase, step, stepIndex, isLastStep } = flow;
  const notice =
    flow.notice === null
      ? ""
      : flow.notice.kind === "issue"
        ? t(flow.notice.issue.key)
        : flow.notice.text;

  return (
    <div className="setup-page">
      <section className="setup-shell">
        <div className="setup-brand"><span className="login-mark" aria-hidden="true">↗</span><span>Atlas Richie <b>Sentinel</b></span></div>
        <div className="setup-heading"><span className="eyebrow">FIRST-RUN SETUP</span><h1>{t("setup.intro.title")}</h1><p>{t("setup.intro.description")}</p></div>
        <div className="setup-layout">
          <ol className="setup-steps" aria-label={t("setup.stepsLabel")}>
            {flow.steps.map((item, index) => <li key={item.id} className={index === stepIndex ? "active" : index < stepIndex ? "complete" : ""}><span>{index < stepIndex ? <CheckCircle size={17} weight="fill" /> : `0${index + 1}`}</span><div><b>{t(item.labelKey)}</b><small>{t(item.descriptionKey)}</small></div></li>)}
          </ol>
          <div className="setup-workspace">
            {notice && <div className="identity-notice" role="status">{notice}</div>}
            {step.id === SETUP_STEP.Storage && <>
              <div className="setup-title"><Database size={25} /><div><h2>{t("setup.stage.database.title")}</h2><p>{t("setup.stage.database.description")}</p></div></div>
              <RadioGroup label={t("setup.field.database")} value={draft.databaseKind} onChange={flow.selectDatabase} className="setup-choice" options={CONTROL_PLANE_DATABASES.map((database) => ({ value: database.id, label: database.label, description: t(database.descriptionKey) }))} />
              {selectedDatabase.requiresNetworkConfiguration ? <div className="setup-form-grid"><TextField label={t("setup.field.host")} value={draft.database.host} onChange={(value) => flow.patchDatabase({ host: value })} placeholder="db.internal.example" autoComplete="off" /><TextField label={t("setup.field.port")} value={draft.databasePort} onChange={flow.setDatabasePort} /><TextField label={t("setup.field.databaseName")} value={draft.database.name} onChange={(value) => flow.patchDatabase({ name: value })} autoComplete="off" /><TextField label={t("setup.field.username")} value={draft.database.username} onChange={(value) => flow.patchDatabase({ username: value })} autoComplete="username" /><TextField label={t("setup.field.password")} type="password" value={draft.database.password} onChange={(value) => flow.patchDatabase({ password: value })} autoComplete="new-password" className="wide" /></div> : <div className="setup-local-note">{t("setup.sqliteNote")}</div>}
              <ActionButton className="secondary-button" type="button" onClick={() => flow.reportInfo(t("setup.info.connectionTested"))}>{t("setup.action.testConnection")}</ActionButton>
            </>}
            {step.id === SETUP_STEP.Admin && <>
              <div className="setup-title"><UserCircle size={25} /><div><h2>{t("setup.stage.admin.title")}</h2><p>{t("setup.stage.admin.description")}</p></div></div>
              <div className="setup-form-grid"><TextField label={t("setup.field.adminUsername")} autoComplete="username" value={draft.admin.username} onChange={(value) => flow.patchAdmin({ username: value })} /><TextField label={t("setup.field.adminPassword")} type="password" autoComplete="new-password" value={draft.admin.password} onChange={(value) => flow.patchAdmin({ password: value })} /><TextField label={t("setup.field.adminConfirm")} type="password" autoComplete="new-password" value={draft.admin.confirm} onChange={(value) => flow.patchAdmin({ confirm: value })} /></div>
            </>}
            {step.id === SETUP_STEP.Sources && <>
              <div className="setup-title"><CloudCheck size={25} /><div><h2>{t("setup.stage.source.title")}</h2><p>{t("setup.stage.source.description")}</p></div></div>
              <RadioGroup label={t("setup.field.ruleSource")} value={draft.sourceKind} onChange={flow.selectRuleSource} className="setup-choice" options={RULE_SOURCE_OPTIONS.map((source) => ({ value: source.id, label: source.label, description: t(source.descriptionKey) }))} />
              <div className="setup-form-grid"><TextField label={t("setup.field.serviceAddress")} placeholder={draft.sourceKind === RULE_SOURCE.Nacos ? "https://nacos.example.com" : "https://consul.example.com"} autoComplete="off" value={draft.source.address} onChange={(value) => flow.patchRuleSource({ address: value })} className="wide" /><TextField label={t("setup.field.namespace")} autoComplete="off" value={draft.source.namespace} onChange={(value) => flow.patchRuleSource({ namespace: value })} /></div>
              <fieldset className="setup-authentication"><legend>{t("setup.field.authenticationMode")}</legend><RadioGroup label={t("setup.field.authenticationMode")} value={draft.sourceAuthenticationMode} onChange={flow.selectAuthenticationMode} className="setup-choice" options={RULE_SOURCE_AUTHENTICATION_OPTIONS.map((option) => ({ value: option.id, label: t(option.labelKey), description: t(option.descriptionKey) }))} /></fieldset>
              {draft.sourceAuthenticationMode === RULE_SOURCE_AUTHENTICATION.CredentialReference && <div className="setup-form-grid"><TextField label={t("setup.field.credentialReference")} value={draft.sourceCredentials.reference} onChange={(value) => flow.patchSourceCredentials({ reference: value })} placeholder={t(draft.sourceKind === RULE_SOURCE.Nacos ? "setup.placeholder.nacos" : "setup.placeholder.consul")} autoComplete="off" className="wide" hint={t("setup.credentialReferenceHint")} /></div>}
              {draft.sourceAuthenticationMode === RULE_SOURCE_AUTHENTICATION.Direct && <div className="setup-form-grid"><div className="wide setup-security-note"><LockKey size={17} /><span>{t("setup.directNote")}</span></div>{draft.sourceKind === RULE_SOURCE.Nacos ? <><TextField label={t("setup.field.nacosUsername")} value={draft.sourceCredentials.username} onChange={(value) => flow.patchSourceCredentials({ username: value })} autoComplete="username" /><TextField label={t("setup.field.nacosPassword")} type="password" value={draft.sourceCredentials.password} onChange={(value) => flow.patchSourceCredentials({ password: value })} autoComplete="new-password" /></> : <TextField label={t("setup.field.consulToken")} type="password" value={draft.sourceCredentials.consulToken} onChange={(value) => flow.patchSourceCredentials({ consulToken: value })} autoComplete="new-password" className="wide" />}</div>}
              {draft.sourceAuthenticationMode === RULE_SOURCE_AUTHENTICATION.None && <div className="setup-security-note"><LockKey size={17} /><span>{t("setup.noneNote", { source: draft.sourceKind === RULE_SOURCE.Nacos ? "Nacos" : "Consul" })}</span></div>}
            </>}
            {step.id === SETUP_STEP.Complete && <>
              <div className="setup-title"><CheckCircle size={25} /><div><h2>{t("setup.stage.finish.title")}</h2><p>{t("setup.stage.finish.description")}</p></div></div>
              <div className="setup-summary"><div><b>{t("setup.summary.databaseLabel")}</b><span>{selectedDatabase.usage === "production" ? t("setup.summary.databaseProduction", { label: selectedDatabase.label }) : t("setup.summary.databaseLocal", { label: selectedDatabase.label })}</span></div><div><b>{t("setup.summary.adminLabel")}</b><span>{t("setup.summary.adminValue", { username: draft.admin.username || "admin" })}</span></div><div><b>{t("setup.summary.ruleSource")}</b><span>{draft.sourceKind === RULE_SOURCE.Nacos ? "Nacos" : "Consul"}</span></div></div>
              <div className="identity-warning"><LockKey size={18} /> {t("setup.warning")}</div>
            </>}
            <div className="setup-actions"><ActionButton className="secondary-button" type="button" disabled={flow.isFirstStep} onClick={flow.goBack}>{t("setup.action.back")}</ActionButton>{isLastStep ? <ActionButton className="primary-button" type="button" onClick={onInitialized}>{t("setup.action.finish")}</ActionButton> : <ActionButton className="primary-button" type="button" onClick={flow.goNext}>{t("setup.action.next")} <ArrowRight size={16} /></ActionButton>}</div>
          </div>
        </div>
      </section>
    </div>
  );
}
