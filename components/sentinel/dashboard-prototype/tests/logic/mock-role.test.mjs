import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MOCK_ROLE_STORAGE_KEY,
  readMockPrincipal,
  writeMockPrincipal,
} from "../../src/core/api/mock/mockRole";

function withWindow(localStorage, run) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: { localStorage } });
  try {
    run();
  } finally {
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else delete globalThis.window;
  }
}

test("mock identity never infers admin from absent, malformed, or inaccessible role storage", () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  try {
    delete globalThis.window;
    writeMockPrincipal(null);
    assert.equal(readMockPrincipal(), null);
    for (const stored of [null, "administrator", "", "anonymous"]) {
      withWindow({ getItem: () => stored }, () => assert.equal(readMockPrincipal(), null));
    }
    withWindow(
      { getItem: () => { throw new Error("storage unavailable"); } },
      () => assert.equal(readMockPrincipal(), null),
    );
    withWindow(
      { getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? "admin" : null) },
      () => assert.equal(readMockPrincipal(), "admin"),
    );
    withWindow(
      { getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? "view" : null) },
      () => assert.equal(readMockPrincipal(), "view"),
    );
  } finally {
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else delete globalThis.window;
  }
});

test("mock identity can retain an explicitly written role in memory when browser storage is unavailable", () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  try {
    delete globalThis.window;
    writeMockPrincipal(null);
    assert.equal(readMockPrincipal(), null);
    writeMockPrincipal("view");
    assert.equal(readMockPrincipal(), "view");
    writeMockPrincipal(null);
    assert.equal(readMockPrincipal(), null);
  } finally {
    writeMockPrincipal(null);
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else delete globalThis.window;
  }
});

test("mock identity keeps an explicit logout anonymous when stale browser storage cannot be cleared", () => {
  const staleStorage = {
    getItem: (key) => (key === MOCK_ROLE_STORAGE_KEY ? "admin" : null),
    setItem: () => undefined,
  };
  withWindow(staleStorage, () => {
    writeMockPrincipal(null);
    assert.equal(readMockPrincipal(), null);
  });
});
