import { useCallback, useEffect, useMemo } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { useShallow } from "zustand/react/shallow";
import { appDefinition } from "@/apps/default/app";
import { authFetch } from "@/lib/auth/authFetch";
import { useBackendUi } from "@/lib/blok/backendUi";
import type { BlokAsset, BlokAssetHost } from "@/lib/blok/renderer/assets";
import { BlokAssetHostProvider } from "@/lib/blok/renderer/assets";
import {
  BlokSceneHostProvider,
  type BlokSceneHost,
} from "@/lib/blok/renderer/bloks/scene";
import { selectAppIsLive, useAppStateStore } from "@/lib/arkitekt/app-state";
import { getBlockingLock, useLockStoreApi } from "@/lib/arkitekt/locks/store";
import type { StateDefinition } from "@/lib/arkitekt/state";
import { useStateContext } from "@/lib/arkitekt/state/state-context";
import { useGlobalStateStore } from "@/lib/arkitekt/state/store";
import { useTaskContext } from "@/lib/arkitekt/task/task-context";
import type { ActionDefinition } from "@/lib/arkitekt/task/types";
import type { Task } from "@/lib/arkitekt/transport/types";
import {
  SELF_DEPENDENCY,
  actionArgOrder,
  foreignDependencyKeys,
  mapActionArguments,
  mergeLiveState,
  selfStateKeys,
  taskUpdateOf,
  type NewswitchBlokDeclaration,
} from "@/lib/blok/newswitch";
import BlokRenderer from "@/lib/blok/renderer/BlokRenderer";
import { newswitchBlokCatalog } from "@/lib/blok/microscope/catalog";
import {
  normalizeBlokComponentTree,
  type BlokDispatchActionHandler,
  type BlokRefuseActionHandler,
} from "@/lib/blok/renderer/runtime";

const APP_KEY = appDefinition.key;

const ACTIONS_BY_NAME = new Map<string, ActionDefinition<unknown, unknown>>(
  Object.values(appDefinition.actions).map(
    (definition) =>
      [
        definition.name,
        definition as ActionDefinition<unknown, unknown>,
      ] as const,
  ),
);

const STATE_DEFINITIONS: Record<
  string,
  StateDefinition<Record<string, unknown>, string> | undefined
> = appDefinition.states as Record<
  string,
  StateDefinition<Record<string, unknown>, string>
>;

const TERMINAL: ReadonlySet<Task["status"]> = new Set([
  "completed",
  "failed",
  "cancelled",
  "interrupted",
]);

const REPLAY_REASON = "Replay mode: actions are paused";

type NewswitchBlokProps = Omit<
  React.ComponentProps<typeof BlokRenderer>,
  | "uiComponents"
  | "initialState"
  | "dispatchAction"
  | "refuseAction"
  | "unavailableDependencies"
  | "children"
> & {
  /** The blok, as the backend serves it (`useBackendUi`). */
  blok: NewswitchBlokDeclaration;
};

/**
 * A blok the newswitch backend declares, drawn against the live app.
 *
 * - `@self.<State>` reads the app's live state of that name (the blok's demo
 *   state stands in until it has loaded).
 * - `@self.<action>(...)` assigns the app's action of that name as a task;
 *   positional arguments are named by the blok's demand on the action.
 * - Pure function calls go through the standard blok function catalog.
 */
