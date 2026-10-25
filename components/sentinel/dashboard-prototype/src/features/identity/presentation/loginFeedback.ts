import { AppErrorKind } from "@richie696/react-framework";
import { CONSOLE_ERROR_STATUS } from "../../../core/api/protocol/common";
import type { AuthenticationSnapshot } from "../application/authenticationWorkflow";
import type { MessageValues, TranslationKey } from "../../../shared/types/translation";
import { loginRetryDelayMs } from "../model/loginRetry";

export { loginRetryDelayMs } from "../model/loginRetry";

/** Display decisions only. This projection cannot grant authentication or issue a request. */
export interface LoginFeedback {
  readonly key: TranslationKey;
  readonly tone: "info" | "warning" | "error";
  readonly busy: boolean;
  readonly canInspect: boolean;
  readonly values?: MessageValues;
}

/** Map confirmed access/command facts to safe wording; never expose exception messages. */
export function loginFeedback(
  { access, login }: AuthenticationSnapshot,
  retryAfterSeconds = 0,
): LoginFeedback | null {
  function describe(
    key: TranslationKey,
    tone: LoginFeedback["tone"] = "info",
    canInspect = false,
    busy = false,
  ): LoginFeedback {
    return { key, tone, canInspect, busy };
  }
  if (login.status === "result-unknown") return describe("login.remote.unknown", "warning", true);
  if (access.phase === "unavailable") return describe("login.remote.unavailable", "error", true);
  if (access.phase === "expired") return describe("login.remote.sessionExpired", "warning", true);
  if (access.phase === "resolved") {
    if (access.facts.kind === "uninitialized")
      return access.facts.setupAvailable
        ? describe("login.remote.setup")
        : describe("login.remote.unavailable", "error", true);
    if (access.facts.kind === "authenticated") return describe("login.remote.confirmed");
  }
  if (retryAfterSeconds > 0)
    return {
      ...describe("login.remote.rateLimitedFor", "error"),
      values: { count: retryAfterSeconds },
    };
  if (
    access.phase === "checking" ||
    access.phase === "authenticating" ||
    access.phase === "unknown"
  )
    return describe("login.remote.checking", "info", false, true);
  if (!("error" in login)) return null;
  if (login.error.status === CONSOLE_ERROR_STATUS.rate_limited)
    return describe("login.remote.rateLimited", "error");
  if (
    login.error.kind === AppErrorKind.UNAUTHORIZED ||
    login.error.kind === AppErrorKind.FORBIDDEN ||
    login.error.status === 401 ||
    login.error.status === 403
  )
    return describe("login.remote.invalid", "error");
  return describe("login.remote.failed", "error");
}
