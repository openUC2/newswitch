import fs from 'node:fs';
import path from 'node:path';
import prettier from 'prettier';
import type { Plugin } from 'vite';

const ROOT_DIR = path.resolve(__dirname, '..');
const SRC_DIR = path.resolve(__dirname, '../src');
const DEFAULT_APPS_DIR = path.resolve(SRC_DIR, 'apps');
const BLOK_PATH = path.resolve(ROOT_DIR, 'blok.json');
const PACKAGE_JSON_PATH = path.resolve(ROOT_DIR, 'package.json');

const DEFAULT_APP_KEY = 'default';
const DEFAULT_REKUEST_IMPORT_PATH = '@/lib/rekuest';

const SHARED_UTILS_CODE = `
import { z } from 'zod';

/**
 * Creates a schema that handles indexed union variants.
 *
 * On the wire a union value is a positional envelope: \`{ __use: <variant index>, __value: <variant> }\`.
 * The index is load-bearing - it is the only discriminator for variants that carry no \`__identifier\`
 * of their own (primitives, structures) - so it cannot be derived from the value alone on decode.
 *
 * Decode also accepts an already-unwrapped value, which makes it idempotent: patch values arrive in
 * wire form and get spliced into an already-decoded document, so a re-validated document is mixed.
 */
export function createIndexedUnion<T extends [z.ZodTypeAny, ...z.ZodTypeAny[]]>(schemas: T) {
  const flat = z.union(schemas);
  const wrapped = z.union(
    schemas.map((schema, index) =>
      z.object({ __use: z.literal(index), __value: schema }),
    ) as unknown as [z.ZodTypeAny, ...z.ZodTypeAny[]],
  );
  const wire = z.union([wrapped, flat]);

  type Decoded = z.input<typeof flat>;
  type Encoded = z.output<typeof wire>;

  return z.codec(wire, flat, {
    decode: (value) => {
      const envelope = value as { __use?: number; __value?: unknown };

      return (
        envelope && typeof envelope === 'object' && '__use' in envelope
          ? envelope.__value
          : value
      ) as Decoded;
    },
    encode: (value, payload) => {
      // First match wins, mirroring the predicate loop the backend shrinks unions with.
      const index = schemas.findIndex((schema) => schema.safeParse(value).success);

      if (index === -1) {
        payload.issues.push({
          code: 'invalid_union',
          errors: [],
          input: value,
          message: 'Value does not match any variant of the union',
        });

        return z.NEVER;
      }

      return { __use: index, __value: value } as Encoded;
    },
  });
}
`;

type ExportKind = 'value' | 'type';

type ExportEntry = {
  kind: ExportKind;
  name: string;
};

type ValidatorSchema = {
  function: string;
  dependencies: string;
  errorMessage: string;
};

type ChoiceInput = {
  key?: string;
  label?: string;
  value: unknown;
  description?: string;
};

type SchemaPort = {
  key?: string;
  kind: string;
  nullable: boolean;
  default?: unknown;
  children?: SchemaPort[];
  choices?: ChoiceInput[];
  identifier?: string;
  description?: string;
  validators?: ValidatorSchema[];
};

type Optimistic = {
  state: string;
  path: string;
  accessor: string;
};

type HookImplementation = {
  definition: {
    description: string;
    args?: SchemaPort[];
    returns?: SchemaPort[];
  };
  description?: string;
  locks?: string[];
  optimistics?: Optimistic[];
};

type HooksSchema = {
  implementations: Record<string, HookImplementation>;
};

type StateSchemaDefinition = {
  ports: SchemaPort[];
};

type StateSchemaImplementation = {
  definition: StateSchemaDefinition;
  interface: string;
};

type StatesSchema = {
  states: Record<string, StateSchemaImplementation>;
};

type LockSchemaDefinition = {
  key: string;
  description?: string;
};

type LocksSchema = {
  locks: Record<string, LockSchemaDefinition>;
};

type SchemaGeneratorContext = {
  subSchemas: Map<string, string>;
  symbolPrefix?: string;
};

type ActionModuleEntry = {
  fileName: string;
  exportName: string;
  definitionName: string;
};

type StateModuleEntry = {
  fileName: string;
  exportName: string;
  definitionName: string;
};

type LockModuleEntry = {
  fileName: string;
  exportName: string;
  definitionName: string;
};

export interface GenerateAppPluginOptions {
  key?: string;
  name?: string;
  hooksSchemaUrl?: string;
  statesSchemaUrl?: string;
  locksSchemaUrl?: string;
  hooksWhitelist?: string[];
  hooksBlacklist?: string[];
  statesWhitelist?: string[];
  statesBlacklist?: string[];
  locksWhitelist?: string[];
  locksBlacklist?: string[];
}

export interface GenerateAppsPluginOptions {
  apps: GenerateAppPluginOptions[];
  baseDir?: string;
  rekuestImportPath?: string;
}

interface NormalizedGenerateAppPluginOptions extends GenerateAppPluginOptions {
  key: string;
  name?: string;
  symbolPrefix?: string;
}

const toCamel = (value: string) =>
  value.replace(/_([a-z])/g, (match) => match[1].toUpperCase());

const toPascal = (value: string) => {
  const camel = toCamel(value)
    .replace(/(^\w|[-_\s](\w))/g, (_, first: string, next?: string) =>
      (next ?? first).toUpperCase(),
    )
    .replaceAll('-', '')
    .replaceAll('_', '')
    .replaceAll(' ', '');

  return camel.charAt(0).toUpperCase() + camel.slice(1);
};

const normalizeOptionalString = (value?: string) => {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
};

const withSymbolPrefix = (value: string, symbolPrefix?: string) =>
  symbolPrefix ? `${symbolPrefix}${value}` : value;

const ensureDir = (dirPath: string) => {
  fs.mkdirSync(dirPath, { recursive: true });
};

// Codepoint order, NOT localeCompare: locale/ICU differences would make the generated
// output machine-dependent, which is exactly what the CI drift check cannot tolerate.
const byCodepoint = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

const sortedEntries = <T>(record: Record<string, T>): [string, T][] =>
  Object.entries(record).sort(([a], [b]) => byCodepoint(a, b));

// Object key order follows the backend's JSON wire order, which is not stable across
// runs. Sort it away. Arrays are left alone - their order is semantic.
const sortKeysDeep = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map(sortKeysDeep);
  }

  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return Object.fromEntries(
      Object.keys(record)
        .sort(byCodepoint)
        .map((key) => [key, sortKeysDeep(record[key])]),
    );
  }

  return value;
};

