/**
 * Evaluating blok `UtilCall`s: the pure calls validators (and optimistic paths) are
 * written in, e.g. `len(value) > 0` arrives as
 * `{ operation: "gt", arguments: [{ key: "a", utilCall: { operation: "len", ... } }, ...] }`.
 *
 * Arguments resolve from `valueLiteral`, `valuePath` (`value` is the port's own value,
 * any other name a sibling port listed in the validator's dependencies), a nested
 * `utilCall`, `valueList` or `valueDict`. Only the pure operations of the standard
 * catalog that make sense in a form are known here; an unknown operation does not
 * block the user: the call counts as unresolved and validators let the value pass.
 */

export type CallArgument = {
  key?: string | null;
  valueLiteral?: unknown;
  valuePath?: string | null;
  utilCall?: UtilCall | null;
  valueList?: CallArgument[] | null;
  valueDict?: CallArgument[] | null;
  /** Calls to agents are never pure; a validator cannot contain one. */
  agentCall?: unknown;
};

export type UtilCall = {
  operation: string;
  arguments?: CallArgument[] | null;
};

export type CallScope = {
  /** The port's own value (`valuePath: "value"`). */
  value: unknown;
  /** Sibling port values, by key. */
  dependencies?: Record<string, unknown>;
};

class UnknownOperation extends Error {}

const isNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

const length = (value: unknown): number => {
  if (value == null) return 0;
  if (typeof value === "string" || Array.isArray(value)) return value.length;
  if (typeof value === "object") return Object.keys(value as object).length;
  return 0;
};

const deepEqual = (a: unknown, b: unknown): boolean =>
  JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

const numeric =
  (fn: (a: number, b: number) => unknown) =>
  (args: Record<string, unknown>): unknown =>
    isNumber(args.a) && isNumber(args.b) ? fn(args.a, args.b) : null;

const compare =
  (fn: (a: number, b: number) => boolean) =>
  (args: Record<string, unknown>): boolean =>
    isNumber(args.a) && isNumber(args.b) && fn(args.a, args.b);

const readPointer = (value: unknown, path: unknown): unknown => {
  if (typeof path !== "string") return null;
  const segments = path
    .split("/")
    .slice(1)
    .map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));
  let current: unknown = value;
  for (const segment of segments) {
    if (current == null || typeof current !== "object") return null;
    current = (current as Record<string, unknown>)[segment];
  }
  return current ?? null;
};

type Operation = (args: Record<string, unknown>) => unknown;

const operations: Record<string, Operation> = {
  eq: ({ a, b }) => deepEqual(a, b),
  ne: ({ a, b }) => !deepEqual(a, b),
  gt: compare((a, b) => a > b),
  gte: compare((a, b) => a >= b),
  lt: compare((a, b) => a < b),
  lte: compare((a, b) => a <= b),
  between: ({ value, min, max }) =>
    isNumber(value) &&
    isNumber(min) &&
    isNumber(max) &&
    min <= value &&
    value <= max,
  and: ({ a, b }) => Boolean(a) && Boolean(b),
  or: ({ a, b }) => Boolean(a) || Boolean(b),
  not: ({ a }) => !a,
  len: ({ a }) => length(a),
  len_between: ({ value, min, max }) => {
    const n = length(value);
    return (!isNumber(min) || n >= min) && (!isNumber(max) || n <= max);
  },
  is_null: ({ a }) => a == null,
  is_set: ({ a }) => a != null,
  is_empty: ({ a }) => length(a) === 0,
  in: ({ value, options }) =>
    Array.isArray(options) && options.some((o) => deepEqual(o, value)),
  contains: ({ haystack, needle }) =>
    typeof haystack === "string"
      ? typeof needle === "string" && haystack.includes(needle)
      : Array.isArray(haystack) &&
        haystack.some((item) => deepEqual(item, needle)),
  starts_with: ({ value, prefix }) =>
    typeof value === "string" &&
    typeof prefix === "string" &&
    value.startsWith(prefix),
  ends_with: ({ value, suffix }) =>
    typeof value === "string" &&
    typeof suffix === "string" &&
    value.endsWith(suffix),
  matches: ({ value, pattern }) =>
    typeof value === "string" &&
    typeof pattern === "string" &&
    new RegExp(`^(?:${pattern})$`).test(value),
  coalesce: ({ a, b }) => a ?? b ?? null,
  if: ({ condition, then, otherwise }) => (condition ? then : otherwise),
  get: ({ value, path }) => readPointer(value, path),
  add: numeric((a, b) => a + b),
  sub: numeric((a, b) => a - b),
  mul: numeric((a, b) => a * b),
  div: numeric((a, b) => (b === 0 ? null : a / b)),
  mod: numeric((a, b) => (b === 0 ? null : ((a % b) + b) % b)),
  neg: ({ a }) => (isNumber(a) ? -a : null),
};

// The namespaced aliases of the standard catalog.
operations["compare.eq"] = operations.eq;
operations["compare.ne"] = operations.ne;
operations["compare.gt"] = operations.gt;
operations["compare.gte"] = operations.gte;
operations["compare.lt"] = operations.lt;
operations["compare.lte"] = operations.lte;
operations["compare.between"] = operations.between;
operations["logic.not"] = ({ value }) => !value;
operations["list.length"] = ({ value }) => length(value);
operations["list.isEmpty"] = ({ value }) => length(value) === 0;
operations["str.length"] = ({ value }) => length(value);
operations["type.isNil"] = ({ value }) => value == null;

const resolve = (argument: CallArgument, scope: CallScope): unknown => {
  if (argument.utilCall) return invoke(argument.utilCall, scope);
  if (argument.valuePath != null) {
    if (argument.valuePath === "value") return scope.value;
    return scope.dependencies?.[argument.valuePath];
  }
  if (argument.valueList)
    return argument.valueList.map((item) => resolve(item, scope));
  if (argument.valueDict) {
    return Object.fromEntries(
      argument.valueDict.map((item) => [item.key ?? "", resolve(item, scope)]),
    );
  }
  return argument.valueLiteral ?? null;
};

const invoke = (call: UtilCall, scope: CallScope): unknown => {
  const operation = operations[call.operation];
  if (!operation) throw new UnknownOperation(call.operation);
  const args: Record<string, unknown> = {};
  for (const argument of call.arguments ?? []) {
    args[argument.key ?? ""] = resolve(argument, scope);
  }
  return operation(args);
};

/** Evaluate `call`; `undefined` when it uses an operation not known here. */
export const evaluateCall = (call: UtilCall, scope: CallScope): unknown => {
  try {
    return invoke(call, scope);
  } catch (error) {
    if (error instanceof UnknownOperation) {
      console.warn(
        `Unknown blok operation "${error.message}"; the call is not evaluated.`,
      );
      return undefined;
    }
    throw error;
  }
};

/** Whether a validator's call accepts the value. An unevaluable call accepts it. */
export const validatorAccepts = (call: UtilCall, scope: CallScope): boolean => {
  const result = evaluateCall(call, scope);
  return result === undefined ? true : Boolean(result);
};
