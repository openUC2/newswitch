import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { toast } from "sonner";
import { useAppStateStoreRegistry } from "@/lib/arkitekt/app-state";
import {
  AppStateContext,
  type AppStateContextValue,
} from "@/lib/arkitekt/app-state/app-state-context";
import {
  LockContext,
  type LockContextValue,
} from "@/lib/arkitekt/locks/lock-context";
import { useLockStoreRegistry } from "@/lib/arkitekt/locks/store";
import {
  getScopedStateKey,
  getStateDefinitionsRecord,
  resolveStateDefinition,
  type StateDefinition,
} from "@/lib/arkitekt/state";
import {
  buildLocalMaterializationPlan,
  DEFAULT_FORWARD_EVENT_WINDOW,
  DEFAULT_MAX_LOCAL_MATERIALIZATION_EVENTS,
  materializeSnapshotMap,
  toNumericGlobalRevision,
  toSnapshotMap,
  type CheckoutConfig,
} from "@/lib/arkitekt/state/materialization";
import {
  StateContext,
  type CheckoutStateOptions,
  type StateContextValue,
} from "@/lib/arkitekt/state/state-context";
import type { LatestPatchEntry } from "@/lib/arkitekt/state/store";
import { useGlobalStateStoreRegistry } from "@/lib/arkitekt/state/store";
import { TaskContext } from "@/lib/arkitekt/task/task-context";
import {
  getRegistryTasks,
  selectTask,
  useTaskStoreRegistry,
} from "@/lib/arkitekt/task/store";
import { useTransport } from "@/lib/arkitekt/transport/transport-context";
import {
  selectIsConnected,
  selectIsReconnecting,
  selectReconnectAttempt,
  selectRegistryVersion,
  useTransportStore,
  useTransportStoreApi,
} from "@/lib/arkitekt/transport/store";
import type {
  AssignOptions,
  LockCollectionResponse,
  LockView,
  RetrieverPatchEventResponse,
  RevisedStatesSnapshotMap,
  StateCollectionResponse,
  StateSegmentsResponse,
  Task,
  TaskCollectionResponse,
  TaskContextValue,
  TaskStatus,
  TaskView,
  TransportMessageSubscription,
  TransportSocketConnectionState,
  WebSocketInitMessage,
} from "@/lib/arkitekt/transport/types";
import {
  LockEventType,
  StateEventType,
  TaskEventType,
} from "@/lib/arkitekt/transport/types";
import type { AppKey } from "@/lib/arkitekt/types";

export interface BundleProviderProps {
  children: ReactNode;
}

type StateProviderAppDefinitions = Record<
  string,
  {
    key: string;
    states: Record<string, StateDefinition<Record<string, unknown>, string>>;
    actions: Record<string, unknown>;
    locks: Record<string, unknown>;
  }
>;

const defaultConnectionState: TransportSocketConnectionState = {
  isConnected: false,
  isReconnecting: false,
  isUnconnectable: false,
  reconnectAttempt: 0,
};

function normalizeError(error: unknown, key: string): Error {
  if (error instanceof Error) {
    return error;
  }

  return new Error(`Failed to fetch ${key}`);
}

interface PartialValidation {
  snapshotMap: RevisedStatesSnapshotMap;
  errors: Record<string, Error>;
}

/**
 * Validates each state on its own, so one state whose payload disagrees with its schema cannot keep
 * the others from hydrating. Callers that can recover from a bad snapshot as a whole (by refetching)
 * should use `validateSnapshots`, which throws instead.
 */
function validateSnapshotsPartial(
  appKey: string,
  globalRevisionId: string | number,
  snapshotMap: RevisedStatesSnapshotMap,
  definitions: StateContextValue["definitions"],
): PartialValidation {
  const validated: RevisedStatesSnapshotMap = {};
  const errors: Record<string, Error> = {};

  for (const [stateKey, revisedState] of Object.entries(snapshotMap)) {
    const definition = definitions[getScopedStateKey(appKey, stateKey)];

    if (!definition) {
      validated[stateKey] = revisedState;
      continue;
    }

    const parsed = definition.schema.safeParse(revisedState.value);

    if (!parsed.success) {
      console.error(
        `[BundleProvider] Checkout validation failed for ${appKey}.${stateKey}`,
        {
          error: parsed.error,
          value: revisedState.value,
          globalRevisionId,
        },
      );

      errors[stateKey] = new Error(
        `Checkout validation failed for ${appKey}.${stateKey}: ${parsed.error.message}`,
      );
      continue;
    }

    validated[stateKey] = {
      value: parsed.data,
      revision: revisedState.revision,
    };
  }

  return { snapshotMap: validated, errors };
}

function validateSnapshots(
  appKey: string,
  globalRevisionId: string | number,
  snapshotMap: RevisedStatesSnapshotMap,
  definitions: StateContextValue["definitions"],
): RevisedStatesSnapshotMap {
  const { snapshotMap: validated, errors } = validateSnapshotsPartial(
    appKey,
    globalRevisionId,
    snapshotMap,
    definitions,
  );

  const firstError = Object.values(errors)[0];

  if (firstError) {
    throw firstError;
  }

  return validated;
}

