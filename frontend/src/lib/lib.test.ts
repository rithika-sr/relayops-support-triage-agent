import { describe, expect, it } from "vitest";
import { qs, safeNext } from "./api";
import { countdown, relative } from "./format";

describe("safeNext", () => {
  it("keeps same-area relative paths", () => {
    expect(safeNext("/app/inbox", "support")).toBe("/app/inbox");
    expect(safeNext("/portal/tickets/x", "customer")).toBe("/portal/tickets/x");
  });
  it("rejects offsite, protocol-relative, backslash, and cross-role targets", () => {
    expect(safeNext("https://evil.example", "support")).toBe("/app");
    expect(safeNext("//evil.example", "support")).toBe("/app");
    expect(safeNext("/\\evil.example", "admin")).toBe("/app");
    expect(safeNext("/app/settings", "customer")).toBe("/portal");
    expect(safeNext(null, "customer")).toBe("/portal");
  });
});

describe("format", () => {
  const now = Date.parse("2026-11-06T12:00:00Z");
  it("formats countdowns for due and breached targets", () => {
    expect(countdown("2026-11-06T14:30:00Z", now)).toBe("2h 30m left");
    expect(countdown("2026-11-06T11:45:00Z", now)).toBe("breached 15m ago");
    expect(countdown(null, now)).toBe("no target");
  });
  it("formats relative times", () => {
    expect(relative("2026-11-06T09:00:00Z", now)).toBe("3h ago");
    expect(relative("2026-11-08T12:00:00Z", now)).toBe("in 2d");
  });
  it("builds query strings without empty values", () => {
    expect(qs({ a: "1", b: "", c: undefined, d: 0 })).toBe("?a=1&d=0");
    expect(qs({})).toBe("");
  });
});
