/** Bootstrap operator authorization is not administrator authentication and cannot reopen a closed setup window. */
export type BootstrapOperatorGate =
  { readonly kind: "closed" } | { readonly kind: "open"; readonly authorized: boolean };