function toSnapshotMapFromCollection(
  response: StateCollectionResponse,
  stateKeys?: string[],
): RevisedStatesSnapshotMap {
  const requestedStateKeys = stateKeys ?? Object.keys(response.states);
  const snapshotMap: RevisedStatesSnapshotMap = {};
  const revision = response.current_global_revision ?? 0;

  for (const stateKey of requestedStateKeys) {
    const stateView = response.states[stateKey];

    if (!stateView || !stateView.initialized || stateView.value == null) {
      continue;
    }

    snapshotMap[stateKey] = {
      value: stateView.value,
      revision,
    };
  }

  return snapshotMap;
}

function normalizeTaskView(appKey: AppKey, taskView: TaskView): Task {
  const now = new Date();

  return {
    id: taskView.task,
    appKey,
    action: taskView.action ?? taskView.action_key,
    args: {},
    reference: taskView.task,
    status: taskView.running ? "running" : "submitted",
    createdAt: now,
    updatedAt: now,
  };
}

function normalizeTaskCollection(
  appKey: AppKey,
  payload: TaskCollectionResponse,
): Task[] {
  return Object.values(payload.tasks).map((taskView) =>
    normalizeTaskView(appKey, taskView),
  );
}

function normalizeLockCollection(
  payload: LockCollectionResponse,
): Record<string, string | undefined> {
  return Object.fromEntries(
    Object.entries(payload.locks).map(([key, value]: [string, LockView]) => [
      key,
      value.task_id ?? undefined,
    ]),
  );
}

function getAppStateKeys(
  definitions: StateContextValue["definitions"],
  appKey: AppKey,
): string[] {
  return Object.values(definitions)
    .filter((definition) => definition.appKey === appKey)
    .map((definition) => definition.key);
}

function toLatestPatchEntriesFromEvents(
  patchEvents: RetrieverPatchEventResponse[],
): LatestPatchEntry[] {
  return patchEvents.flatMap((patchEvent) => {
    const patchOperations = Array.isArray(patchEvent.patch)
      ? patchEvent.patch
      : patchEvent.patch == null
        ? []
        : [patchEvent.patch];

    return patchOperations.map((operation) => ({
      stateName: patchEvent.state_id,
      path:
        typeof operation === "object" &&
        operation !== null &&
        "path" in operation &&
        typeof operation.path === "string"
          ? operation.path
          : "",
      revision: patchEvent.global_future_rev,
      ts: new Date(patchEvent.timepoint).getTime(),
    }));
  });
}

function toLatestPatchEntriesFromSegments(
  segments: StateSegmentsResponse[],
): LatestPatchEntry[] {
  return segments
    .flatMap((segment) => toLatestPatchEntriesFromEvents(segment.patches))
    .flat()
    .sort((left, right) => left.ts - right.ts);
}

