/**
 * The newswitch blok catalog as the backend reads it: the `blok-catalog.json`
 * shape Orkestrator publishes its catalog in, which
 * `arkitekt_spec.declare.catalogs.parse_ui_catalog` parses.
 *
 * It is the whole catalog this frontend renders and evaluates: the standard
 * components, the scene's, the microscope's, and every function as an
 * operation. The backend imports nothing else: it checks the bloks of its
 * device configuration (`ui:`) against exactly this, so a blok that validates
 * there is one this frontend can draw.
 */
import type * as z from "zod";
import type {
  BlokCatalog,
  BlokComponentContext,
  BlokComponentDefinition,
  BlokFunctionDefinition,
  BlokFunctionReturnType,
} from "@/lib/blok/renderer/runtime";
import { isActionSchema } from "@/lib/blok/renderer/runtime/schemas";

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

const kindOf = (schema: z.ZodType): ValueKind => {
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
      const kinds = new Set((def.options ?? []).map(kindOf));
      return kinds.size === 1 ? [...kinds][0] : "ANY";
    }
    default:
      return "ANY";
  }
};

const field = (key: string, schema: z.ZodType): UiCatalogField => ({
  key,
  kind: kindOf(schema),
  required: !schema.safeParse(undefined).success,
  description: schema.description ?? null,
});

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

const RETURNS: Record<BlokFunctionReturnType, ValueKind> = {
  string: "STRING",
  number: "FLOAT",
  boolean: "BOOL",
  list: "LIST",
  object: "DICT",
  unknown: "ANY",
  void: "ANY",
};

const operationArguments = (fn: BlokFunctionDefinition): UiCatalogField[] =>
  fn.variadic
    ? [
        {
          key: "values",
          kind: "LIST",
          required: false,
          description:
            "Positional values; bare numeric argument keys (0, 1, …) are accepted as well.",
        },
      ]
    : byKey(
        Object.entries(shapeOf(fn.schema)).map(([key, schema]) =>
          field(key, schema),
        ),
      );

const operationDescription = (fn: BlokFunctionDefinition, alias?: string) => {
  const parts = [
    alias ? `Alias of ${fn.name}. ${fn.description}` : fn.description,
  ];
  if (fn.deprecated) parts.push(`Deprecated: ${fn.deprecated}`);
  if (fn.purity === "effect")
    parts.push("Has side effects; only valid in action position.");
  return parts.join(" ");
};

/** A function as an operation, and once more under each of its aliases. */
export const toUiCatalogOperations = (
  fn: BlokFunctionDefinition,
): UiCatalogOperation[] => {
  const base = {
    arguments: operationArguments(fn),
    returns: RETURNS[fn.returnType],
  };
  return [
    { name: fn.name, description: operationDescription(fn), ...base },
    ...fn.aliases.map((alias) => ({
      name: alias,
      description: operationDescription(fn, alias),
      ...base,
    })),
  ];
};

/** The whole catalog: every component it draws, every function it evaluates. */
export const toUiCatalogJson = (
  name: string,
  version: number,
  description: string,
  catalog: BlokCatalog,
): UiCatalogJson => ({
  name,
  version,
  description,
  components: [...catalog.components.values()]
    .map(toUiCatalogComponent)
    .sort((a, b) => a.name.localeCompare(b.name)),
  operations: catalog.functionDefinitions
    .flatMap(toUiCatalogOperations)
    .sort((a, b) => a.name.localeCompare(b.name)),
});
