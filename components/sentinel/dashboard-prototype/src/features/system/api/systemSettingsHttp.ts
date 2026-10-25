import { AppError, AppErrorKind, defineUrl, HttpMethod } from "@richie696/react-framework";
import { z } from "zod";
import type {
  ConsoleEndpoint,
  ConsoleTransport,
} from "../../../core/api/transport/consoleEndpoint";
import { parseConsoleInput } from "../../../core/api/protocol/parseInput";
import type { SystemSettingsPort } from "./systemSettingsPort";

export const SystemSettingsSnapshotSchema = z.strictObject({
  timeZone: z.string().min(1).max(128),
  revision: z.number().int().positive(),
});
export const SystemSettingsUpdateSchema = z.strictObject({ timeZone: z.string().min(1).max(128) });
export const SYSTEM_SETTINGS_ENDPOINTS = Object.freeze({
  Read: {
    url: defineUrl("/api/v1/system/settings"),
    response: SystemSettingsSnapshotSchema,
    successStatus: 200,
    command: false,
    idempotency: "none",
    csrf: false,
    expireOnUnauthorized: true,
    errors: ["invalid_request", "unauthenticated", "service_unavailable"],
  } satisfies ConsoleEndpoint<z.infer<typeof SystemSettingsSnapshotSchema>>,
  Update: {
    url: defineUrl("/api/v1/system/settings", { method: HttpMethod.PUT }),
    response: SystemSettingsSnapshotSchema,
    successStatus: 200,
    command: true,
    idempotency: "none",
    csrf: true,
    expireOnUnauthorized: true,
    errors: [
      "invalid_request",
      "unauthenticated",
      "forbidden",
      "csrf_failed",
      "service_unavailable",
    ],
  } satisfies ConsoleEndpoint<z.infer<typeof SystemSettingsSnapshotSchema>>,
});

/** Typed HTTP adapter for the system settings protocol. */
export function createSystemSettingsHttp(transport: ConsoleTransport): SystemSettingsPort {
  return Object.freeze({
    async read(signal: AbortSignal) {
      return transport.send(SYSTEM_SETTINGS_ENDPOINTS.Read, { signal });
    },
    async updateTimeZone(timeZone: string, signal: AbortSignal) {
      const body = parseConsoleInput(SystemSettingsUpdateSchema, { timeZone });
      if (!body)
        throw new AppError(AppErrorKind.PROTOCOL, "Invalid timezone setting", {
          status: 400,
          code: "console_request_invalid",
        });
      return transport.send(SYSTEM_SETTINGS_ENDPOINTS.Update, { signal, body });
    },
  });
}