// Rekuest derives these fields through Python sets, so their wire order changes with
// Python's per-process hash seed. Their order has no meaning; normalize it before the
// schema snapshot reaches blok.json so a fresh CI process cannot create false drift.
const sortSetLikeSchemaArrays = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map(sortSetLikeSchemaArrays);
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, child]) => {
        const normalized = sortSetLikeSchemaArrays(child);
        if (
          (key === 'locks' || key === 'manipulates') &&
          Array.isArray(normalized) &&
          normalized.every((entry) => typeof entry === 'string')
        ) {
          return [key, [...normalized].sort(byCodepoint)];
        }
        return [key, normalized];
      }),
    );
  }

  return value;
};

// Every write goes through here. Rewriting a byte-identical file would churn its mtime,
// which re-triggers Vite's watcher and makes `git status` dirty after a no-op codegen.
const writeIfChanged = (filePath: string, content: string) => {
  try {
    if (fs.readFileSync(filePath, 'utf-8') === content) {
      return false;
    }
  } catch {
    // File does not exist yet - fall through and write it.
  }

  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content);
  return true;
};

// Replaces the old rm -rf + rewrite: drop only files we did NOT emit this run, so a
// lock/state/action removed from the backend still disappears, but unchanged files keep
// their mtime.
const pruneDir = (dirPath: string, expectedFileNames: Set<string>) => {
  let entries: string[];

  try {
    entries = fs.readdirSync(dirPath);
  } catch {
    return;
  }

  for (const entry of entries) {
    if (!expectedFileNames.has(entry)) {
      fs.rmSync(path.join(dirPath, entry), { force: true, recursive: true });
    }
  }
};

// Single source of truth: read the repo's .prettierrc rather than hardcoding options here.
// prettier.format() does NOT resolve config from disk on its own, so a divergence between
// this and the repo config would make the formatter and the generator rewrite each other
// forever - and the CI drift check would never be clean.
let prettierOptions: Promise<prettier.Options> | null = null;

const getPrettierOptions = () => {
  // Resolve against a path INSIDE the generated tree: .prettierrc scopes the single-quote
  // style to src/apps/**, so resolving anywhere else would hand back the hand-written
  // defaults and rewrite every generated file.
  prettierOptions ??= prettier
    .resolveConfig(path.resolve(DEFAULT_APPS_DIR, 'index.ts'))
    .then((resolved) => ({
      ...(resolved ?? { singleQuote: true, trailingComma: 'all' as const }),
      parser: 'typescript' as const,
    }));

  return prettierOptions;
};

const formatTypeScript = async (content: string) =>
  prettier.format(content, {
    ...(await getPrettierOptions()),
    // `filepath` is load-bearing, not cosmetic: with only `parser: 'typescript'` prettier
    // assumes the source might be .tsx and guards the ambiguity by emitting `<T,>` in
    // generic arrow functions. The prettier CLI, which knows the file is .ts, emits `<T>`.
    // Without this the generator and `prettier --check` disagree forever.
    filepath: 'generated.ts',
  });

const formatAndWrite = async (filePath: string, content: string) => {
  const formatted = await formatTypeScript(content);
  writeIfChanged(filePath, formatted);
};

const formatAndWriteJson = (filePath: string, value: unknown) => {
  writeIfChanged(filePath, `${JSON.stringify(value, null, 2)}\n`);
};

const readJsonFile = (filePath: string) => {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf-8')) as Record<
      string,
      unknown
    >;
  } catch {
    return null;
  }
};

const fetchSchemaJson = async (schemaUrl?: string, label?: string) => {
  if (!schemaUrl) {
    return null;
  }

  try {
    const response = await fetch(schemaUrl);

    if (!response.ok) {
      console.warn(
        `⚠️ [GenApps] Failed to fetch ${label ?? 'schema'} from ${schemaUrl}: ${response.status}`,
      );
      return null;
    }

    return (await response.json()) as Record<string, unknown>;
  } catch (error) {
    console.warn(
      `⚠️ [GenApps] Error fetching ${label ?? 'schema'} from ${schemaUrl}:`,
      error,
    );
    return null;
  }
};

const normalizeApps = (
  apps: GenerateAppPluginOptions[],
): NormalizedGenerateAppPluginOptions[] => {
  const normalizedApps = apps.map((app, index) => {
    const explicitKey = normalizeOptionalString(app.key);
    const legacyName = normalizeOptionalString(app.name);
    const key = explicitKey ?? legacyName;

    if (!key) {
      throw new Error(
        `App at index ${index} must define a "key" or a legacy "name".`,
      );
    }

    const normalizedName = explicitKey ? legacyName : undefined;
    const symbolPrefix =
      key === DEFAULT_APP_KEY
        ? undefined
        : normalizeOptionalString(toPascal(key));

    return {
      ...app,
      key,
      name: normalizedName,
      symbolPrefix,
    };
  });

  const seenKeys = new Map<string, string>();
  const seenNames = new Map<string, string>();
  const seenPrefixes = new Map<string, string>();

  for (const app of normalizedApps) {
    if (seenKeys.has(app.key)) {
      throw new Error(
        `Duplicate app key "${app.key}" found for apps "${seenKeys.get(app.key)}" and "${app.key}".`,
      );
    }
    seenKeys.set(app.key, app.key);

    if (app.name) {
      if (seenNames.has(app.name)) {
        throw new Error(
          `Duplicate app name "${app.name}" found for app keys "${seenNames.get(app.name)}" and "${app.key}".`,
        );
      }
      seenNames.set(app.name, app.key);
    }

    if (app.symbolPrefix) {
      if (seenPrefixes.has(app.symbolPrefix)) {
        throw new Error(
          `Duplicate app prefix "${app.symbolPrefix}" generated from app keys for app keys "${seenPrefixes.get(app.symbolPrefix)}" and "${app.key}".`,
        );
      }
      seenPrefixes.set(app.symbolPrefix, app.key);
    }
  }

  return normalizedApps;
};

const shouldGenerate = (
  key: string,
  whitelist?: string[],
  blacklist?: string[],
) => {
  const isAllowed = whitelist ? whitelist.includes(key) : true;
  const isBlocked = blacklist ? blacklist.includes(key) : false;
  return isAllowed && !isBlocked;
};

const renderDescription = (description?: string) => {
  if (!description) {
    return '';
  }

  return `/** ${description} */\n`;
};

