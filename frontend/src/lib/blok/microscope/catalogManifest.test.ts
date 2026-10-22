import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { NEWSWITCH_CATALOG_NAME, newswitchBlokComponents } from "./catalog";
import { toUiCatalogComponent, toUiCatalogJson } from "./catalogManifest";

/** The backend validates its bloks against this file (`newswitch/bloks/__init__.py`). */
// Vitest runs from the frontend's root.
const BACKEND_CATALOG = resolve(
  process.cwd(),
  "../backend/newswitch/bloks/newswitch-catalog.json",
);

const manifest = () =>
  toUiCatalogJson(
    NEWSWITCH_CATALOG_NAME,
    "The newswitch microscope components: control panels, the stage view and its scene layers.",
    newswitchBlokComponents,
  );

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

  it("matches the catalog the backend validates against", () => {
    const current = `${JSON.stringify(manifest(), null, 2)}\n`;

    if (process.env.UPDATE_CATALOG) {
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
