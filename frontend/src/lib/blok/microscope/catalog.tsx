/**
 * The newswitch blok catalog: the standard components, plus the microscope's
 * own. A blok the backend declares with `module="newswitch"` is rendered
 * against it; `catalogManifest` publishes the microscope part to the backend
 * as the `newswitch` module, which the backend validates those bloks with.
 */
import { threeScene } from "@arkitektio/bsx/scene";
import {
  shadcnExtras,
  shadcnHtml,
  shadcnLogo,
  shadcnUi,
} from "@arkitektio/bsx/shadcn";
import {
  declareBlokUi,
  ownBlokCatalog,
  type BlokCatalog,
  type BlokComponentDefinition,
} from "@arkitektio/bsx/runtime";
import { microscopeBlokComponents } from "./microscope";
import { sceneBlokComponents } from "./scene";
import { stageBlokComponents } from "./stage";

export const NEWSWITCH_CATALOG_NAME = "newswitch";

/**
 * The module's version: a blok configuration names the one it was written
 * against as `newswitch@<version>`. Bump it whenever the exported module
 * changes (a component or prop added, removed or changed);
 * `yarn catalog:export` refuses a changed module under the same version.
 */
export const NEWSWITCH_CATALOG_VERSION = 2;

/** The components newswitch adds to the standard catalog. */
export const newswitchBlokComponents: BlokComponentDefinition[] = [
  ...microscopeBlokComponents,
  ...stageBlokComponents,
  ...sceneBlokComponents,
];

/** The microscope's own catalog, `newswitch@<version>`: its contract and its implementation, both newswitch's. */
export const newswitchMicroscope = ownBlokCatalog(
  {
    name: NEWSWITCH_CATALOG_NAME,
    version: NEWSWITCH_CATALOG_VERSION,
    description:
      "The newswitch microscope: its stage, its scene and its controls.",
  },
  newswitchBlokComponents,
);

/** newswitch's UI with the microscope: the global catalogs and its own. */
export const newswitchBlokUi = declareBlokUi({
  name: NEWSWITCH_CATALOG_NAME,
  implements: [
    shadcnUi,
    shadcnHtml,
    shadcnLogo,
    shadcnExtras,
    threeScene,
    newswitchMicroscope,
  ],
});

export const newswitchBlokCatalog: BlokCatalog = newswitchBlokUi.catalog;
