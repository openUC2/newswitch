import { describe, expect, it } from "vitest";
import {
  detectBrowserLanguage,
  normalizeLanguage,
  resolveLanguage,
} from "./language";

describe("language selection", () => {
  it("normalizes supported regional browser languages", () => {
    expect(normalizeLanguage("de-DE")).toBe("de");
    expect(normalizeLanguage("en-US")).toBe("en");
    expect(normalizeLanguage("fr-FR")).toBeNull();
  });

  it("uses the first supported browser language and falls back to English", () => {
    expect(detectBrowserLanguage(["fr-FR", "de-AT", "en-US"])).toBe("de");
    expect(detectBrowserLanguage(["fr-FR", "it-IT"])).toBe("en");
  });

  it("keeps an explicit preference ahead of browser detection", () => {
    expect(resolveLanguage("de")).toBe("de");
    expect(resolveLanguage("en")).toBe("en");
  });
});
