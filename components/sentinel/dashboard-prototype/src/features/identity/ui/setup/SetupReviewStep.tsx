import { CheckCircleIcon, LockKeyIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { RULE_SOURCE, type ControlPlaneDatabaseKind, type RuleSourceKind } from "../../model/setup";
import { setupDatabasePresentationFor } from "../../presentation/setupPresentation";
import { SetupStepHeading } from "./SetupStepHeading";
import { setupClass } from "./setupStyle";

/** Non-sensitive review: no password, token, reference or connection draft is accepted by this component. */
export function SetupReviewStep({
  databaseKind,
  adminUsername,
  sourceKind,
}: {
  readonly databaseKind: ControlPlaneDatabaseKind;
  readonly adminUsername: string;
  readonly sourceKind: RuleSourceKind;
}) {
  const { t } = useTranslation();
  const database = setupDatabasePresentationFor(databaseKind);
  return (
    <>
      <SetupStepHeading
        icon={<CheckCircleIcon size={25} />}
        title={t("setup.stage.finish.title")}
        description={t("setup.stage.finish.description")}
      />
      <div className={setupClass("setup-summary")}>
        <div>
          <b>{t("setup.summary.databaseLabel")}</b>
          <span>
            {t(
              database.usage === "production"
                ? "setup.summary.databaseProduction"
                : "setup.summary.databaseLocal",
              { label: database.label },
            )}
          </span>
        </div>
        <div>
          <b>{t("setup.summary.adminLabel")}</b>
          <span>{t("setup.summary.adminValue", { username: adminUsername })}</span>
        </div>
        <div>
          <b>{t("setup.summary.ruleSource")}</b>
          <span>{sourceKind === RULE_SOURCE.Nacos ? "Nacos" : "Consul"}</span>
        </div>
      </div>
      <div className={setupClass("identity-warning")}>
        <LockKeyIcon size={18} />
        {t("setup.warning")}
      </div>
    </>
  );
}
