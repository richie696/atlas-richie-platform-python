import assert from "node:assert/strict";
import { test } from "node:test";
import { randomUuid } from "../../src/core/crypto/randomUuid";

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** Run with a crypto surface that lacks the secure-context-only native method. */
function withoutNativeRandomUuid(run) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "crypto");
  const native = globalThis.crypto;
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value: { getRandomValues: (array) => native.getRandomValues(array) },
  });
  try {
    run();
  } finally {
    if (previous) Object.defineProperty(globalThis, "crypto", previous);
    else delete globalThis.crypto;
  }
}

test("random identifiers keep the native v4 shape in secure contexts", () => {
  const value = randomUuid();
  assert.match(value, UUID_V4);
  assert.equal(value.length, 36);
  assert.notEqual(value, randomUuid());
});

test("plain-HTTP origins still produce a v4 identifier without crypto.randomUUID", () => {
  withoutNativeRandomUuid(() => {
    const seen = new Set();
    for (let index = 0; index < 32; index += 1) {
      const value = randomUuid();
      assert.match(value, UUID_V4);
      assert.equal(value.length, 36);
      seen.add(value);
    }
    assert.equal(seen.size, 32);
  });
});
