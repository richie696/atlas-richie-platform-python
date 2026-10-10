import { MOCK_IDENTITY_SCENARIO } from "../../../src/app/api/mockIdentityScenario";

const { failureMode, storageKeys } = MOCK_IDENTITY_SCENARIO;

/** Select a fixed synthetic state before app startup; no credential or external service is involved. */
const scenario = new URLSearchParams(window.location.search).get("state");
if (scenario === "first-run") {
  window.localStorage.setItem(storageKeys.initialized, "false");
  window.localStorage.setItem(storageKeys.operatorAuthorized, "true");
  window.localStorage.setItem(storageKeys.principal, "anonymous");
  const databaseCheck = new URLSearchParams(window.location.search).get("database-check");
  const sourceCheck = new URLSearchParams(window.location.search).get("source-check");
  if (databaseCheck === failureMode.failOnce)
    window.localStorage.setItem(storageKeys.databaseCheckFailure, failureMode.failOnce);
  else window.localStorage.removeItem(storageKeys.databaseCheckFailure);
  if (sourceCheck === failureMode.failOnce)
    window.localStorage.setItem(storageKeys.sourceCheckFailure, failureMode.failOnce);
  else window.localStorage.removeItem(storageKeys.sourceCheckFailure);
  window.location.replace("/#/setup");
} else if (scenario === "initialized") {
  window.localStorage.setItem(storageKeys.initialized, "true");
  window.localStorage.removeItem(storageKeys.operatorAuthorized);
  window.localStorage.setItem(storageKeys.principal, "anonymous");
  window.localStorage.removeItem(storageKeys.databaseCheckFailure);
  window.localStorage.removeItem(storageKeys.sourceCheckFailure);
  window.location.replace("/#/login");
} else {
  document.body.textContent = "Use ?state=first-run or ?state=initialized.";
}
