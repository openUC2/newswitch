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
