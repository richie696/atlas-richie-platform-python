import { useTranslation } from "react-i18next";
import type { ControlPlaneAccessState } from "../../identity";
import { ALL_CAPABILITIES, SESSION_CAPABILITY } from "../../../core/session/capabilities";
import { Panel } from "../../../shared/ui/Panel";
import { FeedbackPanel } from "../../../shared/ui/FeedbackPanel";
import { DataTable } from "../../../shared/ui/DataTable";
import styles from "./SystemObservation.module.scss";
const CAPABILITY_LABEL = Object.freeze({
  [SESSION_CAPABILITY.MetricsView]: "system.session.metrics",
  [SESSION_CAPABILITY.RulesWrite]: "system.session.rules",
});
/** Read the authentication owner's confirmed facts by props. No independent session read/store or editable grant controls. */
export function ObservedPermissionsPanel({ access }: { readonly access: ControlPlaneAccessState }) {
  const { t } = useTranslation();
  if (access.phase !== "resolved" || access.facts.kind !== "authenticated")
    return (
      <FeedbackPanel
        tone="warning"
        copy={{ title: t("system.session.title"), description: t("system.session.unavailable") }}
      />
    );
  const identity = access.facts.identity;
  return (
    <Panel title={t("system.session.title")} subtitle={t("system.session.hint")}>
      <div className={styles.content} data-session-permissions>
        <dl className={styles.facts}>
          <div>
            <dt>{t("system.session.username")}</dt>
            <dd>{identity.username}</dd>
          </div>
          <div>
            <dt>{t("system.session.account")}</dt>
            <dd>{identity.accountId}</dd>
          </div>
          <div>
            <dt>{t("system.session.role")}</dt>
            <dd>
              {t(identity.roleId === "admin" ? "roles.role.admin.title" : "roles.role.view.title")}
            </dd>
          </div>
        </dl>
        <DataTable
          heads={[t("system.session.capability"), t("system.session.granted")]}
          rows={ALL_CAPABILITIES.map((capability) => (
            <tr key={capability} data-session-capability={capability}>
              <td>{t(CAPABILITY_LABEL[capability])}</td>
              <td>
                {t(
                  identity.capabilities.includes(capability)
                    ? "system.session.yes"
                    : "system.session.no",
                )}
              </td>
            </tr>
          ))}
        />
        <p>{t("system.session.fixedRoles")}</p>
      </div>
    </Panel>
  );
}
