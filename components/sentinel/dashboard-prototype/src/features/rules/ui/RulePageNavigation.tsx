import { useTranslation } from "react-i18next";
import {
  primaryRulePageSection,
  RULE_PAGE_SECTION,
  type RulePageSection,
} from "../model/rulePageSection";
import styles from "./RulePageNavigation.module.scss";

const PRIMARY_ITEMS = [
  { section: RULE_PAGE_SECTION.Catalog, label: "rules.sections.catalog" },
  { section: RULE_PAGE_SECTION.Runtime, label: "rules.sections.runtime" },
  { section: RULE_PAGE_SECTION.Bindings, label: "rules.sections.bindings" },
  { section: "maintenance", label: "rules.sections.maintenance" },
] as const;

const MAINTENANCE_ITEMS = [
  { section: RULE_PAGE_SECTION.Editor, label: "rules.sections.editor" },
  { section: RULE_PAGE_SECTION.Drafts, label: "rules.sections.drafts" },
  { section: RULE_PAGE_SECTION.Publications, label: "rules.sections.publications" },
  { section: RULE_PAGE_SECTION.Recovery, label: "rules.sections.recovery" },
] as const;

/** URL-backed navigation separates daily rule reading from lifecycle administration. */
export function RulePageNavigation({
  section,
  onSelect,
}: {
  readonly section: RulePageSection;
  readonly onSelect: (section: RulePageSection) => void;
}) {
  const { t } = useTranslation();
  const primary = primaryRulePageSection(section);
  return (
    <div className={styles.navigation}>
      <nav className={styles.primary} aria-label={t("rules.sections.primaryNavigation")}>
        {PRIMARY_ITEMS.map((item) => {
          const active = item.section === primary;
          return (
            <button
              key={item.section}
              type="button"
              className={styles.item}
              aria-current={active ? "page" : undefined}
              onClick={() =>
                onSelect(item.section === "maintenance" ? RULE_PAGE_SECTION.Editor : item.section)
              }
            >
              {t(item.label)}
            </button>
          );
        })}
      </nav>
      {primary === "maintenance" && (
        <nav className={styles.secondary} aria-label={t("rules.sections.maintenanceNavigation")}>
          {MAINTENANCE_ITEMS.map((item) => (
            <button
              key={item.section}
              type="button"
              className={styles.item}
              aria-current={section === item.section ? "page" : undefined}
              onClick={() => onSelect(item.section)}
            >
              {t(item.label)}
            </button>
          ))}
        </nav>
      )}
    </div>
  );
}
