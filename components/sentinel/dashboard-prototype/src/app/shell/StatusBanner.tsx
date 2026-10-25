import styles from "./AppShell.module.scss";
import { InfoIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";

/** Truthful demo status; this does not claim configuration-center publication. */
export function StatusBanner() {
  const { t } = useTranslation();
  return (
    <div className={`demo-banner ${styles["demo-banner"]}`} role="status">
      <InfoIcon size={16} weight="fill" />
      <span>
        <b>{t("shell.demo")}</b> · {t("shell.demoNotice")}
      </span>
    </div>
  );
}
