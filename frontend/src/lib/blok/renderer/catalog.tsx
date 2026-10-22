import { RawInspector } from "./bloks/inspector/Inspector";
import { logoBlokComponents } from "./bloks/logo";
import { sceneBlokComponents } from "./bloks/scene";
import { shadcnComposableComponents } from "./bloks";
import { standardBlokFunctions } from "./functions";
import {
  createBlokCatalog,
  type BlokCatalog,
  type BlokComponentDefinition,
} from "./runtime";

/**
 * The catalog a blok payload is validated and rendered against: which
 * components exist, which functions a `utilCall` may name.
 *
 * The backend does not enumerate either — `ComponentNode.component` and
 * `UtilCall.operation` are free-form strings — so this module is the authority,
 * and `describeBlokCatalog` turns it into the published manifest.
 */
export const defaultBlokCatalog: BlokCatalog = createBlokCatalog(
  "https://arkitekt.live/catalogs/v1.json",
  [
    ...shadcnComposableComponents,
    ...sceneBlokComponents,
    ...logoBlokComponents,
    RawInspector,
  ],
  standardBlokFunctions,
);

/**
 * Adds components a module brings (`ModuleBuiltins.bloks`) to the catalog, so
 * everything that reads `defaultBlokCatalog` (the renderer, the registrar, the
 * export) offers them. Called once, by the composition root that installs the
 * modules; core never imports a module.
 *
 * A name is one component: one the catalog already holds is refused, whoever
 * brought it. Returns the undo (a dev hot reload installs the modules again).
 */
export const addBlokComponents = (
  components: readonly BlokComponentDefinition[],
  catalog: BlokCatalog = defaultBlokCatalog,
): (() => void) => {
  const taken = components.filter((component) =>
    catalog.components.has(component.name),
  );
  if (taken.length > 0) {
    throw new Error(
      `Blok components already in the catalog: ${taken.map((component) => component.name).join(", ")}`,
    );
  }
  for (const component of components)
    catalog.components.set(component.name, component);
  return () => {
    for (const component of components) {
      if (catalog.components.get(component.name) === component)
        catalog.components.delete(component.name);
    }
  };
};
