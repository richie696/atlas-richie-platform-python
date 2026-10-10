import identityStyles from "./Identity.module.scss";
import introStyles from "../../../shared/ui/Intro.module.scss";
import actionButtonStyles from "../../../shared/ui/ActionButton.module.scss";
import { scopedClasses } from "../../../shared/ui/styles/scopedClasses";
import { CheckCircleIcon, ArrowRightIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { SETUP_STEP, type SetupField } from "../model/setup";
import type { SetupFlow } from "../state/useSetupFlow";
import type { ReactNode } from "react";
import { INITIALIZATION_STEPS } from "../presentation/setupPresentation";
import { SetupStorageStep } from "./setup/SetupStorageStep";
import { SetupAdminStep } from "./setup/SetupAdminStep";
import { SetupSourceStep } from "./setup/SetupSourceStep";
import { SetupReviewStep } from "./setup/SetupReviewStep";

const styleModules = [identityStyles, introStyles, actionButtonStyles] as const;

/** Step anatomy only. The caller owns drafts, validation, effects and completion. */
export function SetupWizard({
  flow,
  onFinish,
  onTestDatabase,
  onTestSource,
  isDatabaseChecking = false,
  isSourceChecking = false,
  feedback,
  isLocked = false,
}: {
  readonly flow: SetupFlow;
  readonly onFinish: () => void;
  readonly onTestDatabase: () => void;
  readonly onTestSource?: () => void;
  readonly isDatabaseChecking?: boolean;
  readonly isSourceChecking?: boolean;
  readonly feedback?: ReactNode;
  readonly isLocked?: boolean;
}) {
  const { t } = useTranslation();
  const { draft, step, stepIndex, isLastStep } = flow;
  const fieldErrors = flow.fieldIssues.reduce<Partial<Record<SetupField, string>>>(
    (errors, issue) => {
      if (issue.field) errors[issue.field] = t(issue.key, issue.params);
      return errors;
    },
    {},
  );
  const hasFieldIssues = flow.fieldIssues.length > 0;
  const notice = flow.notice?.text ?? (hasFieldIssues ? t("setup.validation.summary") : "");

  return (
    <div className={scopedClasses(styleModules, "setup-page")}>
      <section className={scopedClasses(styleModules, "setup-shell")}>
        <div className={scopedClasses(styleModules, "setup-brand")}>
          <span className={scopedClasses(styleModules, "login-mark")} aria-hidden="true">
            ↗
          </span>
          <span>
            Atlas Richie <b>Sentinel</b>
          </span>
        </div>
        <div className={scopedClasses(styleModules, "setup-heading")}>
          <span className={scopedClasses(styleModules, "eyebrow")}>FIRST-RUN SETUP</span>
          <h1>{t("setup.intro.title")}</h1>
          <p>{t("setup.intro.description")}</p>
        </div>
        <div className={scopedClasses(styleModules, "setup-layout")}>
          <ol
            className={scopedClasses(styleModules, "setup-steps")}
            aria-label={t("setup.stepsLabel")}
          >
            {INITIALIZATION_STEPS.map((item, index) => (
              <li
                key={item.id}
                className={scopedClasses(
                  styleModules,
                  index === stepIndex ? "active" : index < stepIndex ? "complete" : "",
                )}
              >
                <span>
                  {index < stepIndex ? (
                    <CheckCircleIcon size={17} weight="fill" />
                  ) : (
                    `0${index + 1}`
                  )}
                </span>
                <div>
                  <b>{t(item.labelKey)}</b>
                  <small>{t(item.descriptionKey)}</small>
                </div>
              </li>
            ))}
          </ol>
          <div className={scopedClasses(styleModules, "setup-workspace")}>
            {feedback}
            <fieldset disabled={isLocked} className={scopedClasses(styleModules, "setup-controls")}>
              {notice && (
                <div
                  className={scopedClasses(styleModules, "identity-notice")}
                  role={hasFieldIssues ? "alert" : "status"}
                >
                  {notice}
                </div>
              )}
              {step === SETUP_STEP.Storage && (
                <SetupStorageStep
                  kind={draft.databaseKind}
                  connection={draft.database}
                  port={draft.databasePort}
                  onKindChange={flow.selectDatabase}
                  onPortChange={flow.setDatabasePort}
                  onConnectionChange={flow.patchDatabase}
                  onTestConnection={onTestDatabase}
                  isChecking={isDatabaseChecking}
                  fieldErrors={fieldErrors}
                />
              )}
              {step === SETUP_STEP.Admin && (
                <SetupAdminStep
                  draft={draft.admin}
                  onChange={flow.patchAdmin}
                  fieldErrors={fieldErrors}
                />
              )}
              {step === SETUP_STEP.Sources && (
                <SetupSourceStep
                  kind={draft.sourceKind}
                  connection={draft.source}
                  mode={draft.sourceAuthenticationMode}
                  credentials={draft.sourceCredentials}
                  onKindChange={flow.selectRuleSource}
                  onConnectionChange={flow.patchRuleSource}
                  onModeChange={flow.selectAuthenticationMode}
                  onCredentialsChange={flow.patchSourceCredentials}
                  onTestConnection={onTestSource}
                  isChecking={isSourceChecking}
                  fieldErrors={fieldErrors}
                />
              )}
              {step === SETUP_STEP.Complete && (
                <SetupReviewStep
                  databaseKind={draft.databaseKind}
                  adminUsername={draft.admin.username}
                  sourceKind={draft.sourceKind}
                />
              )}
              <div className={scopedClasses(styleModules, "setup-actions")}>
                <ActionButton
                  className={scopedClasses(styleModules, "secondary-button")}
                  type="button"
                  disabled={flow.isFirstStep}
                  onClick={flow.goBack}
                >
                  {t("setup.action.back")}
                </ActionButton>
                {isLastStep ? (
                  <ActionButton
                    className={scopedClasses(styleModules, "primary-button")}
                    type="button"
                    onClick={onFinish}
                  >
                    {t("setup.action.finish")}
                  </ActionButton>
                ) : (
                  <ActionButton
                    className={scopedClasses(styleModules, "primary-button")}
                    type="button"
                    onClick={flow.goNext}
                  >
                    {t("setup.action.next")} <ArrowRightIcon size={16} />
                  </ActionButton>
                )}
              </div>
            </fieldset>
          </div>
        </div>
      </section>
    </div>
  );
}
