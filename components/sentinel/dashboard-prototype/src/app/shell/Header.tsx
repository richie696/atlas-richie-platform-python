import presentation from "../../shared/ui/styles/Presentation.module.scss";
import styles from "./AppShell.module.scss";
import { ChartLineUpIcon } from "@phosphor-icons/react";
import { useOnlineStatus } from "@richie696/react-framework-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Select } from "../../shared/ui/Select";
import type { Navigate } from "../../shared/types/dashboard";
import { LOCALE_OPTIONS, useLocale, useLocaleSetter } from "../i18n/locales";
import type { RouteId } from "../router/route.constants";
import { Navigation } from "./Navigation";
import { UserMenu } from "./UserMenu";
import type { SessionIdentity } from "../../features/identity/authentication";

const localeOptions = LOCALE_OPTIONS.map((item) => ({ value: item.code, label: item.label }));

/** Global brand/preferences/browser connectivity. Online does not assert backend health. */
export function Header({
  route,
  navigate,
  canAdminister,
  identity,
  logoutStatus,
  onLogout,
}: {
  readonly route: RouteId;
  readonly navigate: Navigate;
  readonly canAdminister: boolean;
  readonly identity: SessionIdentity;
  readonly logoutStatus: "idle" | "pending" | "success" | "error" | "conflict" | "result-unknown";
  readonly onLogout: () => void;
}) {
  const locale = useLocale();
  const setLocale = useLocaleSetter();
  const [localeLoadFailed, setLocaleLoadFailed] = useState(false);
  const online = useOnlineStatus();
  const { t } = useTranslation();
  const changeLanguage = (next: string) => {
    setLocaleLoadFailed(false);
    void setLocale(next).catch(() => setLocaleLoadFailed(true));
  };
  return (
    <header className={`topbar ${styles["topbar"]}`}>
      <div className={`brand ${styles["brand"]}`}>
        <span className={`brand-mark ${styles["brand-mark"]}`}>
          <ChartLineUpIcon size={23} weight="bold" />
        </span>
        <span>
          Atlas Richie <strong>Sentinel</strong>
        </span>
      </div>
      <Navigation route={route} navigate={navigate} canAdminister={canAdminister} />
      <div className={`header-info ${styles["header-info"]}`}>
        <div className={`locale-control ${styles["locale-control"]}`}>
          <span>{t("shell.language")}</span>
          <Select
            label={t("shell.language")}
            isLabelHidden
            value={locale}
            onChange={changeLanguage}
            options={localeOptions}
            className="locale-selector"
          />
          {localeLoadFailed ? <span role="status">{t("shell.languageLoadFailed")}</span> : null}
        </div>
        <span className={`${styles["browser-status"]} ${online ? "" : "offline-state"}`}>
          <i className={`live-dot ${presentation["live-dot"]}`} />{" "}
          {online ? t("shell.online") : t("shell.offline")}
        </span>
        <span className={`clock ${styles["clock"]}`}>{t("shell.clock.sample")}</span>
        <UserMenu
          identity={identity}
          navigate={navigate}
          canAdminister={canAdminister}
          isLoggingOut={logoutStatus === "pending"}
          onLogout={onLogout}
        />
      </div>
    </header>
  );
}
