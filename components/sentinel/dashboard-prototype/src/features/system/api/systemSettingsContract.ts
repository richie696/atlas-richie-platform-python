import {
  CONSOLE_ACCESS,
  type ConsoleOperationContract,
} from "../../../core/api/protocol/operationContract";
import {
  SYSTEM_SETTINGS_ENDPOINTS,
  SystemSettingsSnapshotSchema,
  SystemSettingsUpdateSchema,
} from "./systemSettingsHttp";

/** Machine-readable contracts for durable system display settings. */
export const SYSTEM_SETTINGS_HTTP_CONTRACT: readonly ConsoleOperationContract[] = Object.freeze([
  {
    operationId: "readSystemSettings",
    summary: "Read the Console-wide display settings.",
    tag: "System settings",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.None,
    endpoint: SYSTEM_SETTINGS_ENDPOINTS.Read,
    input: null,
    pathParameters: [],
    semanticRules: ["The timeZone is an IANA identifier; all API timestamps remain UTC instants."],
    examples: [
      {
        name: "currentTimeZone",
        summary: "The persisted system time zone.",
        kind: "positive",
        request: {},
        response: { status: 200, body: { timeZone: "Asia/Shanghai", revision: 1 } },
      },
      {
        name: "settingsRequireSession",
        summary: "匿名会话不能读取控制台全局展示设置",
        kind: "negative",
        request: {},
        response: {
          status: 401,
          body: { error: { code: "unauthenticated", requestId: "settings-anonymous" } },
        },
      },
    ],
  },
  {
    operationId: "updateSystemTimeZone",
    summary: "Update the system-wide display time zone.",
    tag: "System settings",
    security: "session",
    requiredAccess: CONSOLE_ACCESS.Admin,
    endpoint: SYSTEM_SETTINGS_ENDPOINTS.Update,
    input: SystemSettingsUpdateSchema,
    pathParameters: [],
    semanticRules: [
      "Only administrators can update the setting; the server rejects identifiers that are not recognized by its IANA timezone database.",
      "Offsets are derived from the selected IANA zone and its daylight-saving rules; a numeric offset is never persisted as the timezone.",
    ],
    examples: [
      {
        name: "setShanghai",
        summary: "Save the Shanghai display time zone.",
        kind: "positive",
        request: { body: { timeZone: "Asia/Shanghai" } },
        response: { status: 200, body: { timeZone: "Asia/Shanghai", revision: 2 } },
      },
      {
        name: "nonAdminCannotChangeTimeZone",
        summary: "非管理员不能修改控制台全局展示时区",
        kind: "negative",
        request: { body: { timeZone: "Asia/Shanghai" } },
        response: {
          status: 403,
          body: { error: { code: "forbidden", requestId: "settings-denied" } },
        },
      },
    ],
  },
]);

export { SystemSettingsSnapshotSchema };
