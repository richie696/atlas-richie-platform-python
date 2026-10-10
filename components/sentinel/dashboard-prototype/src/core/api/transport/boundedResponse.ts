import { CONSOLE_WIRE_LIMIT } from "../protocol/common";

/** Limit decoded response bytes before the foundation parser allocates a JSON object. No retry or error-body logging. */
export async function boundedResponse(response: Response, signal: AbortSignal): Promise<Response> {
  if (response.status === 204) {
    await ensureBodyIsEmpty(response.body, signal);
    return response;
  }
  if (
    !/^application\/json\s*(?:;\s*charset\s*=\s*"?utf-8"?\s*)?$/i.test(
      response.headers.get("content-type") ?? "",
    )
  )
    throw new Error("Unexpected Console content type");
  const length = response.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > CONSOLE_WIRE_LIMIT.BodyBytes))
    throw new Error("Console body limit exceeded");
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Missing Console body");
  const parts: Uint8Array[] = [];
  let size = 0;
  const abort = () => {
    void reader.cancel().catch(() => {});
  };
  signal.addEventListener("abort", abort, { once: true });
  try {
    signal.throwIfAborted();
    while (true) {
      const chunk = await reader.read();
      signal.throwIfAborted();
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > CONSOLE_WIRE_LIMIT.BodyBytes) throw new Error("Console body limit exceeded");
      parts.push(chunk.value);
    }
    const body = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) {
      body.set(part, offset);
      offset += part.byteLength;
    }
    // Fetch text() replaces malformed bytes; a rule identity/credential must never be silently repaired.
    new TextDecoder("utf-8", { fatal: true }).decode(body);
    // Foundation owns the only JSON parser. This bridge adds bounded ingress through its public fetch slot.
    return new Response(body, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  } catch (error) {
    void reader.cancel().catch(() => {});
    throw error;
  } finally {
    signal.removeEventListener("abort", abort);
    reader.releaseLock();
  }
}

/** Some Fetch interceptors represent an empty 204 as a closed, zero-byte stream. */
async function ensureBodyIsEmpty(body: ReadableStream<Uint8Array> | null, signal: AbortSignal) {
  if (body === null) return;
  const reader = body.getReader();
  const abort = () => {
    void reader.cancel().catch(() => {});
  };
  signal.addEventListener("abort", abort, { once: true });
  try {
    signal.throwIfAborted();
    while (true) {
      const chunk = await reader.read();
      signal.throwIfAborted();
      if (chunk.done) return;
      if (chunk.value.byteLength > 0) throw new Error("Unexpected empty-response body");
    }
  } catch (error) {
    void reader.cancel().catch(() => {});
    throw error;
  } finally {
    signal.removeEventListener("abort", abort);
    reader.releaseLock();
  }
}

/** Parsed input remains bounded by depth as well as bytes; reject rather than dropping nested fields. */
export function withinJsonDepth(value: unknown, maximum = CONSOLE_WIRE_LIMIT.JsonDepth): boolean {
  const pending = [{ value, depth: 0 }];
  while (pending.length) {
    const item = pending.pop();
    if (!item) break;
    if (item.depth > maximum) return false;
    if (item.value !== null && typeof item.value === "object") {
      for (const child of Object.values(item.value))
        pending.push({ value: child, depth: item.depth + 1 });
    }
  }
  return true;
}
