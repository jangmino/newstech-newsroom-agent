import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

beforeEach(() => {
  // Every request must be explicitly replaced with a mock response by the test.
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("Unmocked network request"); }));
  vi.spyOn(XMLHttpRequest.prototype, "send").mockImplementation(() => {
    throw new Error("Network requests are forbidden in UI tests");
  });
  // Node also exposes localStorage; exercise the jsdom browser storage consistently.
  vi.stubGlobal("localStorage", {
    length: 0, key: vi.fn(() => null), getItem: vi.fn(() => null),
    removeItem: vi.fn(), clear: vi.fn(),
    setItem: vi.fn(() => { throw new Error("Review state must not be persisted"); }),
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Review state must not be persisted");
  });
});

afterEach(cleanup);
