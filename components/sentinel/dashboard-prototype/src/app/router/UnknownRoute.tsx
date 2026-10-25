import { useTranslation } from "react-i18next";
import { ActionButton } from "../../shared/ui/ActionButton";
import { FeedbackPanel } from "../../shared/ui/FeedbackPanel";

/** Unknown links have an explicit recovery; raw URL input is never reflected as markup. */
export function UnknownRoute({ onHome }: { readonly onHome: () => void }) {
  const { t } = useTranslation();
  return (
    <section data-route-state="not-found">
      <FeedbackPanel
        copy={{ title: t("shell.route.notFound"), description: t("shell.route.notFoundHelp") }}
        actions={<ActionButton onClick={onHome}>{t("shell.route.home")}</ActionButton>}
      />
    </section>
  );
}
