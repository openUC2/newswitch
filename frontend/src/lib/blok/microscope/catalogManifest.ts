/**
 * The microscope components as a UI catalog the backend reads: the
 * `blok-catalog.json` shape Orkestrator publishes its catalog in, which
 * `arkitekt_spec.declare.catalogs.parse_ui_catalog` parses. The backend checks
 * the bloks it declares with `catalog="newswitch"` against it.
 */
import type * as z from "zod";
import type {
  BlokComponentContext,
  BlokComponentDefinition,
} from "@/lib/blok/renderer/runtime";
import { isActionSchema } from "@/lib/blok/renderer/runtime/schemas";

export type UiCatalogProp = {
  key: string;
  kind: "STRING" | "FLOAT" | "BOOL" | "LIST" | "DICT" | "ANY" | "CALLBACK";
  required: boolean;
  description: string | null;
};

export type UiCatalogComponent = {
  name: string;
  description: string | null;
  acceptsChildren: boolean;
  context: string;
  childrenContext: string | null;
  inheritsContext: boolean;
  downstreamOf: string[];
  notDownstreamOf: string[];
  props: UiCatalogProp[];
};

export type UiCatalogJson = {
  name: string;
  description: string;
  components: UiCatalogComponent[];
  operations: never[];
};

type ZodDef = { type: string; innerType?: z.ZodType };
const defOf = (schema: z.ZodType) =>
  (schema as unknown as { _zod: { def: ZodDef } })._zod.def;

/** Optional, nullable and defaulted wrappers say nothing about the kind. */
const WRAPPERS = new Set(["optional", "nullable", "default", "readonly"]);

const unwrap = (schema: z.ZodType): z.ZodType => {
  let current = schema;
  while (WRAPPERS.has(defOf(current).type) && defOf(current).innerType) {
    current = defOf(current).innerType as z.ZodType;
  }
  return current;
};

const kindOf = (schema: z.ZodType): UiCatalogProp["kind"] => {
  if (isActionSchema(schema) || isActionSchema(unwrap(schema))) {
    return "CALLBACK";
  }
  switch (defOf(unwrap(schema)).type) {
    case "string":
    case "enum":
    case "literal":
      return "STRING";
    case "number":
    case "int":
      return "FLOAT";
    case "boolean":
      return "BOOL";
    case "array":
    case "tuple":
      return "LIST";
    case "object":
    case "record":
      return "DICT";
    default:
      return "ANY";
  }
};

const contextName = (context: BlokComponentContext | undefined) =>
  (context ?? "html").toUpperCase();

export const toUiCatalogComponent = (
  definition: BlokComponentDefinition,
): UiCatalogComponent => {
  const shape = definition.schema.shape as Record<string, z.ZodType>;
  const placement = definition.placement ?? {};
  const props = Object.entries(shape)
    .map(([key, schema]) => ({
      key,
      kind: kindOf(schema),
      required: !schema.safeParse(undefined).success,
      description: schema.description ?? null,
    }))
    .sort((a, b) => a.key.localeCompare(b.key));

  return {
    name: definition.name,
    description: definition.schema.description ?? null,
    acceptsChildren: Boolean(definition.acceptsChildren) || "children" in shape,
    context: contextName(placement.context),
    childrenContext: placement.childrenContext
      ? contextName(placement.childrenContext)
      : null,
    inheritsContext: Boolean(placement.inheritsContext),
    downstreamOf: [...(placement.downstreamOf ?? [])],
    notDownstreamOf: [...(placement.notDownstreamOf ?? [])],
    props,
  };
};

export const toUiCatalogJson = (
  name: string,
  description: string,
  components: readonly BlokComponentDefinition[],
): UiCatalogJson => ({
  name,
  description,
  components: components
    .map(toUiCatalogComponent)
    .sort((a, b) => a.name.localeCompare(b.name)),
  operations: [],
});
