/** File ownership is independent of i18next's flat runtime namespace. */
export const MESSAGE_OWNERS = Object.freeze({
  applications: ["applications"],
  faults: ["faults"],
  identity: [
    "account",
    "accountDialog",
    "accounts",
    "changePassword",
    "login",
    "password",
    "roles",
    "setup",
    "management",
  ],
  observation: ["observation"],
  overview: ["overview"],
  realtime: ["realtime"],
  rules: ["rules"],
  shell: ["shell"],
  system: ["system"],
} as const);

/** Canonical placeholder identity for runtime resources and extraction tests. */
export function interpolationNames(message: string): readonly string[] {
  return [
    ...new Set(
      [...message.matchAll(/\{\{\s*-?\s*([^{}]+)\}\}/g)].map((match) =>
        match[1]!.split(",")[0]!.trim(),
      ),
    ),
  ].sort();
}

/** Assemble one locale without inherited-key collisions, silent file omissions or cross-feature ownership. */
export function assembleMessageCatalog(
  locale: string,
  bundles: Readonly<Record<string, Readonly<Record<string, unknown>>>>,
): Readonly<Record<string, string>> {
  const expected = Object.keys(MESSAGE_OWNERS).sort();
  if (JSON.stringify(Object.keys(bundles).sort()) !== JSON.stringify(expected))
    throw new Error(`Invalid i18n file set: ${locale}`);
  const merged: Record<string, string> = Object.create(null) as Record<string, string>;
  for (const name of expected) {
    const roots: readonly string[] = MESSAGE_OWNERS[name as keyof typeof MESSAGE_OWNERS];
    for (const [key, value] of Object.entries(bundles[name]!)) {
      if (typeof value !== "string" || !value.trim())
        throw new Error(`Invalid i18n message: ${locale}/${name}/${key}`);
      if (!roots.includes(key.split(".")[0]!) || !key.includes("."))
        throw new Error(`Invalid i18n owner: ${locale}/${name}/${key}`);
      if (Object.hasOwn(merged, key)) throw new Error(`Duplicate i18n key: ${locale}/${key}`);
      merged[key] = value;
    }
  }
  return Object.freeze(merged);
}

/** Reject divergent keys/placeholders and incomplete English count forms before rendering any locale. */
export function validateCatalogTranslations(
  catalogs: Readonly<Record<string, Readonly<Record<string, string>>>>,
): void {
  const base = catalogs["zh-CN"];
  if (!base || !catalogs["en-US"] || !catalogs["ja-JP"] || Object.keys(catalogs).length !== 3)
    throw new Error("Invalid i18n locale set");
  const keys = Object.keys(base).sort();
  for (const [locale, messages] of Object.entries(catalogs)) {
    if (JSON.stringify(Object.keys(messages).sort()) !== JSON.stringify(keys))
      throw new Error(`Invalid i18n key set: ${locale}`);
    for (const key of keys) {
      if (
        JSON.stringify(interpolationNames(base[key]!)) !==
        JSON.stringify(interpolationNames(messages[key]!))
      )
        throw new Error(`Invalid i18n placeholders: ${locale}/${key}`);
      if (
        locale === "en-US" &&
        !/_(one|other)$/.test(key) &&
        interpolationNames(messages[key]!).includes("count")
      ) {
        for (const suffix of ["one", "other"])
          if (!Object.hasOwn(messages, `${key}_${suffix}`))
            throw new Error(`Missing i18n plural: ${key}_${suffix}`);
      }
    }
  }
}