const appendValidators = (baseSchemaCode: string, fields: SchemaPort[]) => {
  const fieldsWithValidators = fields.filter(
    (field) => field.validators && field.validators.length > 0 && field.key,
  );

  if (fieldsWithValidators.length === 0) {
    return baseSchemaCode;
  }

  const refinements = fieldsWithValidators
    .map((field) => {
      const fieldName = field.key as string;

      return field.validators
        ?.map((validator) => {
          const dependencies = validator.dependencies
            ? validator.dependencies
                .split(',')
                .map((entry) => entry.trim())
                .filter(Boolean)
            : [];

          const contextProperties = [
            `self: val['${fieldName}']`,
            ...dependencies.map(
              (dependency) => `${dependency}: val['${dependency}']`,
            ),
          ].join(', ');

          return `
        {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          type ValidatorFunc = (context: any) => boolean;
          const validatorFn: ValidatorFunc = ${validator.function};
          const context = { ${contextProperties} };

          if (!validatorFn(context)) {
            ctx.addIssue({
              code: 'custom',
              message: ${JSON.stringify(validator.errorMessage || 'Validation failed')},
              path: ['${fieldName}'],
            });
          }
        }`;
        })
        .join('\n');
    })
    .join('\n');

  return `${baseSchemaCode}.superRefine((val, ctx) => {
    ${refinements}
  })`;
};

const getExportEntries = (code: string): ExportEntry[] => {
  const exportEntries = new Map<string, ExportEntry>();

  for (const match of code.matchAll(
    /export\s+(const|type|function)\s+(\w+)/g,
  )) {
    const [, rawKind, name] = match;
    exportEntries.set(name, {
      name,
      kind: rawKind === 'type' ? 'type' : 'value',
    });
  }

  return Array.from(exportEntries.values());
};

const buildBarrelExports = (fileExports: Map<string, ExportEntry[]>) => {
  const exportCounts = new Map<string, number>();

  for (const exportEntries of fileExports.values()) {
    for (const { name } of exportEntries) {
      exportCounts.set(name, (exportCounts.get(name) ?? 0) + 1);
    }
  }

  return Array.from(fileExports.entries())
    .map(([fileName, exportEntries]) => {
      const uniqueExportEntries = exportEntries.filter(
        ({ name }) => exportCounts.get(name) === 1,
      );

      if (uniqueExportEntries.length === 0) {
        return null;
      }

      const valueExports = uniqueExportEntries
        .filter(({ kind }) => kind === 'value')
        .map(({ name }) => name);
      const typeExports = uniqueExportEntries
        .filter(({ kind }) => kind === 'type')
        .map(({ name }) => name);

      return [
        valueExports.length > 0
          ? `export { ${valueExports.join(', ')} } from './${fileName}';`
          : null,
        typeExports.length > 0
          ? `export type { ${typeExports.join(', ')} } from './${fileName}';`
          : null,
      ]
        .filter((line): line is string => line !== null)
        .join('\n');
    })
    .filter((line): line is string => line !== null)
    .join('\n');
};

const toObjectPropertyKey = (key: string) =>
  /^[A-Za-z_$][\w$]*$/u.test(key) ? key : JSON.stringify(key);

const mapChoicesToZodEnum = (choices: ChoiceInput[]) => {
  const values = choices.map((choice) => {
    const literalValue = choice.value ?? choice.key ?? choice.label;
    return `z.literal(${JSON.stringify(literalValue)}).describe(${JSON.stringify(choice.description || String(literalValue))})`;
  });

  return `z.union([${values.join(', ')}])`;
};

const buildObjectSchemaCode = (
  fields: SchemaPort[],
  context: SchemaGeneratorContext,
  injectedFields: string[] = [],
) => {
  const mappedFields = fields.map((field) => {
    const propertyKey = toObjectPropertyKey(field.key ?? 'value');
    return `${renderDescription(field.description)}${propertyKey}: ${mapPortToZod(field, context, field.key ?? 'Value')}`;
  });

  const objectFields = [...injectedFields, ...mappedFields].join(',\n');
  const objectCode = `z.object({\n${objectFields}\n})`;

  return appendValidators(objectCode, fields);
};

