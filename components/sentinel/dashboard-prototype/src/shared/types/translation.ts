import type { ParseKeys, TFunction } from "i18next";

/** Flat JSON locale resources. Key presence/interpolation is checked by i18n gates. */
export type MessageBundle = Readonly<Record<string, string>>;

/** Non-sensitive interpolation values; this is not a translation runtime. */
export type MessageValues = Readonly<Record<string, string | number>>;

/** Valid translation keys exposed by the application's typed i18next instance. */
export type TranslationKey = ParseKeys<"translation">;

/** Presentational translation callback constrained by the resource-derived key contract. */
export type Translate = (key: TranslationKey, values?: MessageValues) => string;
