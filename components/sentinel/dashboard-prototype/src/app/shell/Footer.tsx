import styles from "./AppShell.module.scss";
import { useTranslation } from "react-i18next";

/** Application provenance; never a feature-specific result or health claim. */
export function Footer() {
  const { t } = useTranslation();
  return (
    <footer className={`footer ${styles["footer"]}`}>
      {t("shell.footer.title")} <span>{t("shell.footer.note")}</span>
    </footer>
  );
}