function mapPortToZod(
  port: SchemaPort,
  context: SchemaGeneratorContext,
  fallbackName = 'Unknown',
): string {
  let base = 'z.any()';
  const isValidKey = !!port.key && port.key !== '...' && port.key !== '';
  const nodeName =
    port.identifier || (isValidKey ? (port.key as string) : fallbackName);

  switch (port.kind) {
    case 'FLOAT':
    case 'INT':
      base = 'z.number()';
      break;
    case 'BOOL':
      base = 'z.boolean()';
      break;
    case 'STRING':
      if (port.choices && port.choices.length > 0) {
        const enumChoices = port.choices.map((choice) => ({
          ...choice,
          value: choice.key ?? choice.value,
        }));
        base = mapChoicesToZodEnum(enumChoices);
      } else {
        base = 'z.string()';
      }
      break;
    case 'ENUM':
      if (port.choices && port.choices.length > 0) {
        const enumChoices = port.choices.map((choice) => ({
          ...choice,
          value: choice.key ?? choice.value,
        }));
        base = mapChoicesToZodEnum(enumChoices);
      } else if (port.identifier) {
        base = `z.string().brand('${port.identifier}').meta({ brand: '${port.identifier}' })`;
      } else {
        base = 'z.string()';
      }
      break;
    case 'STRUCTURE':
      base = `z.object({__identifier: z.literal('${port.identifier}').default('${port.identifier}'), object: z.string()}).brand('${port.identifier}').meta({ brand: '${port.identifier}' })`;
      break;
    case 'SCALAR':
      base = 'z.string()';
      break;
    case 'MEMORY_STRUCTURE':
      base = `z.object({__identifier: z.literal('${port.identifier}').default('${port.identifier}'), object: z.string()}).brand('${port.identifier}').meta({ brand: '${port.identifier}' })`;
      break;
    case 'LIST': {
      if (port.children && port.children.length > 0) {
        const childFallback = nodeName.endsWith('s')
          ? nodeName.slice(0, -1)
          : `${nodeName}Item`;
        const elementType = mapPortToZod(
          port.children[0],
          context,
          childFallback,
        );
        base = `z.array(${elementType})`;
      } else {
        base = 'z.array(z.any())';
      }
      break;
    }
    case 'DICT': {
      if (port.children && port.children.length > 0) {
        const childFallback = `${nodeName}Value`;
        const valueType = mapPortToZod(
          port.children[0],
          context,
          childFallback,
        );
        base = `z.record(z.string(), ${valueType})`;
      } else {
        base = 'z.record(z.string(), z.any())';
      }
      break;
    }
    case 'MODEL': {
      const brandName = port.identifier || nodeName;
      const rawModelName = port.identifier
        ? `${toPascal(port.identifier)}Schema`
        : `${toPascal(nodeName)}ModelSchema`;
      const modelName = withSymbolPrefix(rawModelName, context.symbolPrefix);

      if (!context.subSchemas.has(modelName)) {
        const children = port.children ?? [];
        const injectedBrand = `  __identifier: z.literal('${brandName}').default('${brandName}')`;
        const schemaCode = buildObjectSchemaCode(children, context, [
          injectedBrand,
        ]);
        const brandedSchemaCode = port.identifier
          ? `${schemaCode}.brand('${port.identifier}')`
          : schemaCode;
        const describedSchemaCode = port.description
          ? `${brandedSchemaCode}.describe(${JSON.stringify(port.description)})`
          : brandedSchemaCode;

        // Emit type aliases alongside the schema; without them, consumers importing the
        // nested model type (Illumination, Position, Stack, ...) from the barrel get nothing.
        //
        // The bare name is the INPUT type on purpose. These schemas are branded, so the
        // output type carries a $brand marker and a required __identifier that you can only
        // obtain by parsing - a hand-built object literal can never satisfy it. Consumers
        // construct these values (acquisition payloads, form defaults), so they need the
        // pre-parse shape. The parsed/output type is exposed as `<Name>Output`.
        const modelTypeName = modelName.replace(/Schema$/, '');

        context.subSchemas.set(
          modelName,
          `export const ${modelName} = ${describedSchemaCode};
export type ${modelTypeName} = z.input<typeof ${modelName}>;
export type ${modelTypeName}Output = z.infer<typeof ${modelName}>;${
            context.symbolPrefix
              ? `\nexport const ${rawModelName} = ${modelName};`
              : ''
          }`,
        );
      }

      base = modelName;
      break;
    }
    case 'UNION': {
      const rawUnionName = port.identifier
        ? `${toPascal(port.identifier)}UnionSchema`
        : `${toPascal(nodeName)}UnionSchema`;
      const unionName = withSymbolPrefix(rawUnionName, context.symbolPrefix);

      if (!context.subSchemas.has(unionName)) {
        if (port.children && port.children.length > 0) {
          const types = port.children.map((child, index) =>
            mapPortToZod(child, context, `${nodeName}Variant${index + 1}`),
          );

          context.subSchemas.set(
            unionName,
            `export const ${unionName} = createIndexedUnion([\n  ${types.join(',\n  ')}\n]);${
              context.symbolPrefix
                ? `\nexport const ${rawUnionName} = ${unionName};`
                : ''
            }`,
          );
        } else {
          base = 'z.any()';
          break;
        }
      }

      base = unionName;
      break;
    }
    default:
      base = 'z.any()';
  }

  if (port.description && !base.includes('.describe(')) {
    base = `${base}.describe(${JSON.stringify(port.description)})`;
  }

  if (port.nullable) {
    base = `${base}.nullable().optional()`;
  }

  return base;
}

const generateOptimisticState = (optimistic: Optimistic) => {
  const optimisticName = `Optimistic${toCamel(optimistic.state)}`;

  return `
export const ${optimisticName} = {
  key: '${optimistic.state}',
  selector: (state: never) => ${optimistic.path.split('.').reduce((accumulator, part) => (part ? `${accumulator}.${part}` : accumulator), 'state')},
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  accessor: (state: any, args: any) => ${optimistic.accessor},
};`;
};

const generateActionContent = (
  key: string,
  implementation: HookImplementation,
  importPathToUseAction: string,
  appKey?: string,
  symbolPrefix?: string,
) => {
  const context: SchemaGeneratorContext = {
    subSchemas: new Map<string, string>(),
    symbolPrefix,
  };

  const baseName = toPascal(key);
  const generatedName = withSymbolPrefix(baseName, symbolPrefix);
  const hookName = `use${baseName}`;
  const qualifiedHookName = symbolPrefix ? `use${generatedName}` : hookName;
  const definitionName = `${generatedName}Definition`;
  const argsSchemaName = `${generatedName}ArgsSchema`;
  const returnSchemaName = `${generatedName}ReturnSchema`;
  const argsTypeName = `${generatedName}Args`;
  const returnTypeName = `${generatedName}Return`;
  const description = implementation.definition.description || '';
  const argsFields = implementation.definition.args ?? [];
  const returnFields = implementation.definition.returns ?? [];
  const argsSchemaCode = appendValidators(
    `z.object({\n${argsFields.map((field) => `${renderDescription(field.description)}${toObjectPropertyKey(field.key ?? 'value')}: ${mapPortToZod(field, context, field.key ?? 'Arg')}`).join(',\n')}\n})`,
    argsFields,
  );
  const returnsSchemaCode = appendValidators(
    `z.object({\n${returnFields.map((field) => `${renderDescription(field.description)}${toObjectPropertyKey(field.key ?? 'value')}: ${mapPortToZod(field, context, field.key ?? 'Return')}`).join(',\n')}\n})`,
    returnFields,
  );
  const subSchemasCode = Array.from(context.subSchemas.values()).join('\n\n');
  const includesUnion = subSchemasCode.includes('createIndexedUnion');
  const schemaAndTypeAliases = symbolPrefix
    ? `
export const ${baseName}ArgsSchema = ${argsSchemaName};
export const ${baseName}ReturnSchema = ${returnSchemaName};
export type ${baseName}Args = ${argsTypeName};
export type ${baseName}Return = ${returnTypeName};`
    : '';
  const definitionAlias = symbolPrefix
    ? `
export const ${baseName}Definition = ${definitionName};`
    : '';

  const optimisticExports = (implementation.optimistics ?? []).map(
    (optimistic) => {
      const optimisticName = `Optimistic${toCamel(optimistic.state)}`;
      const generatedOptimisticName = withSymbolPrefix(
        optimisticName,
        symbolPrefix,
      );
      const optimisticExport = generateOptimisticState(optimistic).replace(
        `export const ${optimisticName}`,
        `export const ${generatedOptimisticName}`,
      );

      if (!symbolPrefix) {
        return optimisticExport;
      }

      return `${optimisticExport}\n\nexport const ${optimisticName} = ${generatedOptimisticName};`;
    },
  );

  return `
import { z } from 'zod';
import { useAction, type ActionDefinition } from '${importPathToUseAction}';
${includesUnion ? "import { createIndexedUnion } from './utils';" : ''}

// --- Shared Models ---
${subSchemasCode}

// --- Schemas ---
export const ${argsSchemaName} = ${argsSchemaCode};
export const ${returnSchemaName} = ${returnsSchemaCode};

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type ${argsTypeName} = z.input<typeof ${argsSchemaName}>;
export type ${returnTypeName} = z.infer<typeof ${returnSchemaName}>;
${schemaAndTypeAliases}

// --- Definition ---
export const ${definitionName}: ActionDefinition<${argsTypeName}, ${returnTypeName}> = {
  name: '${key}',
  appKey: '${appKey}',
  description: ${JSON.stringify(implementation.description || description || '')},
  argsSchema: ${argsSchemaName},
  returnSchema: ${returnSchemaName},
  lockKeys: ${JSON.stringify((implementation.locks ?? []).sort())},
};
${definitionAlias}

/**
 * ${implementation.description || description}
 */
export const ${qualifiedHookName} = () => {
  return useAction(${definitionName});
};
${
  qualifiedHookName !== hookName
    ? `
export const ${hookName} = ${qualifiedHookName};`
    : ''
}

${optimisticExports.length > 0 ? `/** Optimistic state hooks for ${key} */` : ''}
${optimisticExports.join('\n')}
`;
};

