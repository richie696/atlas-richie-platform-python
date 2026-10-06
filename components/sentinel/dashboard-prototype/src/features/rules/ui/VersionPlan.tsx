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
import {
  VERSION_STATE,
  VERSION_STATE_TONE,
  type RuleVersion,
  type VersionPlanCopy,
} from "../model/ruleVersion";

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
          className="secondary-button"
          onClick={() => setMessage(`${copy.previewOnly} ${copy.immutable}`)}
        >
          {copy.createVersion}
        </ActionButton>
      }
      className="version-plan-panel"
    >
      <div className="version-plan-list">
        {versions.map((version) => (
          <article
            className={`version-plan version-${version.state}`}
            key={version.id}
          >
            <div className="version-marker" aria-hidden="true" />
            <div className="version-main">
              <div className="version-heading">
                <b>{version.name}</b>
                <code>{version.id}</code>
                <Status tone={VERSION_STATE_TONE[version.state]}>
                  {copy[version.state]}
                </Status>
              </div>
              <span>
                {version.summary} · {version.source} · {version.checksum}
              </span>
            </div>
            {version.state === VERSION_STATE.Scheduled ? (
              <div className="version-window">
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
              <div className="version-window">
                <span>{copy.publishedAt}</span>
                <b>{version.publishedAt}</b>
                <small>
                  {version.state === VERSION_STATE.Active
                    ? copy.noEnd
                    : copy.effectiveWindow}
                </small>
              </div>
            )}
          </article>
        ))}
      </div>
      {message && <div className="version-note">{message}</div>}
    </Panel>
  );
}
