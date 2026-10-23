/**
 * The newswitch blok catalog: the standard components and functions, plus the
 * microscope's own. A blok the backend declares with `catalog="newswitch"` is
 * rendered against it; `catalogManifest` publishes the microscope part to the
 * backend, which validates those bloks against it.
 */
import {
  createBlokCatalog,
  type BlokCatalog,
  type BlokComponentDefinition,
} from "@/lib/blok/renderer/runtime";
import { defaultBlokCatalog } from "@/lib/blok/renderer/catalog";
import { microscopeBlokComponents } from "./microscope";
import { sceneBlokComponents } from "./scene";
import { stageBlokComponents } from "./stage";

export const NEWSWITCH_CATALOG_NAME = "newswitch";

/**
 * The catalog's version: a blok configuration names the catalog it was written
 * against as `newswitch@<version>`. Bump it whenever the exported catalog
 * changes (a component, prop or function added, removed or changed);
 * `yarn catalog:export` refuses a changed catalog under the same version.
 */
export const NEWSWITCH_CATALOG_VERSION = 1;

/** The components newswitch adds to the standard catalog. */
export const newswitchBlokComponents: BlokComponentDefinition[] = [
  ...microscopeBlokComponents,
  ...stageBlokComponents,
  ...sceneBlokComponents,
];

export const newswitchBlokCatalog: BlokCatalog = createBlokCatalog(
  NEWSWITCH_CATALOG_NAME,
  [...defaultBlokCatalog.components.values(), ...newswitchBlokComponents],
  defaultBlokCatalog.functionDefinitions,
);