const generateStateContent = (
  key: string,
  stateDefinition: StateSchemaImplementation,
  importPathToSync: string,
  appKey?: string,
  symbolPrefix?: string,
) => {
  const context: SchemaGeneratorContext = {
    subSchemas: new Map<string, string>(),
    symbolPrefix,
  };
  const baseName = toPascal(key);
  const generatedName = withSymbolPrefix(baseName, symbolPrefix);
  const hookName = `use${baseName}`;
  const qualifiedHookName = symbolPrefix ? `use${generatedName}` : hookName;
  const schemaName = `${generatedName}Schema`;
  const typeName = generatedName;
  const definitionName = `${generatedName}Definition`;
  const fields = (stateDefinition.definition.ports ?? [])
    .map(
      (port) =>
        `  ${toObjectPropertyKey(port.key ?? 'value')}: ${mapPortToZod(port, context, port.key ?? 'State')}`,
    )
    .join(',\n');
  const subSchemasCode = Array.from(context.subSchemas.values()).join('\n\n');
  const includesUnion = subSchemasCode.includes('createIndexedUnion');
  const schemaAndTypeAliases = symbolPrefix
    ? `
export const ${baseName}Schema = ${schemaName};
export type ${baseName} = ${typeName};`
    : '';
  const definitionAlias = symbolPrefix
    ? `
export const ${baseName}Definition = ${definitionName};`
    : '';

  return `
import { z } from 'zod';
import { buildUseState, type StateDefinition } from '${importPathToSync}';
${includesUnion ? "import { createIndexedUnion } from './utils';" : ''}

// --- Sub-Schemas ---
${subSchemasCode}

// --- Main Schema ---
export const ${schemaName} = z.object({
${fields}
});

// --- Type ---
export type ${typeName} = z.infer<typeof ${schemaName}>;
${schemaAndTypeAliases}

// --- Definition ---
export const ${definitionName}: StateDefinition<${typeName}, '${key}'> = {
  ${appKey ? `appKey: '${appKey}',` : ''}
  key: '${key}',
  schema: ${schemaName},
};
${definitionAlias}

/**
 * Hook to sync ${key}
 */
export const ${qualifiedHookName} = buildUseState<${typeName}>(${definitionName});
${
  qualifiedHookName !== hookName
    ? `
export const ${hookName} = ${qualifiedHookName};`
    : ''
}
`;
};

const generateLockContent = (
  key: string,
  lockDefinition: LockSchemaDefinition,
  importPathToSync: string,
  appKey?: string,
  symbolPrefix?: string,
) => {
  const baseName = toPascal(key);
  const generatedName = withSymbolPrefix(baseName, symbolPrefix);
  const hookName = `use${baseName}Lock`;
  const qualifiedHookName = symbolPrefix ? `use${generatedName}Lock` : hookName;
  const definitionName = `${generatedName}Definition`;
  const compatibilityAliases = symbolPrefix
    ? `

export const ${baseName}Definition = ${definitionName};`
    : '';

  return `
import { useLock, type LockDefinition, type UseLockOptions } from '${importPathToSync}';

// --- Definition ---
export const ${definitionName}: LockDefinition<'${key}'> = {
  // ${lockDefinition.description ? lockDefinition.description : 'No description provided'}
  ${appKey ? `appKey: '${appKey}',` : ''}
  key: '${key}',
};

/**
 * Hook to sync ${key}
 */
export const ${qualifiedHookName} = (options?: UseLockOptions) => {
  return useLock<'${key}'>(${definitionName}, options);
};
${
  qualifiedHookName !== hookName
    ? `
export const ${hookName} = ${qualifiedHookName};`
    : ''
}${compatibilityAliases}
`;
};

const writeSharedUtilsIfNeeded = async (outputDir: string) => {
  await formatAndWrite(path.join(outputDir, 'utils.ts'), SHARED_UTILS_CODE);
};

const generateActionsDirectory = async (options: {
  schema: HooksSchema;
  outputDir: string;
  importPathToUseAction: string;
  indexImportPathToUseAction: string;
  appKey: string;
  symbolPrefix?: string;
  whitelist?: string[];
  blacklist?: string[];
}) => {
  const {
    schema,
    outputDir,
    importPathToUseAction,
    indexImportPathToUseAction,
    appKey,
    symbolPrefix,
    whitelist,
    blacklist,
  } = options;

  ensureDir(outputDir);
  await writeSharedUtilsIfNeeded(outputDir);

  const emitted = new Set<string>(['utils.ts', 'index.ts']);
  const fileExports = new Map<string, ExportEntry[]>();
  fileExports.set(
    'utils',
    getExportEntries(await formatTypeScript(SHARED_UTILS_CODE)),
  );
  const generatedActions: ActionModuleEntry[] = [];

  for (const [key, implementation] of sortedEntries(schema.implementations)) {
    if (!shouldGenerate(key, whitelist, blacklist)) {
      continue;
    }

    const hookFileName = toCamel(key);
    const hookName = toPascal(key);
    const definitionName = `${withSymbolPrefix(hookName, symbolPrefix)}Definition`;
    const code = generateActionContent(
      key,
      implementation,
      importPathToUseAction,
      appKey,
      symbolPrefix,
    );
    const formatted = await formatTypeScript(code);

    emitted.add(`${hookFileName}.ts`);
    writeIfChanged(path.join(outputDir, `${hookFileName}.ts`), formatted);
    fileExports.set(hookFileName, getExportEntries(formatted));
    generatedActions.push({
      fileName: hookFileName,
      exportName: hookName,
      definitionName,
    });
  }

  const definitionImports = generatedActions
    .map(
      ({ fileName, definitionName }) =>
        `import { ${definitionName} } from './${fileName}';`,
    )
    .join('\n');
  const definitionEntries = generatedActions
    .map(
      ({ exportName, definitionName }) => `  ${exportName}: ${definitionName},`,
    )
    .join('\n');
  const barrelExports = buildBarrelExports(fileExports);
  const indexCode = `import type { ActionDefinition } from '${indexImportPathToUseAction}';
${definitionImports}

${barrelExports}

export const globalActionDefinition = {
${definitionEntries}
} satisfies Record<string, ActionDefinition<unknown, unknown>>;

export type GlobalActionDefinition = typeof globalActionDefinition;
export const globalActionDefintiion = globalActionDefinition;
`;

  await formatAndWrite(path.join(outputDir, 'index.ts'), indexCode);
  pruneDir(outputDir, emitted);
};

