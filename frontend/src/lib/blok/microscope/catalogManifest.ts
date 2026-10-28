/**
 * The newswitch module as the backend reads it (blok language v2): the
 * `blok-catalog.json` shape, which `arkitekt_spec.declare.catalogs.parse_ui_catalog`
 * parses, and the backend declares with `app.ui_catalog("newswitch", ...)`.
 *
 * A v2 blok is drawn with base, the standard catalogs (`ui@1`, `scene@1`, ...)
 * and the Orkestrator's module, which the spec ships, plus one module of the
 * app's own. This is that module: the components this frontend draws that none
 * of those hold (the microscope's, the stage's). Functions are the vocabulary's,
 * so it adds no operations.
 */
import type * as z from "zod";
import type {
  BlokCatalog,
  BlokComponentContext,
  BlokComponentDefinition,
} from "@arkitektio/bsx/renderer/runtime/index";
import { baseCatalog, standardCatalogs } from "@arkitektio/bsx/spec/catalogs";
import { isActionSchema } from "@arkitektio/bsx/renderer/runtime/schemas";

type ValueKind =
  | "STRING"
  | "INT"
  | "FLOAT"
  | "BOOL"
  | "LIST"
  | "DICT"
  | "ANY"
  | "CALLBACK"
  | "ASSET";

export type UiCatalogField = {
  key: string;
  kind: ValueKind;
  required: boolean;
  description: string | null;
  /** For a `STRING` prop, the closed set of literals it takes. */
  values?: string[];
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
  props: UiCatalogField[];
};

export type UiCatalogOperation = {
  name: string;
  description: string;
  arguments: UiCatalogField[];
  returns: ValueKind;
};

export type UiCatalogJson = {
  name: string;
  /** Bumped on every change; bloks name the catalog as `<name>@<version>`. */
  version: number;
  description: string;
  components: UiCatalogComponent[];
  operations: UiCatalogOperation[];
};

type ZodDef = {
  type: string;
  format?: string;
  innerType?: z.ZodType;
  in?: z.ZodType;
  options?: z.ZodType[];
  values?: unknown[];
  entries?: Record<string, unknown>;
  shape?: Record<string, z.ZodType>;
};
const defOf = (schema: z.ZodType) =>
  (schema as unknown as { _zod: { def: ZodDef } })._zod.def;

/** Optional, nullable and defaulted wrappers and transforms say nothing about the kind. */
const WRAPPERS = new Set(["optional", "nullable", "default", "readonly"]);
const INT_FORMATS = new Set(["safeint", "int32", "uint32", "int64", "uint64"]);

const unwrap = (schema: z.ZodType): z.ZodType => {
  let current = schema;
  for (let depth = 0; depth < 16; depth += 1) {
    const def = defOf(current);
    if (WRAPPERS.has(def.type) && def.innerType) current = def.innerType;
    else if (def.type === "pipe" && def.in) current = def.in;
    else return current;
  }
  return current;
};

/** The closed set of strings a `z.enum` prop takes, through its wrappers; null for any other schema. */
export const zodEnumValues = (schema: z.ZodType): string[] | null => {
  const def = defOf(unwrap(schema));
  if (def.type !== "enum" || !def.entries) return null;
  const values = Object.values(def.entries);
  return values.every((value): value is string => typeof value === "string")
    ? values
    : null;
};

/** The catalog kind of a zod schema; unknown shapes are `ANY`. */
export const zodToCatalogKind = (schema: z.ZodType): ValueKind => {
  if (isActionSchema(schema) || isActionSchema(unwrap(schema))) {
    return "CALLBACK";
  }
  const def = defOf(unwrap(schema));
  switch (def.type) {
    case "string":
    case "enum":
    case "template_literal":
      return "STRING";
    case "literal": {
      const values = def.values ?? [];
      if (values.every((value) => typeof value === "string")) return "STRING";
      if (values.every((value) => typeof value === "boolean")) return "BOOL";
      if (values.every((value) => typeof value === "number")) return "FLOAT";
      return "ANY";
    }
    case "number":
      return def.format && INT_FORMATS.has(def.format) ? "INT" : "FLOAT";
    case "int":
      return "INT";
    case "boolean":
      return "BOOL";
    case "array":
    case "tuple":
    case "set":
      return "LIST";
    case "object":
    case "record":
    case "map":
      return "DICT";
    case "union": {
      const kinds = new Set((def.options ?? []).map(zodToCatalogKind));
      return kinds.size === 1 ? [...kinds][0] : "ANY";
    }
    default:
      return "ANY";
  }
};

const field = (key: string, schema: z.ZodType): UiCatalogField => {
  const values = zodEnumValues(schema);
  return {
    key,
    kind: zodToCatalogKind(schema),
    required: !schema.safeParse(undefined).success,
    description: schema.description ?? null,
    ...(values ? { values } : {}),
  };
};

const byKey = <T extends { key: string }>(items: T[]): T[] =>
  [...items].sort((a, b) => a.key.localeCompare(b.key));

const shapeOf = (schema: z.ZodType): Record<string, z.ZodType> =>
  defOf(schema).type === "object"
    ? ((schema as unknown as { shape: Record<string, z.ZodType> }).shape ?? {})
    : {};

const contextName = (context: BlokComponentContext | undefined) =>
  (context ?? "html").toUpperCase();

export const toUiCatalogComponent = (
  definition: BlokComponentDefinition,
): UiCatalogComponent => {
  const shape = shapeOf(definition.schema);
  const placement = definition.placement ?? {};
  const props = Object.entries(shape).map(([key, schema]) => {
    const kind = definition.propKinds?.[key];
    return kind ? { ...field(key, schema), kind } : field(key, schema);
  });

  return {
    name: definition.name,
    description: definition.schema.description ?? null,
    acceptsChildren: Boolean(definition.acceptsChildren) || "children" in shape,
    context: contextName(placement.context),
    childrenContext: placement.childrenContext
      ? contextName(placement.childrenContext)
      : null,
    inheritsContext: Boolean(placement.inheritsContext),
    downstreamOf: [...(placement.downstreamOf ?? [])].sort(),
    notDownstreamOf: [...(placement.notDownstreamOf ?? [])].sort(),
    props: byKey(props),
  };
};

/**
 * The module: every component of `catalog` that base and the global catalogs
 * (shadcn@1 among them) do not hold, by name.
 */
export const toModuleJson = (
  name: string,
  version: number,
  description: string,
  catalog: BlokCatalog,
): UiCatalogJson => {
  const provided = new Set(
    [baseCatalog(), ...standardCatalogs()].flatMap((source) =>
      source.components.map((component) => component.name),
    ),
  );
  return {
    name,
    version,
    description,
    components: [...catalog.components.values()]
      .filter((definition) => !provided.has(definition.name))
      .map(toUiCatalogComponent)
      .sort((a, b) => a.name.localeCompare(b.name)),
    operations: [],
  };
};
