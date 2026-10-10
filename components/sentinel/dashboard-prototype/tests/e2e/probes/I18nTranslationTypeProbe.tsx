import { useTranslation } from "react-i18next";
import type { TranslationKey } from "../../../src/shared/types/translation";

/** Compile-time probe proving that the UI translator accepts only real JSON keys. */
export function I18nTranslationTypeProbe() {
  const { t } = useTranslation();
  const validDynamicKey: TranslationKey = "shell.nav.overview";

  // @ts-expect-error A misspelled/nonexistent catalog key must stay rejected.
  const invalidKey = t("missing.namespace.key");
  return <span>{`${t(validDynamicKey)}${invalidKey}`}</span>;
}