const generateStatesDirectory = async (options: {
  schema: StatesSchema;
  outputDir: string;
  importPathToSync: string;
  appKey: string;
  symbolPrefix?: string;
  whitelist?: string[];
  blacklist?: string[];
}) => {
  const {
    schema,
    outputDir,
    importPathToSync,
    appKey,
    symbolPrefix,
    whitelist,
    blacklist,
  } = options;

  ensureDir(outputDir);
  await writeSharedUtilsIfNeeded(outputDir);

  const emitted = new Set<string>(['utils.ts', 'index.ts']);
  const fileExports = new Map<string, ExportEntry[]>();
  fileExports.set(
    'utils',
    getExportEntries(await formatTypeScript(SHARED_UTILS_CODE)),
  );
  const generatedStates: StateModuleEntry[] = [];

  for (const [key, stateDefinition] of sortedEntries(schema.states)) {
    if (!shouldGenerate(key, whitelist, blacklist)) {
      continue;
    }

    const stateName = toPascal(key);
    const definitionName = `${withSymbolPrefix(stateName, symbolPrefix)}Definition`;
    const code = generateStateContent(
      key,
      stateDefinition,
      importPathToSync,
      appKey,
      symbolPrefix,
    );
    const formatted = await formatTypeScript(code);

    emitted.add(`${stateName}.ts`);
    writeIfChanged(path.join(outputDir, `${stateName}.ts`), formatted);
    fileExports.set(stateName, getExportEntries(formatted));
    generatedStates.push({
      fileName: stateName,
      exportName: stateName,
      definitionName,
    });
  }

  const definitionImports = generatedStates
    .map(
      ({ fileName, definitionName }) =>
        `import { ${definitionName} } from './${fileName}';`,
    )
    .join('\n');
  const definitionEntries = generatedStates
    .map(
      ({ exportName, definitionName }) => `  ${exportName}: ${definitionName},`,
    )
    .join('\n');
  const barrelExports = buildBarrelExports(fileExports);
  const indexCode = `
import type { StateDefinition } from '${importPathToSync}';
${definitionImports}

${barrelExports}

export const globalStateDefinition = {
${definitionEntries}
} satisfies Record<string, StateDefinition<unknown>>;

type InferStateDefinition<TDefinition> =
  TDefinition extends StateDefinition<infer TState, string> ? TState : never;

export type GlobalStateDefinition = typeof globalStateDefinition;
export type GlobalStateKey = keyof GlobalStateDefinition;
export type GlobalStateShape = {
  [K in GlobalStateKey]: InferStateDefinition<GlobalStateDefinition[K]>;
};

export const globalStateKeys = Object.values(globalStateDefinition).map((definition) => definition.key) as GlobalStateKey[];
export const globalStateDefintiion = globalStateDefinition;
`;

  await formatAndWrite(path.join(outputDir, 'index.ts'), indexCode);
  pruneDir(outputDir, emitted);
};

const generateLocksDirectory = async (options: {
  schema: LocksSchema;
  outputDir: string;
  importPathToSync: string;
  appKey: string;
  symbolPrefix?: string;
  whitelist?: string[];
  blacklist?: string[];
}) => {
  const {
    schema,
    outputDir,
    importPathToSync,
    appKey,
    symbolPrefix,
    whitelist,
    blacklist,
  } = options;

  ensureDir(outputDir);

  const emitted = new Set<string>(['index.ts']);
  const fileExports = new Map<string, ExportEntry[]>();
  const generatedLocks: LockModuleEntry[] = [];

  for (const [key, lockDefinition] of sortedEntries(schema.locks)) {
    if (!shouldGenerate(key, whitelist, blacklist)) {
      continue;
    }

    const lockName = toPascal(key);
    const definitionName = `${withSymbolPrefix(lockName, symbolPrefix)}Definition`;
    const code = generateLockContent(
      key,
      lockDefinition,
      importPathToSync,
      appKey,
      symbolPrefix,
    );
    const formatted = await formatTypeScript(code);

    emitted.add(`${lockName}.ts`);
    writeIfChanged(path.join(outputDir, `${lockName}.ts`), formatted);
    fileExports.set(lockName, getExportEntries(formatted));
    generatedLocks.push({
      fileName: lockName,
      exportName: lockName,
      definitionName,
    });
  }

  const definitionImports = generatedLocks
    .map(
      ({ fileName, definitionName }) =>
        `import { ${definitionName} } from './${fileName}';`,
    )
    .join('\n');
  const definitionEntries = generatedLocks
    .map(
      ({ exportName, definitionName }) => `  ${exportName}: ${definitionName},`,
    )
    .join('\n');
  const barrelExports = buildBarrelExports(fileExports);
  const indexCode = `
import type { LockDefinition } from '${importPathToSync}';
${definitionImports}

${barrelExports}

export const globalLockDefinition = {
${definitionEntries}
} satisfies Record<string, LockDefinition<string>>;

export type GlobalLockDefinition = typeof globalLockDefinition;
type InferLockKey<TDefinition> =
  TDefinition extends LockDefinition<infer TKey> ? TKey : never;

export type GlobalLockKey = InferLockKey<
  GlobalLockDefinition[keyof GlobalLockDefinition]
>;
export const globalLockKeys = Object.values(globalLockDefinition).map((definition) => definition.key) as GlobalLockKey[];
export const globalLockDefintiion = globalLockDefinition;
`;

  await formatAndWrite(path.join(outputDir, 'index.ts'), indexCode);
  pruneDir(outputDir, emitted);
};

