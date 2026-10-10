import actionButtonStyles from "../../../shared/ui/ActionButton.module.scss";
import rulesStyles from "./Rules.module.scss";
import { scopedClasses } from "../../../shared/ui/styles/scopedClasses";
/**
 * 规则集版本时间线。
 *
 * 中文
 * ----
 * 纯展示：接收不可变版本列表与文案，渲染生效 / 已计划 / 已归档三种状态的窗口信息。
 * 「创建版本」按钮当前只给出演示提示，**不**产生任何真实版本——真正的版本固化属于
 * 管理服务的发布用例。
 *
 * 版本数据由 props 注入而不是读取全局模块：这样面板可被单独测试，也不会让 rules
 * feature 的 UI 隐式依赖数据来源。
 */
import { useState } from "react";

import { ActionButton } from "../../../shared/ui/ActionButton";
import { Panel } from "../../../shared/ui/Panel";
import { Status } from "../../../shared/ui/Status";
import { VERSION_STATE, type RuleVersion } from "../model/ruleVersion";
import { VERSION_STATE_TONE } from "../presentation/versionPresentation";
import { type VersionPlanCopy } from "../i18n/versionPlanCopy";

const styleModules = [actionButtonStyles, rulesStyles] as const;

export interface VersionPlanProps {
  readonly versions: readonly RuleVersion[];
  readonly copy: VersionPlanCopy;
}

export function VersionPlan({ versions, copy }: VersionPlanProps) {
  const [message, setMessage] = useState("");

  return (
    <Panel
      title={copy.title}
      subtitle={copy.subtitle}
      action={
        <ActionButton
          type="button"
          className={scopedClasses(styleModules, "secondary-button")}
          onClick={() => setMessage(`${copy.previewOnly} ${copy.immutable}`)}
        >
          {copy.createVersion}
        </ActionButton>
      }
      className={scopedClasses(styleModules, "version-plan-panel")}
    >
      <div className={scopedClasses(styleModules, "version-plan-list")}>
        {versions.map((version) => (
          <article
            className={scopedClasses(styleModules, `version-plan version-${version.state}`)}
            key={version.id}
          >
            <div className={scopedClasses(styleModules, "version-marker")} aria-hidden="true" />
            <div className={scopedClasses(styleModules, "version-main")}>
              <div className={scopedClasses(styleModules, "version-heading")}>
                <b>{version.name}</b>
                <code>{version.id}</code>
                <Status tone={VERSION_STATE_TONE[version.state]}>{copy[version.state]}</Status>
              </div>
              <span>
                {version.summary} · {version.source} · {version.checksum}
              </span>
            </div>
            {version.state === VERSION_STATE.Scheduled ? (
              <div className={scopedClasses(styleModules, "version-window")}>
                <span>
                  {copy.plannedWindow} · {copy.timeZone}
                </span>
                <b>
                  {version.startsAt} → {version.endsAt}
                </b>
                <small>
                  {copy.returnTo}: {version.restoreVersion}
                </small>
              </div>
            ) : (
              <div className={scopedClasses(styleModules, "version-window")}>
                <span>{copy.publishedAt}</span>
                <b>{version.publishedAt}</b>
                <small>
                  {version.state === VERSION_STATE.Active ? copy.noEnd : copy.effectiveWindow}
                </small>
              </div>
            )}
          </article>
        ))}
      </div>
      {message && <div className={scopedClasses(styleModules, "version-note")}>{message}</div>}
    </Panel>
  );
}
