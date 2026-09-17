import { describe, expect, it } from "vitest";
import { resources } from "./resources";

function translationKeys(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof child === "object" && child !== null
      ? translationKeys(child, path)
      : [path];
  });
}

describe("translation resources", () => {
  it("keeps English and German translation keys in sync", () => {
    const englishKeys = translationKeys(resources.en.translation).sort();
    const germanKeys = translationKeys(resources.de.translation).sort();

    expect(germanKeys).toEqual(englishKeys);
  });
});
