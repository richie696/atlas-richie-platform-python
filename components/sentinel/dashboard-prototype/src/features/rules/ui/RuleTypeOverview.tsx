import { useTranslation } from "react-i18next";
import { RULE_KINDS, type RuleKind } from "../model/ruleKinds";
import { useRuleCopy } from "../i18n/useRuleCopy";
import styles from "./RuleTypeOverview.module.scss";

/** Makes the five supported Sentinel rule families visible and usable as catalog filters. */
export function RuleTypeOverview({
  selectedKind,
  disabled = false,
  onSelect,
}: {
  readonly selectedKind: RuleKind | null;
  readonly disabled?: boolean;
  readonly onSelect: (kind: RuleKind | null) => void;
}) {
  const { t } = useTranslation();
  const { messages } = useRuleCopy();

  return (
    <section className={styles.overview} aria-labelledby="rule-type-overview-title">
      <div className={styles.heading}>
        <div>
          <h3 id="rule-type-overview-title">
            {t("rules.catalog.ruleTypesTitle", { count: RULE_KINDS.length })}
          </h3>
          <p>{t("rules.catalog.ruleTypesDescription")}</p>
        </div>
        <button
          type="button"
          className={styles.allTypes}
          aria-pressed={selectedKind === null}
          disabled={disabled || selectedKind === null}
          onClick={() => onSelect(null)}
        >
          {t("rules.directory.allKinds")}
        </button>
      </div>
      <div className={styles.types}>
        {RULE_KINDS.map((kind) => {
          const copy = messages.types[kind];
          return (
            <button
              key={kind}
              type="button"
              className={styles.type}
              aria-pressed={selectedKind === kind}
              disabled={disabled}
              data-rule-kind-card={kind}
              onClick={() => onSelect(kind)}
            >
              <span className={styles.typeName}>{copy.label}</span>
              <span className={styles.description}>{copy.description}</span>
              <span className={styles.action}>{t("rules.catalog.viewRuleType")}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
