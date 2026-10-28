/**
 * Pure helpers that bind a blok, as the newswitch backend declares it
 * (`/schemas/bloks`, generated into `src/apps/<app>/bloks.ts`), to the
 * newswitch app it runs against. The React side is `NewswitchBlok`.
 *
 * A blok names what it needs through its dependencies. In newswitch the only
 * dependency that can be served is `self`: the newswitch app itself. Its state
 * dependencies are read from the app's state store, and its action
 * dependencies are assigned as tasks of the app.
 */
import { z } from "zod";
import { parseBsx } from "@arkitektio/bsx/bsx/parse";
import {
  demoModel,
  parseBlokDeclarations,
} from "@arkitektio/bsx/renderer/declarations";
import {
  normalizeBlokComponentTree,
  type BlokTaskUpdate,
} from "@arkitektio/bsx/renderer/runtime/index";
import type { Task } from "@/lib/arkitekt/transport/types";

/** The dependency key under which a blok addresses the app it is served by. */
export const SELF_DEPENDENCY = "self";

type ArgMatch = { readonly at?: number | null; readonly key: string };

/** The part of a generated blok entry the host reads (blok language v2). */
export type NewswitchBlokDeclaration = {
  readonly key: string;
  /** The parsed tree; a blok declared from source carries `source` instead. */
  readonly components: ReadonlyArray<unknown> | null;
  /** Its BSX source, which the frontend parses. */
  readonly source?: string | null;
  readonly vocab?: number | null;
  /** What it is drawn with before anything is live: `{deps: {self: {<State>: ...}}, args, ...}`. */
  readonly demo?: unknown;
  readonly locals?: unknown;
  readonly queries?: unknown;
  readonly subscriptions?: unknown;
  readonly dependencies?: ReadonlyArray<{
    readonly key: string;
    readonly actionDependencies?: ReadonlyArray<{
      readonly key: string;
      readonly demand?: {
        readonly key?: string | null;
        readonly argMatches?: ReadonlyArray<ArgMatch> | null;
      } | null;
    }> | null;
    readonly stateDependencies?: ReadonlyArray<{
      readonly key: string;
      readonly demand?: { readonly key?: string | null } | null;
    }> | null;
  }> | null;
};

const selfDependency = (blok: NewswitchBlokDeclaration) =>
  blok.dependencies?.find((dependency) => dependency.key === SELF_DEPENDENCY);

/** The states of the app a blok reads, by state (interface) name. */
export const selfStateKeys = (blok: NewswitchBlokDeclaration): string[] => [
  ...new Set(
    (selfDependency(blok)?.stateDependencies ?? []).map(
      (dependency) => dependency.demand?.key ?? dependency.key,
    ),
  ),
];

/** Dependencies other than `self`: nothing in newswitch can serve them. */
export const foreignDependencyKeys = (
  blok: NewswitchBlokDeclaration,
): string[] =>
  (blok.dependencies ?? [])
    .map((dependency) => dependency.key)
    .filter((key) => key !== SELF_DEPENDENCY);

/**
 * The argument names of an action, in positional order: from what the blok
 * demands of it (`argMatches`, each with its position `at`), else from the
 * order of the action's own args schema.
 */
export const actionArgOrder = (
  blok: NewswitchBlokDeclaration,
  operation: string,
  argsSchema?: z.ZodType,
): string[] => {
  const demand = selfDependency(blok)?.actionDependencies?.find(
    (dependency) => (dependency.demand?.key ?? dependency.key) === operation,
  )?.demand;
  const matches = demand?.argMatches;
  if (matches && matches.length > 0) {
    return [...matches]
      .map((match, index) => ({ key: match.key, at: match.at ?? index }))
      .sort((a, b) => a.at - b.at)
      .map((match) => match.key);
  }
  if (argsSchema instanceof z.ZodObject) {
    return Object.keys(argsSchema.shape);
  }
  return [];
};

