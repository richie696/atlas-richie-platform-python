import { defineUrlCatalog } from "@richie696/react-framework";
import { IDENTITY_ACCESS_ENDPOINTS, IDENTITY_ACCESS_URLS } from "./identityAccessEndpoints";
import { BOOTSTRAP_SETUP_ENDPOINTS, BOOTSTRAP_SETUP_URLS } from "./bootstrapSetupEndpoints";

/** Combined catalog is retained for protocol export and tests, not imported by app startup. */
export const IDENTITY_URLS = defineUrlCatalog({
  ...IDENTITY_ACCESS_URLS,
  ...BOOTSTRAP_SETUP_URLS,
});
export const IDENTITY_ENDPOINTS = Object.freeze({
  ...IDENTITY_ACCESS_ENDPOINTS,
  ...BOOTSTRAP_SETUP_ENDPOINTS,
});