export function NewswitchBlok({ blok, ...rendererProps }: NewswitchBlokProps) {
  const blokKey = blok.key;

  const roots = useMemo(
    () => normalizeBlokComponentTree(blok.components).roots,
    [blok],
  );

  // --- State reads -------------------------------------------------------
  const stateKeys = useMemo(() => selfStateKeys(blok), [blok]);
  const live = useGlobalStateStore(
    APP_KEY,
    useShallow((store) =>
      Object.fromEntries(stateKeys.map((key) => [key, store.states[key]])),
    ),
  );

  const stateContext = useStateContext();
  useEffect(() => {
    for (const key of stateKeys) {
      const definition = STATE_DEFINITIONS[key];
      if (definition) void stateContext.ensureState(definition);
    }
  }, [stateContext, stateKeys]);

  const initialState = useMemo(
    () => mergeLiveState(blok.demoState, live),
    [blok, live],
  );

  // --- Availability ------------------------------------------------------
  const isLive = useAppStateStore(APP_KEY, selectAppIsLive);
  const unavailableDependencies = useMemo(() => {
    const unavailable = new Map<string, string>();
    if (!isLive) unavailable.set(SELF_DEPENDENCY, REPLAY_REASON);
    for (const key of foreignDependencyKeys(blok)) {
      unavailable.set(
        key,
        `"${key}" is not served here: newswitch only provides its own (self) actions`,
      );
    }
    for (const key of stateKeys) {
      if (!STATE_DEFINITIONS[key]) {
        unavailable.set(
          SELF_DEPENDENCY,
          `This app has no state "${key}" (is the frontend out of date?)`,
        );
      }
    }
    return unavailable;
  }, [blok, isLive, stateKeys]);

  const refuseAction = useCallback<BlokRefuseActionHandler>(() => {
    if (isLive) return false;
    toast.info(REPLAY_REASON, { id: "blok-replay-paused" });
    return true;
  }, [isLive]);

  // --- Action dispatch ---------------------------------------------------
  const taskApi = useTaskContext();
  const lockStoreApi = useLockStoreApi(APP_KEY);

  const dispatchAction = useCallback<BlokDispatchActionHandler>(
    (action, _component, observe) => {
      const fail = (error: string) => {
        console.error(`Blok ${blokKey}: ${error}`);
        toast.error(error);
        observe?.({ end: "failed", error });
      };

      if (action.dependency !== SELF_DEPENDENCY) {
        return fail(
          `Dependency "${action.dependency}" is not served by newswitch.`,
        );
      }
      const definition = ACTIONS_BY_NAME.get(action.operation);
      if (!definition) {
        return fail(`This app has no action "${action.operation}".`);
      }

      const mapped = mapActionArguments(
        action.arguments,
        actionArgOrder(blok, definition.name, definition.argsSchema),
      );
      if (!mapped.ok) {
        return fail(`${definition.name}: ${mapped.error}`);
      }

      // As `useAction` does: parse (applies defaults), then encode to the wire
      // form (wraps union members in their `{ __use, __value }` envelope).
      const parsed = definition.argsSchema.safeParse(mapped.args);
      if (!parsed.success) {
        return fail(
          `${definition.name}: invalid arguments: ${z.prettifyError(parsed.error)}`,
        );
      }
      const encoded = z.safeEncode(definition.argsSchema, parsed.data);
      if (!encoded.success) {
        return fail(`${definition.name}: ${z.prettifyError(encoded.error)}`);
      }

      const { lockKey, lockingTaskId } = getBlockingLock(
        lockStoreApi.getState().locks,
        definition.lockKeys,
      );
      if (lockKey) {
        return fail(
          `${definition.name} is locked by task ${lockingTaskId} (lock: ${lockKey}).`,
        );
      }

      const reference = taskApi.createReference();
      return new Promise<void>((resolve) => {
        let settled = false;
        // Filled in once subscribed; an update may arrive before that.
        const subscription: { stop?: () => void } = {};
        const settle = () => {
          if (settled) return;
          settled = true;
          subscription.stop?.();
          resolve();
        };

        // Subscribed before the assign so no early update is missed.
        subscription.stop = taskApi.subscribeToTask(
          reference,
          APP_KEY,
          (task) => {
            observe?.(taskUpdateOf(task));
            if (TERMINAL.has(task.status)) settle();
          },
        );
        if (settled) subscription.stop();

        taskApi
          .assign(APP_KEY, definition.name, encoded.data, { reference })
          .catch((error: unknown) => {
            fail(
              `${definition.name} failed: ${error instanceof Error ? error.message : String(error)}`,
            );
            settle();
          });
      });
    },
    [blok, blokKey, lockStoreApi, taskApi],
  );

  return (
    <NewswitchHosts>
      <BlokRenderer
        // A different blok starts from a fresh runtime: nothing it wrote carries over.
        key={blokKey}
        surfaceId={`newswitch-${blokKey}`}
        // A superset of the standard catalog: the microscope's components too.
        catalog={newswitchBlokCatalog}
        {...rendererProps}
        uiComponents={roots}
        initialState={initialState}
        dispatchAction={dispatchAction}
        refuseAction={refuseAction}
        unavailableDependencies={unavailableDependencies}
      />
    </NewswitchHosts>
  );
}

const loadingAsset: BlokAsset = { status: "loading" };

/**
 * The backend's assets, for a blok's `@self.assets.<name>`: listed by `/schemas/assets`
 * (with the hash a model is checked against) and served at `/assets/<name>`.
 */
const assetHost: BlokAssetHost = {
  useAsset: (dependency, name) => {
    const ui = useBackendUi();
    const asset = ui.status === "ready" ? ui.assets[name] : undefined;
    const apiEndpoint = ui.status === "ready" ? ui.apiEndpoint : "";
    return useMemo<BlokAsset>(() => {
      if (dependency !== SELF_DEPENDENCY) {
        return {
          status: "unknown",
          reason: `"${dependency}" is not served here: newswitch only has its own (self) assets`,
        };
      }
      if (ui.status === "loading") return loadingAsset;
      if (!asset) {
        return {
          status: "unknown",
          reason: `The backend has no asset "${name}"`,
        };
      }
      return {
        status: "ready",
        ref: asset.ref,
        kind: asset.kind,
        load: async () => {
          // Behind newswitch's auth, like every route but the schemas.
          const response = await authFetch(
            `${apiEndpoint}/assets/${encodeURIComponent(name)}`,
          );
          if (!response.ok) {
            throw new Error(`Asset "${name}": ${response.status}`);
          }
          return new Uint8Array(await response.arrayBuffer());
        },
      };
    }, [apiEndpoint, asset, dependency, name, ui.status]);
  },
};

/** Opens another of the backend's bloks by name, for a scene's `OnClick open=`. */
function useSceneHost(): BlokSceneHost {
  const ui = useBackendUi();
  return useMemo<BlokSceneHost>(
    () => ({
      useModelDecorations: () => [],
      renderBlok: (name) => {
        const blok = ui.status === "ready" ? ui.bloks[name] : undefined;
        return blok ? (
          <NewswitchBlok blok={blok} chrome="minimal" sizing="intrinsic" />
        ) : (
          <p className="text-sm text-muted-foreground">
            The backend has no blok "{name}".
          </p>
        );
      },
    }),
    [ui],
  );
}

function NewswitchHosts({ children }: { children: React.ReactNode }) {
  const sceneHost = useSceneHost();
  return (
    <BlokAssetHostProvider value={assetHost}>
      <BlokSceneHostProvider value={sceneHost}>
        {children}
      </BlokSceneHostProvider>
    </BlokAssetHostProvider>
  );
}
