/**
 * Compose owned CSS-module classes with stable semantic hooks during the migration.
 * Unknown hooks pass through; this does not traverse React children or select DOM nodes.
 * Multiple owners support shared presentation primitives without cross-feature imports.
 */
export function scopedClasses(
  modules: readonly Readonly<Record<string, string>>[],
  className: string | undefined,
): string {
  const hooks = className?.split(/\s+/).filter(Boolean) ?? [];
  return [
    ...new Set(
      hooks.flatMap((hook) => [
        hook,
        ...modules.flatMap((module) => (Object.hasOwn(module, hook) ? [module[hook]] : [])),
      ]),
    ),
  ].join(" ");
}
