import type { Locale } from "./locales";
import { assembleMessageCatalog } from "./catalog";

type MessageFile = Readonly<Record<string, unknown>>;
type MessageFileLoader = () => Promise<{ readonly default: MessageFile }>;
type LocaleCatalogLoader = () => Promise<Readonly<Record<string, string>>>;

const bundleNames = Object.freeze([
  "shell",
  "overview",
  "faults",
  "applications",
  "realtime",
  "rules",
  "system",
  "identity",
  "observation",
] as const);

/** Explicit paths make adding or removing a locale bundle a compile-time edit. */
const bundlesByLocale: Readonly<Record<Locale, readonly MessageFileLoader[]>> = Object.freeze({
  "zh-CN": [
    () => import("./messages/zh-CN/shell.json"),
    () => import("./messages/zh-CN/overview.json"),
    () => import("./messages/zh-CN/faults.json"),
    () => import("./messages/zh-CN/applications.json"),
    () => import("./messages/zh-CN/realtime.json"),
    () => import("./messages/zh-CN/rules.json"),
    () => import("./messages/zh-CN/system.json"),
    () => import("./messages/zh-CN/identity.json"),
    () => import("./messages/zh-CN/observation.json"),
  ],
  "en-US": [
    () => import("./messages/en-US/shell.json"),
    () => import("./messages/en-US/overview.json"),
    () => import("./messages/en-US/faults.json"),
    () => import("./messages/en-US/applications.json"),
    () => import("./messages/en-US/realtime.json"),
    () => import("./messages/en-US/rules.json"),
    () => import("./messages/en-US/system.json"),
    () => import("./messages/en-US/identity.json"),
    () => import("./messages/en-US/observation.json"),
  ],
  "ja-JP": [
    () => import("./messages/ja-JP/shell.json"),
    () => import("./messages/ja-JP/overview.json"),
    () => import("./messages/ja-JP/faults.json"),
    () => import("./messages/ja-JP/applications.json"),
    () => import("./messages/ja-JP/realtime.json"),
    () => import("./messages/ja-JP/rules.json"),
    () => import("./messages/ja-JP/system.json"),
    () => import("./messages/ja-JP/identity.json"),
    () => import("./messages/ja-JP/observation.json"),
  ],
});

const loadedCatalogs = new Map<Locale, Promise<Readonly<Record<string, string>>>>();

async function assembleLocaleCatalog(locale: Locale): Promise<Readonly<Record<string, string>>> {
  const modules = await Promise.all(bundlesByLocale[locale].map((load) => load()));
  const bundles = Object.fromEntries(
    bundleNames.map((name, index) => [name, modules[index]!.default]),
  );
  return assembleMessageCatalog(locale, bundles);
}

/**
 * Load and memoize only the requested locale. A failed chunk load is evicted so
 * a later user retry can request it again instead of retaining a rejected promise.
 */
export function loadMessageCatalog(locale: Locale): Promise<Readonly<Record<string, string>>> {
  let loaded = loadedCatalogs.get(locale);
  if (!loaded) {
    loaded = assembleLocaleCatalog(locale);
    loadedCatalogs.set(locale, loaded);
    void loaded.catch(() => loadedCatalogs.delete(locale));
  }
  return loaded;
}
