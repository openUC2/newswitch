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
import type { BlokTaskUpdate } from "./renderer/runtime";
import type { Task } from "@/lib/arkitekt/transport/types";

/** The dependency key under which a blok addresses the app it is served by. */
export const SELF_DEPENDENCY = "self";

type ArgMatch = { readonly at?: number | null; readonly key: string };

/** The part of a generated blok entry the host reads. */
export type NewswitchBlokDeclaration = {
  readonly key: string;
  readonly components: ReadonlyArray<unknown> | null;
  readonly demoState?: unknown;
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
 * A blok spells positional arguments by index (`@self.switch_objective(2)`
 * arrives as `{"0": 2}`); they are named by `argOrder`. Named arguments pass
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
 * The data model a blok is drawn against: its demo state, with every state of
 * the app it reads replaced by the live value once there is one.
 */
export const mergeLiveState = (
  demoState: unknown,
  live: Readonly<Record<string, unknown>>,
): unknown => {
  const present = Object.entries(live).filter(([, value]) => value != null);
  if (present.length === 0) return demoState;
  const base = isRecord(demoState) ? demoState : {};
  const self = isRecord(base[SELF_DEPENDENCY]) ? base[SELF_DEPENDENCY] : {};
  return {
    ...base,
    [SELF_DEPENDENCY]: { ...self, ...Object.fromEntries(present) },
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
