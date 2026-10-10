import { useEffect, useId, useRef, useState } from "react";
import { SignOutIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { IDENTITY_ROLE, type SessionIdentity } from "../../features/identity/authentication";
import { ActionButton } from "../../shared/ui/ActionButton";
import type { Navigate } from "../../shared/types/dashboard";
import { sessionShortcutRoute } from "../router/navigation";
import styles from "./AppShell.module.scss";

/** Session controls rendered only from the app's confirmed, immutable identity snapshot. */
export function UserMenu({
  identity,
  navigate,
  canAdminister,
  isLoggingOut,
  onLogout,
}: {
  readonly identity: SessionIdentity;
  readonly navigate: Navigate;
  readonly canAdminister: boolean;
  readonly isLoggingOut: boolean;
  readonly onLogout: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const target = sessionShortcutRoute(canAdminister);
  const targetLabel = t(canAdminister ? "shell.nav.accounts" : "shell.nav.changePassword");
  const roleLabel = t(
    identity.roleId === IDENTITY_ROLE.Admin ? "roles.role.admin.title" : "roles.role.view.title",
  );

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      root.current?.querySelector<HTMLButtonElement>("[aria-expanded]")?.focus();
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    root.current?.querySelector<HTMLButtonElement>("[data-session-action]")?.focus();
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const initials = [...identity.username.trim()].slice(0, 2).join("").toLocaleUpperCase();
  return (
    <div className={styles["user-menu"]} ref={root}>
      <ActionButton
        className={`avatar ${styles["avatar"]}`}
        type="button"
        aria-label={t("shell.session.open", { username: identity.username })}
        aria-expanded={open}
        aria-controls={menuId}
        disabled={isLoggingOut}
        onClick={() => setOpen((value) => !value)}
      >
        {initials}
      </ActionButton>
      {open && (
        <div
          id={menuId}
          className={styles["user-menu-panel"]}
          role="group"
          aria-label={t("shell.session.menuLabel")}
        >
          <div className={styles["user-menu-identity"]}>
            <span className={styles["user-menu-username"]}>{identity.username}</span>
            <span className={styles["user-menu-role"]}>{roleLabel}</span>
          </div>
          <ActionButton
            data-session-action
            className={styles["user-menu-action"]}
            onClick={() => {
              setOpen(false);
              navigate(target);
            }}
          >
            {targetLabel}
          </ActionButton>
          <ActionButton
            className={styles["user-menu-action"]}
            disabled={isLoggingOut}
            isLoading={isLoggingOut}
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
          >
            <SignOutIcon size={17} aria-hidden="true" />
            {t(isLoggingOut ? "shell.session.signingOut" : "shell.session.signOut")}
          </ActionButton>
        </div>
      )}
    </div>
  );
}
