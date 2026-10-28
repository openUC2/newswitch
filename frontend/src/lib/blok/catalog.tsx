import { threeScene } from "@arkitektio/bsx/scene";
import {
  shadcnExtras,
  shadcnHtml,
  shadcnLogo,
  shadcnUi,
} from "@arkitektio/bsx/shadcn";
import { addBlokComponents as addToCatalog } from "@arkitektio/bsx/web";
import {
  declareBlokUi,
  type BlokCatalog,
  type BlokComponentDefinition,
} from "@arkitektio/bsx/runtime";

/**
 * newswitch's UI: the global catalogs it implements, all drawn with the
 * package's shadcn and three implementations. structure@1 it does not draw.
 * The microscope's own catalog (`newswitch@<version>`) is declared on top of
 * it (`microscope/catalog.tsx`).
 */
export const standardBlokUi = declareBlokUi({
  name: "newswitch",
  implements: [shadcnUi, shadcnHtml, shadcnLogo, shadcnExtras, threeScene],
});

export const defaultBlokCatalog: BlokCatalog = standardBlokUi.catalog;

/** Adds components to the catalog (`defaultBlokCatalog` unless given another); returns the undo. */
export const addBlokComponents = (
  components: readonly BlokComponentDefinition[],
  catalog: BlokCatalog = defaultBlokCatalog,
): (() => void) => addToCatalog(components, catalog);
