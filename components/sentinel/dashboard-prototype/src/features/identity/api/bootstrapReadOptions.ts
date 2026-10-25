/** Distinguish safe reuse of a confirmed route fact from an explicit server revalidation. */
export interface BootstrapReadOptions {
  readonly forceRefresh?: boolean;
}