const POSITIONAL = /^\d+$/;

/**
 * Turns the arguments of a resolved agent call into the action's named args.
 * A v2 blok names every argument (`self.switch_objective(slot: 2)`); one
 * spelled by index (`{"0": 2}`) is named by `argOrder`. Named arguments pass
 * through. A positional argument beyond the known names is an error.
 */
export const mapActionArguments = (
  args: Readonly<Record<string, unknown>> | undefined,
  argOrder: readonly string[],
):
  | { ok: true; args: Record<string, unknown> }
  | { ok: false; error: string } => {
  const entries = Object.entries(args ?? {});
  const named: Record<string, unknown> = Object.fromEntries(
    entries.filter(([key]) => !POSITIONAL.test(key)),
  );
  for (const [key, value] of entries) {
    if (!POSITIONAL.test(key)) continue;
    const name = argOrder[Number(key)];
    if (name === undefined) {
      return {
        ok: false,
        error: `Positional argument ${key} has no matching parameter (expected ${argOrder.length}: ${argOrder.join(", ") || "none"}).`,
      };
    }
    if (name in named) {
      return {
        ok: false,
        error: `Argument "${name}" is given both by position and by name.`,
      };
    }
    named[name] = value;
  }
  return { ok: true, args: named };
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * The blok's root nodes: its tree as served (checked by the renderer's
 * preflight), else its source parsed here. Throws a `BsxSyntaxError` for a
 * source that does not parse.
 */
export const blokRoots = (blok: NewswitchBlokDeclaration): unknown[] => {
  if (blok.components && blok.components.length > 0) {
    return normalizeBlokComponentTree(blok.components).roots;
  }
  return blok.source ? [parseBsx(blok.source).tree] : [];
};

/**
 * The data model a blok is drawn with before anything is live: its declared
 * locals at their defaults, its `into` records idle, and its `demo`
 * (`deps.self.<State>` among it).
 */
export const blokModel = (
  blok: NewswitchBlokDeclaration,
  roots: ReadonlyArray<unknown>,
): Record<string, unknown> =>
  demoModel(
    roots,
    parseBlokDeclarations({
      vocab: blok.vocab,
      componentTree: blok.components,
      locals: blok.locals,
      demo: blok.demo,
      queries: blok.queries,
      subscriptions: blok.subscriptions,
    }),
  );

/**
 * The data model a blok is drawn against: `model` (`blokModel`), with every
 * state of the app it reads (`deps.self.<State>`, which `self.<State>` reads)
 * replaced by the live value once there is one.
 */
export const mergeLiveState = (
  model: Record<string, unknown>,
  live: Readonly<Record<string, unknown>>,
): Record<string, unknown> => {
  const present = Object.entries(live).filter(([, value]) => value != null);
  if (present.length === 0) return model;
  const deps = isRecord(model.deps) ? model.deps : {};
  const self = isRecord(deps[SELF_DEPENDENCY]) ? deps[SELF_DEPENDENCY] : {};
  return {
    ...model,
    deps: {
      ...deps,
      [SELF_DEPENDENCY]: { ...self, ...Object.fromEntries(present) },
    },
  };
};

/** What a blok's task binding learns from one update of a newswitch task. */
export const taskUpdateOf = (
  task: Pick<
    Task,
    "status" | "progress" | "progressMessage" | "result" | "error"
  >,
): BlokTaskUpdate => {
  const update: BlokTaskUpdate = {};
  if (typeof task.progress === "number") update.progress = task.progress;
  if (task.progressMessage) update.message = task.progressMessage;
  if (task.result !== undefined) update.returns = task.result;
  switch (task.status) {
    case "completed":
      update.end = "done";
      break;
    case "failed":
    case "interrupted":
      update.end = "failed";
      update.error = task.error ?? `Task ${task.status}`;
      break;
    case "cancelled":
      update.end = "cancelled";
      break;
  }
  return update;
};
