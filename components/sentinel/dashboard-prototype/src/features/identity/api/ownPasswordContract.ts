import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import { OWN_PASSWORD_ENDPOINT } from "./ownPasswordHttp";
import { OwnPasswordInputSchema } from "./ownPasswordWire";

/** Own-password authorization is independent of admin/view. No privileged target selection. */
export const OWN_PASSWORD_HTTP_CONTRACT = Object.freeze([
  {
    operationId: "changeOwnPassword",
    summary: "修改当前账号的登录密码",
    tag: "own-password",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: OWN_PASSWORD_ENDPOINT,
    input: OwnPasswordInputSchema,
    pathParameters: [],
    semanticRules: [
      "Both admin/view may change only their own password; account comes from the current Cookie session.",
      "Requires current password, exact Origin and CSRF; confirmation and target account are forbidden input.",
      "Password strings must contain Unicode scalar values; a lone surrogate escape is rejected as `400 invalid_request` before password policy or hashing.",
      "An incorrect current password returns `current_password_invalid`; an absent/expired session remains `unauthenticated`.",
      "The current server atomically updates the password hash, revokes every account session, and returns only `reauthenticate`.",
      "Unverifiable response is not replayable; inspecting a session is not proof that the password mutation did or did not commit.",
      "No credentials appear in read facts, audit payloads or rejection diagnostics.",
    ],
    examples: [
      {
        name: "change_own_password_and_reauthenticate",
        summary: "当前账号使用旧密码设置新密码，服务端要求重新登录",
        kind: "positive",
        request: {
          body: {
            currentPassword: "synthetic-current-password-012345",
            newPassword: "synthetic-new-password-0123",
          },
        },
        response: { status: 200, body: { sessionDisposition: "reauthenticate" } },
      },
      {
        name: "change_own_password_rejects_wrong_current_password",
        summary: "旧密码不正确时拒绝变更且不会回显任何凭证",
        kind: "negative",
        request: {
          body: {
            currentPassword: "synthetic-incorrect-current-012345",
            newPassword: "synthetic-new-password-0123",
          },
        },
        response: {
          status: 400,
          body: { error: { code: "current_password_invalid", requestId: "password-rejected" } },
        },
      },
    ],
  },
] satisfies readonly ConsoleOperationContract[]);
