import { AppError, AppErrorKind } from "@richie696/react-framework";
import type { z } from "zod";

/** Invalid local input never dispatches and never exposes Zod's issue/input tree, especially write-only credentials. */
export function parseConsoleInput<Value>(schema: z.ZodType<Value>, value: unknown): Value {
  const parsed = schema.safeParse(value);
  if (!parsed.success)
    throw new AppError(AppErrorKind.PROTOCOL, "Invalid Console input", {
      code: "console_request_invalid",
      status: 400,
    });
  return parsed.data;
}
