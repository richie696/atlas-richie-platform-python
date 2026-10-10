import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import { createNavigationProtectionRegistry } from "../../shared/state/navigationProtection";
import { NavigationProtectionProvider } from "../../shared/state/NavigationProtectionProvider";
import { DialogFrame } from "../../shared/ui/DialogFrame";
import { ActionButton } from "../../shared/ui/ActionButton";
import { HashNavigationContext } from "./HashNavigationContext";
import { createHashNavigationController } from "./hashNavigationController";
import { createBrowserHashPort } from "./browserHashPort";
/** App-scoped history/confirmation owner; creation has no DOM listener effects and StrictMode cleanup is reusable. */
export function NavigationBoundary({ children }: { readonly children: ReactNode }) {
  const [owners] = useState(() => {
    const registry = createNavigationProtectionRegistry();
    // A 128-bit, non-credential history-session identity also works on private HTTP origins without randomUUID().
    const sessionKey = crypto.getRandomValues(new Uint32Array(4)).join("-");
    return {
      registry,
      controller: createHashNavigationController(createBrowserHashPort(sessionKey), registry),
    };
  });
  const snapshot = useExternalSnapshot(owners.controller),
    { t } = useTranslation();
  useEffect(() => {
    owners.controller.start();
    return () => owners.controller.stop();
  }, [owners]);
  const prompt = snapshot.prompt;
  const description =
    prompt?.kind === "discard-failed"
      ? "shell.navigationGuard.discardFailed"
      : prompt?.kind === "history-failed"
        ? "shell.navigationGuard.historyFailed"
        : prompt?.kind === "locked"
          ? "shell.navigationGuard.locked"
          : "shell.navigationGuard.dirty";
  return (
    <HashNavigationContext value={owners.controller}>
      <NavigationProtectionProvider registry={owners.registry}>
        {children}
        {prompt && (
          <DialogFrame
            isOpen
            isBusy={snapshot.restoring}
            onOpenChange={(open) => {
              if (!open) owners.controller.cancel();
            }}
            title={t("shell.navigationGuard.title")}
            subtitle={t(description)}
            actions={
              <>
                <ActionButton disabled={snapshot.restoring} onClick={owners.controller.cancel}>
                  {t("shell.navigationGuard.stay")}
                </ActionButton>
                {prompt.kind === "dirty" && (
                  <ActionButton
                    disabled={snapshot.restoring}
                    onClick={() => void owners.controller.confirm()}
                  >
                    {t("shell.navigationGuard.discard")}
                  </ActionButton>
                )}
              </>
            }
          >
            <p>{t("shell.navigationGuard.hint")}</p>
          </DialogFrame>
        )}
      </NavigationProtectionProvider>
    </HashNavigationContext>
  );
}