export function BundleProvider({ children }: BundleProviderProps) {
  const transport = useTransport();
  const appStateStoreRegistry = useAppStateStoreRegistry();
  const globalStateStoreRegistry = useGlobalStateStoreRegistry();
  const lockStoreRegistry = useLockStoreRegistry();
  const taskStoreRegistry = useTaskStoreRegistry();
  const runtimeStoreApi = useTransportStoreApi();
  const stateAwareApps =
    transport.apps as unknown as StateProviderAppDefinitions;
  const definitions = useMemo(
    () => getStateDefinitionsRecord(stateAwareApps),
    [stateAwareApps],
  );

  const inflightRequestsRef = useRef(new Map<string, Promise<unknown>>());
  const subscriptionsRef = useRef(
    new Map<AppKey, TransportMessageSubscription>(),
  );
  const connectionSubscriptionsRef = useRef(new Map<AppKey, () => void>());
  const connectionStatesRef = useRef(
    new Map<AppKey, TransportSocketConnectionState>(),
  );
  const liveCountsRef = useRef(new Map<AppKey, number>());

  const isConnected = useTransportStore(selectIsConnected);
  const isReconnecting = useTransportStore(selectIsReconnecting);
  const reconnectAttempt = useTransportStore(selectReconnectAttempt);
  const registryVersion = useTransportStore(selectRegistryVersion);

  const createReference = useCallback(() => {
    return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }, []);

  const getLiveCount = useCallback(
    (appKey: AppKey) => liveCountsRef.current.get(appKey) ?? 0,
    [],
  );

  const syncConnectionState = useCallback(() => {
    const states = Array.from(connectionStatesRef.current.values());
    const runtimeStore = runtimeStoreApi.getState();

    if (states.length === 0) {
      runtimeStore.setConnected(false);
      runtimeStore.setReconnecting(false);
      runtimeStore.setUnconnectable(false);
      runtimeStore.setReconnectAttempt(0);
      return;
    }

    runtimeStore.setConnected(states.some((state) => state.isConnected));
    runtimeStore.setReconnecting(states.some((state) => state.isReconnecting));
    runtimeStore.setUnconnectable(
      states.some((state) => state.isUnconnectable),
    );
    runtimeStore.setReconnectAttempt(
      states.reduce(
        (maxAttempt, state) => Math.max(maxAttempt, state.reconnectAttempt),
        0,
      ),
    );
  }, [runtimeStoreApi]);

  const ensureAppLiveSubscription = useCallback(
    (appKey: AppKey) => {
      const appStateKeys = getAppStateKeys(definitions, appKey);

      if (!subscriptionsRef.current.has(appKey)) {
        subscriptionsRef.current.set(
          appKey,
          transport.subscribeToMessages({
            appKey,
            listener: (message) => {
              const stateStore = globalStateStoreRegistry
                .getStoreApi(appKey)
                .getState();
              const lockStore = lockStoreRegistry
                .getStoreApi(appKey)
                .getState();
              const taskStore = taskStoreRegistry
                .getStoreApi(appKey)
                .getState();

              console.debug(
                `[BundleProvider] Received message for ${appKey}:`,
                message,
              );

              switch (message.type) {
                case "INIT": {
                  const initMessage = message as WebSocketInitMessage;
                  const { snapshotMap, errors } = validateSnapshotsPartial(
                    appKey,
                    initMessage.states.current_global_revision ?? "current",
                    toSnapshotMapFromCollection(initMessage.states),
                    definitions,
                  );

                  Object.entries(errors).forEach(([stateKey, error]) => {
                    stateStore.setError(
                      stateKey,
                      normalizeError(error, stateKey),
                    );
                  });

                  stateStore.setStateSnapshots(
                    snapshotMap,
                    initMessage.states.current_global_revision,
                  );
                  if (initMessage.states.current_global_revision != null) {
                    stateStore.setGlobalRevision(
                      initMessage.states.current_global_revision,
                    );
                    stateStore.cacheSnapshot(
                      initMessage.states.current_global_revision,
                      snapshotMap,
                    );
                  }
                  stateStore.replaceLatestPatches([]);

                  appStateKeys.forEach((stateKey) => {
                    stateStore.setLoading(stateKey, false);
                  });

                  lockStore.replaceLocks(
                    normalizeLockCollection(initMessage.locks),
                  );
                  taskStore.upsertTasks(
                    normalizeTaskCollection(appKey, initMessage.tasks),
                  );
                  return;
                }
                case StateEventType.STATE_UPDATE:
                  stateStore.setState(message.state, message.value);
                  return;
                case StateEventType.STATE_PATCH:
                  stateStore.applyPatch(
                    message,
                    definitions[getScopedStateKey(appKey, message.state_name)]
                      ?.schema,
                  );
                  return;
                case LockEventType.LOCK:
                  lockStore.setLock(message.key, message.task);
                  return;
                case LockEventType.UNLOCK:
                  lockStore.setLock(message.key, undefined);
                  return;
                case TaskEventType.STARTED:
                  taskStore.updateTask(message.task, {
                    status: "running",
                  });
                  return;
                case TaskEventType.PROGRESS:
                  taskStore.updateTask(message.task, {
                    status: "running",
                    progress: message.progress,
                    progressMessage: message.message,
                  });
                  return;
                case TaskEventType.YIELD:
                  taskStore.updateTask(message.task, {
                    status: "running",
                    result: message.returns,
                  });
                  return;
                case TaskEventType.COMPLETED: {
                  const existingTask = taskStore.getTask(message.task);
                  if (existingTask?.notify) {
                    toast.success(`Task completed: ${existingTask.action}`, {
                      description: `Task ${message.task} finished successfully`,
                    });
                  }
                  taskStore.updateTask(message.task, {
                    status: "completed",
                    ...("returns" in message && message.returns !== undefined
                      ? { result: message.returns }
                      : {}),
                  });
                  return;
                }
                case TaskEventType.FAILED:
                  taskStore.updateTask(message.task, {
                    status: "failed",
                    error: message.error,
                  });
                  return;
                case TaskEventType.CRITICAL:
                  taskStore.updateTask(message.task, {
                    status: "failed",
                    error: message.error,
                  });
                  toast.error(`Critical error in task: ${message.error}`);
                  return;
                case TaskEventType.PAUSED:
                  taskStore.updateTask(message.task, {
                    status: "paused",
                  });
                  return;
                case TaskEventType.RESUMED:
                  taskStore.updateTask(message.task, {
                    status: "running",
                  });
                  return;
                case TaskEventType.CANCELLED:
                  taskStore.updateTask(message.task, {
                    status: "cancelled",
                  });
                  return;
                case TaskEventType.INTERRUPTED:
                  taskStore.updateTask(message.task, {
                    status: "interrupted",
                  });
                  return;
                case TaskEventType.LOG: {
                  const logMethod =
                    message.level === "ERROR" || message.level === "CRITICAL"
                      ? console.error
                      : message.level === "WARN"
                        ? console.warn
                        : console.log;
                  logMethod(
                    `[Agent Log] [${message.level}] ${message.message}`,
                  );
                  return;
                }
              }
            },
          }),
        );
      }

      if (!connectionSubscriptionsRef.current.has(appKey)) {
        connectionSubscriptionsRef.current.set(
          appKey,
          transport.subscribeToConnectionState(appKey, (state) => {
            connectionStatesRef.current.set(appKey, state);
            appStateStoreRegistry
              .getStoreApi(appKey)
              .getState()
              .setConnectionState(state);
            syncConnectionState();
          }),
        );
      }

      if (!connectionStatesRef.current.has(appKey)) {
        connectionStatesRef.current.set(appKey, defaultConnectionState);
        appStateStoreRegistry
          .getStoreApi(appKey)
          .getState()
          .setConnectionState(defaultConnectionState);
      }

      syncConnectionState();
    },
    [
      appStateStoreRegistry,
      definitions,
      globalStateStoreRegistry,
      lockStoreRegistry,
      syncConnectionState,
      taskStoreRegistry,
      transport,
    ],
  );

  const cleanupIfAppNotLive = useCallback(
    (appKey: AppKey) => {
      if (getLiveCount(appKey) > 0) {
        return;
      }

      subscriptionsRef.current.get(appKey)?.unsubscribe();
      subscriptionsRef.current.delete(appKey);
      connectionSubscriptionsRef.current.get(appKey)?.();
      connectionSubscriptionsRef.current.delete(appKey);
      connectionStatesRef.current.delete(appKey);
      liveCountsRef.current.delete(appKey);
      appStateStoreRegistry.getStoreApi(appKey).getState().reset();
      globalStateStoreRegistry.getStoreApi(appKey).getState().setIsLive(false);
      syncConnectionState();
    },
    [
      appStateStoreRegistry,
      getLiveCount,
      globalStateStoreRegistry,
      syncConnectionState,
    ],
  );

  const startLive = useCallback(
    async (appKey: AppKey) => {
      const stateStore = globalStateStoreRegistry
        .getStoreApi(appKey)
        .getState();
      const appStateKeys = getAppStateKeys(definitions, appKey);
      const nextCount = getLiveCount(appKey) + 1;
      liveCountsRef.current.set(appKey, nextCount);
      appStateStoreRegistry.getStoreApi(appKey).getState().setIsLive(true);
      stateStore.setIsLive(true);
      appStateKeys.forEach((stateKey) => {
        stateStore.setLoading(stateKey, true);
        stateStore.setError(stateKey, null);
      });

      ensureAppLiveSubscription(appKey);
      transport.reconnectSocket(appKey);

      if (nextCount > 1) {
        return;
      }
    },
    [
      appStateStoreRegistry,
      definitions,
      ensureAppLiveSubscription,
      getLiveCount,
      globalStateStoreRegistry,
      transport,
    ],
  );

  const stopAllLiveSync = useCallback(
    async (appKey: AppKey) => {
      liveCountsRef.current.delete(appKey);
      cleanupIfAppNotLive(appKey);
    },
    [cleanupIfAppNotLive],
  );

  const resolveCheckoutConfig = useCallback(
    (options?: CheckoutStateOptions): CheckoutConfig => ({
      maxLocalMaterializationEvents:
        options?.maxLocalMaterializationEvents ??
        DEFAULT_MAX_LOCAL_MATERIALIZATION_EVENTS,
      forwardEventWindow:
        options?.forwardEventWindow ?? DEFAULT_FORWARD_EVENT_WINDOW,
    }),
    [],
  );

  const fetchValidatedCheckoutSnapshot = useCallback(
    async (
      appKey: string,
      globalRevisionId: string | number,
      stateKeys: string[],
    ): Promise<{
      snapshotMap: RevisedStatesSnapshotMap;
      recentPatches: LatestPatchEntry[];
    }> => {
      const response = await transport.fetchStateCheckout(
        appKey,
        globalRevisionId,
        stateKeys,
      );
      return {
        snapshotMap: validateSnapshots(
          appKey,
          response.current_global_revision ?? globalRevisionId,
          toSnapshotMapFromCollection(response, stateKeys),
          definitions,
        ),
        recentPatches: toLatestPatchEntriesFromEvents(response.recent_patches),
      };
    },
    [definitions, transport],
  );

  const fetchValidatedStateCollection = useCallback(
    async (
      appKey: string,
      stateKeys: string[],
    ): Promise<{
      snapshotMap: RevisedStatesSnapshotMap;
      globalRevision: number | null;
    }> => {
      const response = await transport.fetchAll(appKey, stateKeys);
      const snapshotMap = validateSnapshots(
        appKey,
        response.current_global_revision ?? "current",
        toSnapshotMapFromCollection(response, stateKeys),
        definitions,
      );

      return {
        snapshotMap,
        globalRevision: response.current_global_revision,
      };
    },
    [definitions, transport],
  );

  const materializeValidatedSnapshot = useCallback(
    (
      appKey: string,
      globalRevisionId: string | number,
      baseSnapshot: RevisedStatesSnapshotMap,
      segments: StateSegmentsResponse[],
    ): RevisedStatesSnapshotMap | null => {
      try {
        return validateSnapshots(
          appKey,
          globalRevisionId,
          materializeSnapshotMap(baseSnapshot, segments),
          definitions,
        );
      } catch (error) {
        console.warn(
          `[BundleProvider] Falling back to direct checkout for ${appKey}@${String(globalRevisionId)} after local materialization failed.`,
          error,
        );
        return null;
      }
    },
    [definitions],
  );

  const fetchSnapshotWithForwardWindow = useCallback(
    async (
      appKey: string,
      globalRevisionId: string | number,
      stateKeys: string[],
      config: CheckoutConfig,
    ): Promise<{
      baseRevision: string | number;
      baseSnapshot: RevisedStatesSnapshotMap;
      materializedSnapshot: RevisedStatesSnapshotMap;
      segments: StateSegmentsResponse[];
      recentPatches: LatestPatchEntry[];
    }> => {
      const numericTargetRevision = toNumericGlobalRevision(globalRevisionId);

      if (numericTargetRevision === null) {
        const directCheckout = await fetchValidatedCheckoutSnapshot(
          appKey,
          globalRevisionId,
          stateKeys,
        );

        return {
          baseRevision: globalRevisionId,
          baseSnapshot: directCheckout.snapshotMap,
          materializedSnapshot: directCheckout.snapshotMap,
          segments: [],
          recentPatches: directCheckout.recentPatches,
        };
      }

      const forwardEventWindow = Math.max(0, config.forwardEventWindow);
      const baseRevision = Math.max(
        0,
        numericTargetRevision - forwardEventWindow,
      );
      const baseCheckout = await fetchValidatedCheckoutSnapshot(
        appKey,
        baseRevision,
        stateKeys,
      );
      const baseSnapshot = baseCheckout.snapshotMap;

      if (baseRevision === numericTargetRevision) {
        return {
          baseRevision,
          baseSnapshot,
          materializedSnapshot: baseSnapshot,
          segments: [],
          recentPatches: baseCheckout.recentPatches,
        };
      }

      const segments = await transport.fetchStateSegments(
        appKey,
        baseRevision,
        numericTargetRevision,
        stateKeys,
      );

      const materializedSnapshot = materializeValidatedSnapshot(
        appKey,
        globalRevisionId,
        baseSnapshot,
        [segments],
      );

      if (!materializedSnapshot) {
        const directCheckout = await fetchValidatedCheckoutSnapshot(
          appKey,
          globalRevisionId,
          stateKeys,
        );

        return {
          baseRevision: globalRevisionId,
          baseSnapshot: directCheckout.snapshotMap,
          materializedSnapshot: directCheckout.snapshotMap,
          segments: [],
          recentPatches: directCheckout.recentPatches,
        };
      }

      return {
        baseRevision,
        baseSnapshot,
        materializedSnapshot,
        segments: [segments],
        recentPatches: toLatestPatchEntriesFromSegments([segments]),
      };
    },
    [fetchValidatedCheckoutSnapshot, materializeValidatedSnapshot, transport],
  );

  const refetchState = useCallback(
    async <T extends Record<string, unknown>, TKey extends string>(
      inputDefinition: StateDefinition<T, TKey>,
    ): Promise<T> => {
      const definition = resolveStateDefinition(inputDefinition);
      const requestKey = `${definition.appKey}::${definition.key}`;
      const existingRequest = inflightRequestsRef.current.get(requestKey);

      if (existingRequest) {
        return existingRequest as Promise<T>;
      }

      const storeApi = globalStateStoreRegistry.getStoreApi(definition.appKey);
      const store = storeApi.getState();
      store.setLoading(definition.key, true);
      store.setError(definition.key, null);

      const request = transport
        .fetchState<T>(definition.appKey, definition.key)
        .then((response) => {
          const parsed = definition.schema.safeParse(response.value);

          if (!parsed.success) {
            console.error(
              `[BundleProvider] Validation failed for ${definition.appKey}.${definition.key}`,
              {
                error: parsed.error,
                value: response.value,
              },
            );

            throw new Error(
              `Validation failed for ${definition.appKey}.${definition.key}`,
            );
          }

          storeApi
            .getState()
            .setStateSnapshot(
              definition.key,
              parsed.data as T,
              response.local_revision ?? 0,
            );

          return parsed.data as T;
        })
        .catch((error) => {
          const normalizedError = normalizeError(
            error,
            `${definition.appKey}.${definition.key}`,
          );
          storeApi.getState().setError(definition.key, normalizedError);
          throw normalizedError;
        })
        .finally(() => {
          inflightRequestsRef.current.delete(requestKey);
          storeApi.getState().setLoading(definition.key, false);
        });

      inflightRequestsRef.current.set(requestKey, request);

      return request;
    },
    [globalStateStoreRegistry, transport],
  );

  const refetchAll = useCallback<StateContextValue["refetchAll"]>(
    async (appKey, options) => {
      const availableDefinitions = Object.values(definitions).filter(
        (definition) => definition.appKey === appKey,
      );
      const stateKeys =
        options?.stateKeys ??
        availableDefinitions.map((definition) => definition.key);

      if (stateKeys.length === 0) {
        return {};
      }

      const storeApi = globalStateStoreRegistry.getStoreApi(appKey);
      stateKeys.forEach((key) => {
        const stateStore = storeApi.getState();
        stateStore.setLoading(key, true);
        stateStore.setError(key, null);
      });

      try {
        const { snapshotMap, globalRevision } =
          await fetchValidatedStateCollection(appKey, stateKeys);
        const stateStore = storeApi.getState();
        stateStore.setStateSnapshots(snapshotMap, globalRevision);
        stateStore.replaceLatestPatches([]);
        if (globalRevision != null) {
          stateStore.setGlobalRevision(globalRevision);
          stateStore.cacheSnapshot(globalRevision, snapshotMap);
        }

        return snapshotMap;
      } catch (error) {
        const normalizedError = normalizeError(error, `${appKey}@current`);
        stateKeys.forEach((key) => {
          storeApi.getState().setError(key, normalizedError);
        });
        throw normalizedError;
      } finally {
        stateKeys.forEach((key) => {
          storeApi.getState().setLoading(key, false);
        });
      }
    },
    [definitions, fetchValidatedStateCollection, globalStateStoreRegistry],
  );

  const ensureState = useCallback(
    async <T extends Record<string, unknown>, TKey extends string>(
      definition: StateDefinition<T, TKey>,
    ): Promise<void> => {
      const resolvedDefinition = resolveStateDefinition(definition);
      const currentState = globalStateStoreRegistry
        .getStoreApi(resolvedDefinition.appKey)
        .getState()
        .getState(resolvedDefinition.key);

      if (currentState !== undefined) {
        return;
      }

      await refetchState(resolvedDefinition);
    },
    [globalStateStoreRegistry, refetchState],
  );

  const checkout = useCallback<StateContextValue["checkout"]>(
    async (appKey, globalRevisionId, options) => {
      const availableDefinitions = Object.values(definitions).filter(
        (definition) => definition.appKey === appKey,
      );
      const stateKeys =
        options?.stateKeys ??
        availableDefinitions.map((definition) => definition.key);

      if (stateKeys.length === 0) {
        return {};
      }

      const storeApi = globalStateStoreRegistry.getStoreApi(appKey);
      const checkoutConfig = resolveCheckoutConfig(options);

      await stopAllLiveSync(appKey);
      storeApi.getState().setGlobalRevision(globalRevisionId);

      stateKeys.forEach((key) => {
        const stateStore = storeApi.getState();
        stateStore.setLoading(key, true);
        stateStore.setError(key, null);
      });

      try {
        const currentStore = storeApi.getState();
        const numericTargetRevision = toNumericGlobalRevision(globalRevisionId);
        const localPlan =
          numericTargetRevision === null
            ? null
            : buildLocalMaterializationPlan(
                currentStore.snapshots,
                currentStore.segments,
                stateKeys,
                numericTargetRevision,
                checkoutConfig.maxLocalMaterializationEvents,
              );

        const checkoutResult = localPlan
          ? (() => {
              const baseSnapshot = toSnapshotMap(localPlan.baseSnapshot);
              const materializedSnapshot = materializeValidatedSnapshot(
                appKey,
                globalRevisionId,
                baseSnapshot,
                localPlan.segments,
              );

              if (!materializedSnapshot) {
                return null;
              }

              return {
                baseRevision: localPlan.baseSnapshot.revision,
                baseSnapshot,
                materializedSnapshot,
                segments: localPlan.segments,
                recentPatches: toLatestPatchEntriesFromSegments(
                  localPlan.segments,
                ),
              };
            })()
          : null;

        const resolvedCheckoutResult =
          checkoutResult ??
          (await fetchSnapshotWithForwardWindow(
            appKey,
            globalRevisionId,
            stateKeys,
            checkoutConfig,
          ));

        const stateStore = storeApi.getState();
        stateStore.replaceStateSnapshots(
          resolvedCheckoutResult.materializedSnapshot,
          globalRevisionId,
        );
        stateStore.setGlobalRevision(globalRevisionId);
        stateStore.replaceLatestPatches(resolvedCheckoutResult.recentPatches);
        stateStore.cacheSnapshot(
          resolvedCheckoutResult.baseRevision,
          resolvedCheckoutResult.baseSnapshot,
        );
        stateStore.cacheSnapshot(
          globalRevisionId,
          resolvedCheckoutResult.materializedSnapshot,
        );
        if (resolvedCheckoutResult.segments.length > 0) {
          stateStore.upsertSegments(resolvedCheckoutResult.segments);
        }

        return resolvedCheckoutResult.materializedSnapshot;
      } catch (error) {
        const normalizedError = normalizeError(
          error,
          `${appKey}@${String(globalRevisionId)}`,
        );
        stateKeys.forEach((key) => {
          storeApi.getState().setError(key, normalizedError);
        });
        throw normalizedError;
      } finally {
        stateKeys.forEach((key) => {
          storeApi.getState().setLoading(key, false);
        });
      }
    },
    [
      definitions,
      fetchSnapshotWithForwardWindow,
      globalStateStoreRegistry,
      materializeValidatedSnapshot,
      resolveCheckoutConfig,
      stopAllLiveSync,
    ],
  );

  const assign: TaskContextValue["assign"] = useCallback(
    async <TArgs, TReturn>(
      appKey: AppKey,
      actionName: string,
      args: TArgs,
      options?: AssignOptions,
    ) => {
      const storeApi = taskStoreRegistry.getStoreApi(appKey);
      const reference = options?.reference || createReference();

      storeApi.getState().addTask(actionName, reference, args, "pending");
      if (options?.notify) {
        storeApi.getState().updateTask(reference, { notify: true });
      }

      try {
        const data = await transport.assignAction(appKey, actionName, args, {
          ...options,
          reference,
        });

        storeApi.getState().setAssignationID(reference, data.task_id);
        storeApi.getState().updateTask(reference, { status: data.status });

        return storeApi.getState().getTask<TArgs, TReturn>(reference)!;
      } catch (error: unknown) {
        const message =
          error instanceof Error ? error.message : "Unknown transport error";
        storeApi.getState().updateTask(reference, {
          status: "failed",
          error: message,
        });
        throw error;
      }
    },
    [createReference, taskStoreRegistry, transport],
  );

  const getTask: TaskContextValue["getTask"] = useCallback(
    async <TArgs = unknown, TReturn = unknown>(
      appKey: AppKey,
      taskId: string,
    ) => {
      const task = await transport.fetchTask<TArgs, TReturn>(appKey, taskId);
      taskStoreRegistry.getStoreApi(appKey).getState().updateTask(taskId, task);
      return task;
    },
    [taskStoreRegistry, transport],
  );

  const getCachedTask = useCallback(
    (taskId: string, appKey: AppKey): Task | undefined =>
      taskStoreRegistry.getStoreApi(appKey).getState().getTask(taskId),
    [taskStoreRegistry],
  );

  const updateTaskStatus = useCallback(
    async (
      taskId: string,
      status: TaskStatus,
      request: () => Promise<void>,
      appKey: AppKey,
    ) => {
      await request();
      taskStoreRegistry
        .getStoreApi(appKey)
        .getState()
        .updateTask(taskId, { status });
    },
    [taskStoreRegistry],
  );

  const cancelTask = useCallback(
    async (appKey: AppKey, taskId: string) => {
      await updateTaskStatus(
        taskId,
        "cancelled",
        () => transport.cancelTaskRequest(appKey, taskId),
        appKey,
      );
    },
    [transport, updateTaskStatus],
  );

  const pauseTask = useCallback(
    async (appKey: AppKey, taskId: string) => {
      await updateTaskStatus(
        taskId,
        "paused",
        () => transport.pauseTaskRequest(appKey, taskId),
        appKey,
      );
    },
    [transport, updateTaskStatus],
  );

  const unpauseTask = useCallback(
    async (appKey: AppKey, taskId: string) => {
      await updateTaskStatus(
        taskId,
        "running",
        () => transport.unpauseTaskRequest(appKey, taskId),
        appKey,
      );
    },
    [transport, updateTaskStatus],
  );

  const stepTask = useCallback(
    async (appKey: AppKey, taskId: string) => {
      await updateTaskStatus(
        taskId,
        "running",
        () => transport.stepTaskRequest(appKey, taskId),
        appKey,
      );
    },
    [transport, updateTaskStatus],
  );

  const subscribeToTask = useCallback(
    (
      taskId: string,
      appKey: AppKey,
      callback: (task: Task) => void,
    ): (() => void) => {
      const storeApi = taskStoreRegistry.getStoreApi(appKey);

      return storeApi.subscribe((state, previousState) => {
        const task = selectTask(taskId)(state);
        const previousTask = selectTask(taskId)(previousState);

        if (task && task !== previousTask) {
          callback(task as Task);
        }
      });
    },
    [taskStoreRegistry],
  );

  const waitForTask: TaskContextValue["waitForTask"] = useCallback(
    <TArgs = unknown, TReturn = unknown>(
      appKey: AppKey,
      taskId: string,
    ): Promise<Task<TArgs, TReturn>> => {
      const cachedTask = taskStoreRegistry
        .getStoreApi(appKey)
        .getState()
        .getTask<TArgs, TReturn>(taskId);

      if (cachedTask?.status === "completed") {
        return Promise.resolve(cachedTask);
      }

      if (cachedTask?.status === "failed") {
        return Promise.reject(new Error(cachedTask.error || "Task failed"));
      }

      if (
        cachedTask?.status === "cancelled" ||
        cachedTask?.status === "interrupted"
      ) {
        return Promise.reject(new Error(`Task was ${cachedTask.status}`));
      }

      return new Promise<Task<TArgs, TReturn>>((resolve, reject) => {
        const unsubscribe = subscribeToTask(taskId, appKey, (task) => {
          const typedTask = task as Task<TArgs, TReturn>;

          if (typedTask.status === "completed") {
            unsubscribe();
            resolve(typedTask);
            return;
          }

          if (typedTask.status === "failed") {
            unsubscribe();
            reject(new Error(typedTask.error || "Task failed"));
            return;
          }

          if (
            typedTask.status === "cancelled" ||
            typedTask.status === "interrupted"
          ) {
            unsubscribe();
            reject(new Error(`Task was ${typedTask.status}`));
          }
        });
      });
    },
    [subscribeToTask, taskStoreRegistry],
  );

  const appStateGoLive = useCallback<AppStateContextValue["goLive"]>(
    async (appKey) => {
      await startLive(appKey);
    },
    [startLive],
  );

  const appStateStopLive = useCallback<AppStateContextValue["stopLive"]>(
    async (appKey) => {
      await stopAllLiveSync(appKey);
    },
    [stopAllLiveSync],
  );

  const reconnect = useCallback(
    (appKey: AppKey) => {
      transport.reconnectSocket(appKey);
    },
    [transport],
  );

  const disconnect = useCallback(
    (appKey: AppKey) => {
      transport.disconnectSocket(appKey);
    },
    [transport],
  );

  void registryVersion;

  const tasks = getRegistryTasks(taskStoreRegistry);
  const tasksMap = useMemo(() => {
    const map = new Map<string, Task>();
    for (const [appKey, appTasks] of Object.entries(tasks)) {
      for (const [reference, task] of Object.entries(appTasks)) {
        map.set(`${appKey}:${reference}`, task);
      }
    }
    return map;
  }, [tasks]);

  const stateValue = useMemo<StateContextValue>(
    () => ({
      definitions,
      ensureState,
      refetchState,
      refetchAll,
      checkout,
    }),
    [checkout, definitions, ensureState, refetchAll, refetchState],
  );

  const taskValue = useMemo<TaskContextValue>(
    () => ({
      apiEndpoint: transport.apiEndpoint,
      isConnected,
      isReconnecting,
      reconnectAttempt,
      tasks: tasksMap,
      assign,
      getTask,
      getCachedTask,
      subscribeToTask,
      waitForTask,
      createReference,
      cancelTask,
      pauseTask,
      unpauseTask,
      stepTask,
      reconnect,
      disconnect,
    }),
    [
      assign,
      cancelTask,
      createReference,
      disconnect,
      getCachedTask,
      getTask,
      isConnected,
      isReconnecting,
      pauseTask,
      reconnect,
      reconnectAttempt,
      stepTask,
      subscribeToTask,
      tasksMap,
      transport.apiEndpoint,
      unpauseTask,
      waitForTask,
    ],
  );

  const lockValue = useMemo<LockContextValue>(() => ({}), []);

  const appStateValue = useMemo<AppStateContextValue>(
    () => ({
      goLive: appStateGoLive,
      stopLive: appStateStopLive,
    }),
    [appStateGoLive, appStateStopLive],
  );

  useEffect(() => {
    const subscriptions = subscriptionsRef.current;
    const connectionSubscriptions = connectionSubscriptionsRef.current;
    const connectionStates = connectionStatesRef.current;
    const liveCounts = liveCountsRef.current;

    return () => {
      subscriptions.forEach((subscription) => subscription.unsubscribe());
      subscriptions.clear();
      connectionSubscriptions.forEach((unsubscribe) => unsubscribe());
      connectionSubscriptions.clear();
      connectionStates.clear();
      liveCounts.clear();
      appStateStoreRegistry.getStoreEntries().forEach(([, storeApi]) => {
        storeApi.getState().reset();
      });
      const runtimeStore = runtimeStoreApi.getState();
      runtimeStore.setConnected(false);
      runtimeStore.setReconnecting(false);
      runtimeStore.setUnconnectable(false);
      runtimeStore.setReconnectAttempt(0);
    };
  }, [appStateStoreRegistry, runtimeStoreApi]);

  return (
    <AppStateContext.Provider value={appStateValue}>
      <StateContext.Provider value={stateValue}>
        <TaskContext.Provider value={taskValue}>
          <LockContext.Provider value={lockValue}>
            {children}
          </LockContext.Provider>
        </TaskContext.Provider>
      </StateContext.Provider>
    </AppStateContext.Provider>
  );
}
