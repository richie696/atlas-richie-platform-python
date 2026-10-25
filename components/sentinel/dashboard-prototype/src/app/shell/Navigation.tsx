import styles from "./AppShell.module.scss";
import { useTranslation } from "react-i18next";
import { ActionButton } from "../../shared/ui/ActionButton";
import type { Navigate } from "../../shared/types/dashboard";
import { navigationItemsForAccess } from "../router/navigation";
import type { RouteId } from "../router/route.constants";

/** Application navigation only; feature content and commands stay outside the shell. */
export function Navigation({
  route,
  navigate,
  canAdminister,
}: {
  readonly route: RouteId;
  readonly navigate: Navigate;
  readonly canAdminister: boolean;
}) {
  const { t } = useTranslation();
  return (
    <nav className={`main-nav ${styles["main-nav"]}`} aria-label={t("shell.language")}>
      {navigationItemsForAccess(canAdminister).map((item) => {
        const Icon = item.icon;
        return (
          <ActionButton
            key={item.id}
            type="button"
            className={route === item.id ? "active" : ""}
            onClick={() => navigate(item.id)}
            onFocus={(event) =>
              event.currentTarget.scrollIntoView({ block: "nearest", inline: "center" })
            }
          >
            <Icon size={16} />
            <span>{t(item.i18nKey)}</span>
          </ActionButton>
        );
      })}
    </nav>
  );
}
