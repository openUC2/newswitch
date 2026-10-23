import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  NEWSWITCH_CATALOG_NAME,
  NEWSWITCH_CATALOG_VERSION,
  newswitchBlokCatalog,
  newswitchBlokComponents,
} from "./catalog";
import { toUiCatalogComponent, toUiCatalogJson } from "./catalogManifest";

/** The backend validates the bloks of its configuration against this file, and nothing else. */
// Vitest runs from the frontend's root.
const BACKEND_CATALOG = resolve(
  process.cwd(),
  "../backend/newswitch/bloks/newswitch-catalog.json",
);

const manifest = () =>
  toUiCatalogJson(
    NEWSWITCH_CATALOG_NAME,
    NEWSWITCH_CATALOG_VERSION,
    "What the newswitch frontend renders: the standard components, the scene's and the microscope's.",
    newswitchBlokCatalog,
  );

const byName = <T extends { name: string }>(items: T[], name: string): T => {
  const found = items.find((item) => item.name === name);
  if (!found) throw new Error(`${name} is not in the catalog`);
  return found;
};
const byOperation = byName;

/** A catalog that differs from the committed one carries a higher version. */
const expectVersioned = () => {
  if (!existsSync(BACKEND_CATALOG)) return;
  const committed = JSON.parse(readFileSync(BACKEND_CATALOG, "utf8")) as {
    version?: number;
  };
  const { version: committedVersion = 0, ...before } = committed;
  const { version, ...after } = manifest();
  if (JSON.stringify(before) === JSON.stringify(after)) {
    expect(version, "the catalog is unchanged: keep its version").toBe(
      committedVersion,
    );
    return;
  }
  expect(
    version,
    `the catalog changed: bump NEWSWITCH_CATALOG_VERSION (catalog.tsx) past ${committedVersion}`,
  ).toBeGreaterThan(committedVersion);
};

describe("newswitch catalog manifest", () => {
  it("describes placement and prop kinds", () => {
    const byName = Object.fromEntries(
      manifest().components.map((component) => [component.name, component]),
    );

    expect(byName.StageScene).toMatchObject({
      acceptsChildren: true,
      context: "HTML",
      childrenContext: "SCENE",
      downstreamOf: ["StageView"],
    });
    expect(byName.FramesLayer).toMatchObject({
      context: "SCENE",
      acceptsChildren: false,
      downstreamOf: ["StageScene"],
    });
    expect(byName.SettingsPanel.props).toEqual([
      {
        key: "className",
        kind: "STRING",
        required: false,
        description: "Extra Tailwind classes appended to the element.",
      },
    ]);
    expect(
      toUiCatalogComponent(newswitchBlokComponents[0]).description,
    ).toBeTruthy();
  });

  it("is the whole catalog: standard components and every function", () => {
    const { components, operations } = manifest();
    const names = new Set(components.map((component) => component.name));
    for (const name of [
      "div",
      "span",
      "if",
      "foreach",
      "Button",
      "Model",
      "StageControl",
    ]) {
      expect(names).toContain(name);
    }
    expect(byOperation(operations, "compare.lt").returns).toBe("BOOL");
    expect(byName(components, "Model").props).toContainEqual(
      expect.objectContaining({ key: "src", kind: "ASSET" }),
    );
  });

  it("is versioned: a changed catalog gets a new version", () => {
    expectVersioned();
  });

  it("matches the catalog the backend validates against", () => {
    const current = `${JSON.stringify(manifest(), null, 2)}\n`;

    if (process.env.UPDATE_CATALOG) {
      expectVersioned();
      writeFileSync(BACKEND_CATALOG, current);
      return;
    }

    expect(
      existsSync(BACKEND_CATALOG),
      "run `yarn catalog:export` to write it",
    ).toBe(true);
    expect(
      readFileSync(BACKEND_CATALOG, "utf8"),
      "the backend's newswitch-catalog.json is out of date: run `yarn catalog:export`",
    ).toBe(current);
  });
});
