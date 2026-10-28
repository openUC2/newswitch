/**
 * The newswitch blok catalog: the standard components, plus the microscope's
 * own. A blok the backend declares with `module="newswitch"` is rendered
 * against it; `catalogManifest` publishes the microscope part to the backend
 * as the `newswitch` module, which the backend validates those bloks with.
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

export const newswitchBlokCatalog: BlokCatalog = createBlokCatalog(
  NEWSWITCH_CATALOG_NAME,
  [...defaultBlokCatalog.components.values(), ...newswitchBlokComponents],
  defaultBlokCatalog.functionDefinitions,
);
