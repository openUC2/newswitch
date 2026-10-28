import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  NEWSWITCH_CATALOG_NAME,
  NEWSWITCH_CATALOG_VERSION,
  newswitchBlokCatalog,
  newswitchBlokComponents,
} from "./catalog";
import { toModuleJson, toUiCatalogComponent } from "./catalogManifest";

/** The backend declares this file as the `newswitch` module its bloks render against. */
// Vitest runs from the frontend's root.
const BACKEND_CATALOG = resolve(
  process.cwd(),
  "../backend/newswitch/bloks/newswitch-catalog.json",
);

const manifest = () =>
  toModuleJson(
    NEWSWITCH_CATALOG_NAME,
    NEWSWITCH_CATALOG_VERSION,
    "What the newswitch frontend draws beyond the spec's catalogs: the microscope's components, the stage's and their scene layers.",
    newswitchBlokCatalog,
  );

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

  it("is the module: only what the spec's catalogs do not hold", () => {
    const { components, operations } = manifest();
    const names = new Set(components.map((component) => component.name));
    expect(names).toContain("StageControl");
    expect(names).toContain("LiveView");
    for (const name of ["div", "if", "foreach", "Button", "Model"]) {
      expect(names).not.toContain(name);
    }
    expect(operations).toEqual([]);
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