const buildTaskHookContent = (
  appKey: string,
  symbolPrefix: string | undefined,
  hookName: 'Cancel' | 'Pause' | 'Resume' | 'Step',
  rekuestImportPath: string,
) => {
  const qualifiedHookName = `use${symbolPrefix ?? ''}${hookName}Task`;
  const baseHookName = `use${hookName}AppTask`;

  const aliasExport = symbolPrefix
    ? `\nexport const use${hookName}Task = ${qualifiedHookName};\n`
    : '';

  return `
import { ${baseHookName} } from '${rekuestImportPath}/task';

export const ${qualifiedHookName} = () => ${baseHookName}('${appKey}');${aliasExport}`;
};

const buildTaskStoreHookContent = (
  appKey: string,
  symbolPrefix: string | undefined,
  rekuestImportPath: string,
) => {
  const qualifiedHookName = `use${symbolPrefix ?? ''}TaskStore`;

  const aliasExport = symbolPrefix
    ? `\nexport const useTaskStore = ${qualifiedHookName};\n`
    : '';

  return `
import { useTaskStore as useBaseTaskStore, type TaskStore } from '${rekuestImportPath}/task';

export const ${qualifiedHookName} = <TSelected>(
  selector: (state: TaskStore) => TSelected,
): TSelected => useBaseTaskStore('${appKey}', selector);${aliasExport}`;
};

const buildStateStoreHookContent = (
  appKey: string,
  symbolPrefix: string | undefined,
  rekuestImportPath: string,
) => {
  const qualifiedHookName = `use${symbolPrefix ?? ''}StateStore`;

  const aliasExport = symbolPrefix
    ? `\nexport const useStateStore = ${qualifiedHookName};\n`
    : '';

  return `
import { useGlobalStateStore as useBaseStateStore, type GlobalStateStore } from '${rekuestImportPath}/state';

export const ${qualifiedHookName} = <TSelected>(
  selector: (state: GlobalStateStore) => TSelected,
): TSelected => useBaseStateStore('${appKey}', selector);${aliasExport}`;
};

const buildLockStoreHookContent = (
  appKey: string,
  symbolPrefix: string | undefined,
  rekuestImportPath: string,
) => {
  const qualifiedHookName = `use${symbolPrefix ?? ''}LockStore`;

  const aliasExport = symbolPrefix
    ? `\nexport const useLockStore = ${qualifiedHookName};\n`
    : '';

  return `
import { useLockStore as useBaseLockStore, type LockStore } from '${rekuestImportPath}/locks';

export const ${qualifiedHookName} = <TSelected>(
  selector: (state: LockStore) => TSelected,
): TSelected => useBaseLockStore('${appKey}', selector);${aliasExport}`;
};

const isHooksSchema = (
  value: Record<string, unknown> | null,
): value is HooksSchema =>
  !!value &&
  typeof value.implementations === 'object' &&
  value.implementations !== null;

const isStatesSchema = (
  value: Record<string, unknown> | null,
): value is StatesSchema =>
  !!value && typeof value.states === 'object' && value.states !== null;

const isLocksSchema = (
  value: Record<string, unknown> | null,
): value is LocksSchema =>
  !!value && typeof value.locks === 'object' && value.locks !== null;

