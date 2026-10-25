import { useState } from "react";
import { useTranslation } from "react-i18next";
import { LOCALE_OPTIONS, useLocale, useLocaleSetter } from "../i18n/locales";
import { Select } from "../../shared/ui/Select";

const options = LOCALE_OPTIONS.map(({ code, label }) => ({ value: code, label }));

/** App-owned language control shared by public login and documentation routes. */
export function PublicLocaleControl() {
  const { t } = useTranslation();
  const locale = useLocale();
  const setLocale = useLocaleSetter();
  const [failed, setFailed] = useState(false);
  return (
    <Select
      label={t("shell.language")}
      value={locale}
      options={options}
      onChange={(next) => {
        setFailed(false);
        void setLocale(next).catch(() => setFailed(true));
      }}
      error={failed ? t("shell.languageLoadFailed") : undefined}
    />
  );
}
