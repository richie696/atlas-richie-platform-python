/** Dependencies owned by the application when changing the active locale. */
export interface LocaleSwitchOperations<Locale extends string> {
  /** Load every catalog needed by the locale before committing it. */
  prepare(locale: Locale): Promise<void>;
  /** Apply the locale to the application-wide translation runtime. */
  apply(locale: Locale): Promise<unknown>;
}

/**
 * Create a latest-request-wins locale switcher.
 *
 * Catalog loading can overlap, but runtime commits are serialized. A superseded
 * request never applies or persists its locale; if it is superseded while an
 * application-level change is already in progress, the newer request commits
 * after it and becomes the final state.
 *
 * @returns A promise resolving to `true` only when this request remained current
 *   through application and its optional persistence callback. Superseded
 *   requests resolve to `false`; preparation/application failures reject.
 */
export function createLatestLocaleSwitcher<Locale extends string>(
  operations: LocaleSwitchOperations<Locale>,
): (locale: Locale, persist?: (locale: Locale) => void) => Promise<boolean> {
  let latestRequest = 0;
  let commitQueue: Promise<void> = Promise.resolve();

  return async (locale, persist) => {
    const request = ++latestRequest;
    await operations.prepare(locale);
    if (request !== latestRequest) return false;

    let committed = false;
    const commit = commitQueue.then(async () => {
      if (request !== latestRequest) return;
      await operations.apply(locale);
      if (request !== latestRequest) return;
      persist?.(locale);
      committed = true;
    });

    // Keep the queue usable after an individual application failure while
    // still returning that failure to the caller.
    commitQueue = commit.then(
      () => undefined,
      () => undefined,
    );
    await commit;
    return committed;
  };
}