export default function generateAppsPlugin(
  options: GenerateAppsPluginOptions,
): Plugin {
  const normalizedApps = normalizeApps(options.apps);
  const appsDir = options.baseDir
    ? path.resolve(options.baseDir)
    : DEFAULT_APPS_DIR;
  const rekuestImportPath =
    options.rekuestImportPath ?? DEFAULT_REKUEST_IMPORT_PATH;

  // buildStart fires on `vite build` AND on every dev-server (re)start. Without this the
  // whole pipeline - three fetches plus a full rewrite - re-runs on each restart.
  let generation: Promise<void> | null = null;

  return {
    name: 'vite-plugin-generate-apps',
    async buildStart() {
      generation ??= generate();
      return generation;
    },
  };

  async function generate() {
    ensureDir(appsDir);

    const packageData = readJsonFile(PACKAGE_JSON_PATH) ?? {};
    const scripts =
      (packageData.scripts as Record<string, string> | undefined) ?? {};
    const previousBlok = readJsonFile(BLOK_PATH) ?? {};
    const previousApps =
      (previousBlok.apps as
        | Record<string, Record<string, unknown>>
        | undefined) ?? {};
    const blokApps: Record<string, Record<string, unknown>> = {};
    const availableApps: NormalizedGenerateAppPluginOptions[] = [];

    for (const app of normalizedApps) {
      const appRootDir = path.resolve(appsDir, app.key);
      const appHooksDir = path.resolve(appRootDir, 'hooks');
      const appActionsDir = path.resolve(appHooksDir, 'actions');
      const appStatesDir = path.resolve(appHooksDir, 'states');
      const appLocksDir = path.resolve(appHooksDir, 'locks');

      ensureDir(appRootDir);
      ensureDir(appHooksDir);

      const [hooksSchemaJson, statesSchemaJson, locksSchemaJson] =
        await Promise.all([
          fetchSchemaJson(app.hooksSchemaUrl, `${app.key} task schema`),
          fetchSchemaJson(app.statesSchemaUrl, `${app.key} state schema`),
          fetchSchemaJson(app.locksSchemaUrl, `${app.key} lock schema`),
        ]);

      const previousAppEntry = previousApps[app.key] ?? {};
      const previousAppSchemas = (previousAppEntry.schemas ?? {}) as Record<
        string,
        string | null
      >;

      blokApps[app.key] = {
        key: app.key,
        name: app.name ?? app.key,
        tasks:
          (hooksSchemaJson?.implementations as
            | Record<string, unknown>
            | undefined) ??
          (previousAppEntry.tasks as Record<string, unknown> | undefined) ??
          {},
        states:
          (statesSchemaJson?.states as Record<string, unknown> | undefined) ??
          (previousAppEntry.states as Record<string, unknown> | undefined) ??
          {},
        locks:
          (locksSchemaJson?.locks as Record<string, unknown> | undefined) ??
          (previousAppEntry.locks as Record<string, unknown> | undefined) ??
          {},
        // Fall back to the recorded URLs: these come from env (VITE_SCHEMA_*), so a build
        // with those vars unset would otherwise overwrite good values with null.
        schemas: {
          tasks: app.hooksSchemaUrl ?? previousAppSchemas.tasks ?? null,
          states: app.statesSchemaUrl ?? previousAppSchemas.states ?? null,
          locks: app.locksSchemaUrl ?? previousAppSchemas.locks ?? null,
        },
      };

      if (isHooksSchema(hooksSchemaJson)) {
        await generateActionsDirectory({
          schema: hooksSchemaJson,
          outputDir: appActionsDir,
          importPathToUseAction: `${rekuestImportPath}/task`,
          indexImportPathToUseAction: `${rekuestImportPath}/task`,
          appKey: app.key,
          symbolPrefix: app.symbolPrefix,
          whitelist: app.hooksWhitelist,
          blacklist: app.hooksBlacklist,
        });
      }

      if (isStatesSchema(statesSchemaJson)) {
        await generateStatesDirectory({
          schema: statesSchemaJson,
          outputDir: appStatesDir,
          importPathToSync: `${rekuestImportPath}/state`,
          appKey: app.key,
          symbolPrefix: app.symbolPrefix,
          whitelist: app.statesWhitelist,
          blacklist: app.statesBlacklist,
        });
      }

      if (isLocksSchema(locksSchemaJson)) {
        await generateLocksDirectory({
          schema: locksSchemaJson,
          outputDir: appLocksDir,
          importPathToSync: `${rekuestImportPath}/locks`,
          appKey: app.key,
          symbolPrefix: app.symbolPrefix,
          whitelist: app.locksWhitelist,
          blacklist: app.locksBlacklist,
        });
      }

      await formatAndWrite(
        path.resolve(appHooksDir, 'useCancelTask.ts'),
        buildTaskHookContent(
          app.key,
          app.symbolPrefix,
          'Cancel',
          rekuestImportPath,
        ),
      );

      await formatAndWrite(
        path.resolve(appHooksDir, 'usePauseTask.ts'),
        buildTaskHookContent(
          app.key,
          app.symbolPrefix,
          'Pause',
          rekuestImportPath,
        ),
      );

      await formatAndWrite(
        path.resolve(appHooksDir, 'useResumeTask.ts'),
        buildTaskHookContent(
          app.key,
          app.symbolPrefix,
          'Resume',
          rekuestImportPath,
        ),
      );

      await formatAndWrite(
        path.resolve(appHooksDir, 'useStepTask.ts'),
        buildTaskHookContent(
          app.key,
          app.symbolPrefix,
          'Step',
          rekuestImportPath,
        ),
      );

      await formatAndWrite(
        path.resolve(appHooksDir, 'useTaskStore.ts'),
        buildTaskStoreHookContent(app.key, app.symbolPrefix, rekuestImportPath),
      );

      await formatAndWrite(
        path.resolve(appHooksDir, 'useStateStore.ts'),
        buildStateStoreHookContent(
          app.key,
          app.symbolPrefix,
          rekuestImportPath,
        ),
      );

      await formatAndWrite(
        path.resolve(appHooksDir, 'useLockStore.ts'),
        buildLockStoreHookContent(app.key, app.symbolPrefix, rekuestImportPath),
      );

      const hasAppDefinitionFiles = [
        path.resolve(appActionsDir, 'index.ts'),
        path.resolve(appStatesDir, 'index.ts'),
        path.resolve(appLocksDir, 'index.ts'),
      ].every((filePath) => fs.existsSync(filePath));

      if (hasAppDefinitionFiles) {
        await formatAndWrite(
          path.resolve(appRootDir, 'app.ts'),
          `
import {
  globalActionDefinition,
  type GlobalActionDefinition,
} from './hooks/actions';
import {
  globalLockDefinition,
  type GlobalLockDefinition,
} from './hooks/locks';
import {
  globalStateDefinition,
  type GlobalStateDefinition,
} from './hooks/states';

export interface AppDefinition<TAppKey extends string = string> {
  key: TAppKey;
  actions: GlobalActionDefinition;
  locks: GlobalLockDefinition;
  states: GlobalStateDefinition;
}

export const appDefinition = {
  key: '${app.key}',
  actions: globalActionDefinition,
  locks: globalLockDefinition,
  states: globalStateDefinition,
} satisfies AppDefinition<'${app.key}'>;
`,
        );

        availableApps.push(app);
      } else {
        console.warn(
          `⚠️ [GenApps] Skipping app registry entry for "${app.key}" because generated definitions are unavailable. Existing code was preserved.`,
        );
      }
    }

    const appImports = availableApps
      .map(
        (app) =>
          `import { appDefinition as ${toPascal(app.key)}AppDefinition } from './${app.key}/app';`,
      )
      .join('\n');

    const appEntries = availableApps
      .map(
        (app) =>
          `  ${JSON.stringify(app.key)}: ${toPascal(app.key)}AppDefinition,`,
      )
      .join('\n');

    await formatAndWrite(
      path.resolve(appsDir, 'index.ts'),
      `
${appImports}

export const appsDefinition = {
${appEntries}
} as const;

export type AppsDefinition = typeof appsDefinition;
export type AppKey = keyof AppsDefinition;
export type AppDefinition = AppsDefinition[AppKey];
`,
    );

    // Everything except generatedAt. Key order comes from the backend's JSON and is not
    // stable, so deep-sort it before comparing or writing.
    const blokPayload = sortKeysDeep(
      sortSetLikeSchemaArrays({
        app: {
          name: (packageData.name as string | undefined) ?? 'unknown',
          version: (packageData.version as string | undefined) ?? '0.0.0',
          description: (packageData.description as string | undefined) ?? '',
          startPage:
            (packageData.homepage as string | undefined) ?? '/index.html',
          type: (packageData.type as string | undefined) ?? 'unknown',
          scripts: {
            dev: scripts.dev ?? '',
            build: scripts.build ?? '',
            preview: scripts.preview ?? '',
          },
        },
        apps: blokApps,
      }),
    ) as Record<string, unknown>;

    // Only stamp a new generatedAt when the content actually changed. Otherwise every
    // dev-server start would dirty blok.json (780KB) for no reason.
    const { generatedAt: previousGeneratedAt, ...previousPayload } =
      previousBlok;
    const unchanged =
      typeof previousGeneratedAt === 'string' &&
      JSON.stringify(sortKeysDeep(previousPayload)) ===
        JSON.stringify(blokPayload);

    formatAndWriteJson(BLOK_PATH, {
      generatedAt: unchanged ? previousGeneratedAt : new Date().toISOString(),
      ...blokPayload,
    });
  }
}
