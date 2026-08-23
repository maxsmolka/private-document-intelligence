import { describe, expect, it } from "vitest";
import { resolveSafeInternalRedirect } from "@/lib/auth/redirect";

describe("resolveSafeInternalRedirect", () => {
  it.each([
    ["overview", "/", "/"],
    ["documents", "/documents", "/documents"],
    ["search", "/search", "/search"],
    ["nested document", "/documents/6eb3d86a", "/documents/6eb3d86a"],
    ["query", "/documents?status=ready", "/documents?status=ready"],
    ["fragment", "/search#result", "/search#result"],
    ["query and fragment", "/search?q=invoice#result", "/search?q=invoice#result"],
    ["normalized internal path", "/documents/../search", "/search"],
  ])("allows the %s internal destination", (_label, candidate, expected) => {
    expect(resolveSafeInternalRedirect(candidate)).toBe(expected);
  });

  it.each([
    ["missing", null],
    ["empty", ""],
    ["protocol relative", "//evil.example"],
    ["HTTPS URL", "https://evil.example"],
    ["HTTP URL", "http://evil.example"],
    ["encoded absolute URL", "https:%2f%2fevil.example"],
    ["encoded protocol relative URL", "%2F%2Fevil.example"],
    ["double-encoded protocol relative URL", "%252F%252Fevil.example"],
    ["backslash relative", "\\\\evil.example"],
    ["mixed slash and backslash", "/\\evil.example"],
    ["encoded backslash relative", "%5C%5Cevil.example"],
    ["leading whitespace", " /documents"],
    ["trailing whitespace", "/documents "],
    ["control character", "/documents\n"],
    ["malformed URL-like value", "://evil.example"],
    ["JavaScript scheme", "javascript:alert(1)"],
    ["data scheme", "data:text/html,unsafe"],
  ])("rejects the %s destination", (_label, candidate) => {
    expect(resolveSafeInternalRedirect(candidate)).toBe("/");
  });

  it("rejects external destinations after URLSearchParams decoding", () => {
    const protocolRelative = new URLSearchParams("next=%2F%2Fevil.example").get("next");
    const absolute = new URLSearchParams("next=https%3A%2F%2Fevil.example").get("next");
    const mixedSlash = new URLSearchParams("next=%2F%5Cevil.example").get("next");

    expect(resolveSafeInternalRedirect(protocolRelative)).toBe("/");
    expect(resolveSafeInternalRedirect(absolute)).toBe("/");
    expect(resolveSafeInternalRedirect(mixedSlash)).toBe("/");
  });

  it("fails closed when the configured fallback is also unsafe", () => {
    expect(resolveSafeInternalRedirect("//evil.example", "https://fallback.example")).toBe("/");
  });
});
