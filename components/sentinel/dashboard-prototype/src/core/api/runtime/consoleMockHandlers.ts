import { http, HttpResponse } from "msw";
import { CONSOLE_ERROR_STATUS, CONSOLE_HEADER, RequestKeySchema } from "../protocol/common";

/** This terminal handler prevents an unimplemented Console operation from reaching a real API. */
export const unmatchedConsoleApiHandler = http.all(/\/api\/v1(?:\/.*)?$/, ({ request }) => {
  const requestId = request.headers.get(CONSOLE_HEADER.RequestId);
  const safeRequestId =
    requestId !== null && RequestKeySchema.safeParse(requestId).success
      ? requestId
      : "mock-unmatched-request";
  return HttpResponse.json(
    { error: { code: "dependency_unavailable", requestId: safeRequestId } },
    {
      status: CONSOLE_ERROR_STATUS.dependency_unavailable,
      headers: { [CONSOLE_HEADER.RequestId]: safeRequestId },
    },
  );
});

/** Feature mock handlers are appended before this fail-closed fallback as each page migrates. */
export const CONSOLE_MOCK_HANDLERS = Object.freeze([unmatchedConsoleApiHandler]);
