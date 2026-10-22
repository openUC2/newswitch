import { createContext, useContext } from "react";
import { useStore } from "zustand";
import type { ZodType } from "zod";
import { applyPatch, type Operation } from "fast-json-patch";
import { createStore, type StateCreator, type StoreApi } from "zustand/vanilla";
import { devtools, subscribeWithSelector } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import type {
  StatePatchEvent,
  StateSegmentsResponse,
} from "@/lib/arkitekt/transport/types";

export interface StateSnapshot {
  name: string;
  value: unknown;
  revision: number;
}

export interface SnapshotEnvelope {
  revision: string | number;
  state_snapshots: StateSnapshot[];
}

export interface LatestPatchEntry {
  stateName: string;
  path: string;
  revision: number;
  ts: number;
}

export interface GlobalStateStore {
  states: Record<string, unknown>;
  stateRevisions: Record<string, number | undefined>;
  globalRevision: string | number | null;
  latestPatches: LatestPatchEntry[];

  isLive: boolean;
  segments: StateSegmentsResponse[];
  snapshots: SnapshotEnvelope[];

  loading: Record<string, boolean | undefined>;
  errors: Record<string, Error | null | undefined>;

  setIsLive: (isLive: boolean) => void;
  setState: (key: string, value: unknown) => void;
  setStateSnapshot: (key: string, value: unknown, revision: number) => void;
  setStateSnapshots: (
    snapshots: Record<string, { value: unknown; revision: number }>,
    trustedRevision?: string | number | null,
  ) => void;
  replaceStateSnapshots: (
    snapshots: Record<string, { value: unknown; revision: number }>,
    trustedRevision?: string | number | null,
  ) => void;
  cacheSnapshot: (
    globalRevision: string | number,
    snapshots: Record<string, { value: unknown; revision: number }>,
  ) => void;
  upsertSegments: (segments: StateSegmentsResponse[]) => void;
  applyPatch: (envelope: StatePatchEvent, schema?: ZodType) => void;
  replaceLatestPatches: (patches: LatestPatchEntry[]) => void;
  setLoading: (key: string, loading: boolean) => void;
  setGlobalRevision: (revision: string | number | null) => void;
  setError: (key: string, error: Error | null) => void;
  getState: <T = unknown>(key: string) => T | undefined;
  clearState: (key: string) => void;
  clearAll: () => void;
}

interface GlobalStateStoreOptions {
  debug?: boolean;
  devtoolsName?: string;
  latestPatchesBufferSize?: number;
}

export const createGlobalStateStore = ({
  debug = false,
  devtoolsName = "ArkitektStateStore",
  latestPatchesBufferSize = 100,
}: GlobalStateStoreOptions = {}) => {
  const toTrustedRevision = (revision: string | number | null | undefined) => {
    if (revision === null || revision === undefined) {
      return null;
    }

    const numericRevision =
      typeof revision === "number" ? revision : Number(revision);
    return Number.isFinite(numericRevision) ? numericRevision : null;
  };

  const initializer: StateCreator<
    GlobalStateStore,
    [],
    [["zustand/subscribeWithSelector", never], ["zustand/immer", never]]
  > = subscribeWithSelector(
    immer((set, get) => ({
      states: {},
      stateRevisions: {},
      loading: {},
      isLive: false,
      segments: [],
      snapshots: [],
      errors: {},
      latestPatches: [],
      globalRevision: null,
      setIsLive: (isLive) => {
        set((state) => {
          state.isLive = isLive;
        });
      },
      setGlobalRevision: (revision) => {
        set((state) => {
          state.globalRevision = revision;
        });
      },
      setState: (key, value) => {
        set((state) => {
          state.states[key] = value;
          state.errors[key] = null;
          state.stateRevisions[key] = 0;
        });
      },

      setStateSnapshot: (key, value, revision) => {
        set((state) => {
          state.states[key] = value;
          state.errors[key] = null;
          state.stateRevisions[key] = revision;
        });
      },

      setStateSnapshots: (snapshots, trustedRevision) => {
        set((state) => {
          const normalizedTrustedRevision = toTrustedRevision(trustedRevision);
          for (const [key, snapshot] of Object.entries(snapshots)) {
            state.states[key] = snapshot.value;
            state.errors[key] = null;
            state.stateRevisions[key] =
              normalizedTrustedRevision ?? snapshot.revision;
          }
        });
      },

      replaceStateSnapshots: (snapshots, trustedRevision) => {
        set((state) => {
          const normalizedTrustedRevision = toTrustedRevision(trustedRevision);

          state.states = Object.fromEntries(
            Object.entries(snapshots).map(([key, snapshot]) => [
              key,
              snapshot.value,
            ]),
          );
          state.errors = Object.fromEntries(
            Object.keys(snapshots).map((key) => [key, null]),
          );
          state.stateRevisions = Object.fromEntries(
            Object.entries(snapshots).map(([key, snapshot]) => [
              key,
              normalizedTrustedRevision ?? snapshot.revision,
            ]),
          );
        });
      },

      cacheSnapshot: (globalRevision, snapshots) => {
        set((state) => {
          const snapshotEnvelope: SnapshotEnvelope = {
            revision: globalRevision,
            state_snapshots: Object.entries(snapshots).map(
              ([name, snapshot]) => ({
                name,
                value: snapshot.value,
                revision: snapshot.revision,
              }),
            ),
          };

          const existingIndex = state.snapshots.findIndex(
            (entry) => String(entry.revision) === String(globalRevision),
          );

          if (existingIndex >= 0) {
            state.snapshots[existingIndex] = snapshotEnvelope;
            return;
          }

          state.snapshots.push(snapshotEnvelope);
          state.snapshots.sort(
            (left, right) => Number(left.revision) - Number(right.revision),
          );
        });
      },

      upsertSegments: (segments) => {
        set((state) => {
          const nextSegments = [...state.segments];

          for (const segment of segments) {
            const existingIndex = nextSegments.findIndex(
              (entry) =>
                entry.from_global_revision === segment.from_global_revision &&
                entry.to_global_revision === segment.to_global_revision,
            );

            if (existingIndex >= 0) {
              nextSegments[existingIndex] = segment;
            } else {
              nextSegments.push(segment);
            }
          }

          nextSegments.sort(
            (left, right) =>
              left.from_global_revision - right.from_global_revision,
          );

          state.segments = nextSegments;
        });
      },

      applyPatch: (message, schema) => {
        const currentState = get().states[message.state_name];

        if (currentState === undefined) {
          console.error(
            `[StateStore] ${message.state_name} is not hydrated; dropping patch at global revision ${message.global_rev}`,
          );
          return;
        }

        console.log(
          `[StateStore] Applying patch to ${message.state_name} at global revision ${message.global_rev}:`,
          message,
        );

        set((state) => {
          const nextEntry: LatestPatchEntry = {
            stateName: message.state_name,
            path: message.path,
            revision: message.global_rev,
            ts: message.ts,
          };

          state.latestPatches = [...state.latestPatches, nextEntry].slice(
            -latestPatchesBufferSize,
          );
        });

        try {
          const clonedState = JSON.parse(JSON.stringify(currentState));
          // The patch event *is* a JSON-Patch operation (op/path/value) plus transport
          // metadata (state_name, global_rev, ts, ...) that fast-json-patch ignores.
          // It can't be narrowed structurally: `op` is the full union while `Operation`
          // is a discriminated union whose `move`/`copy` members require a `from` field
          // that StatePatchEvent doesn't carry, so no exhaustive switch can produce one.
          const operation = message as unknown as Operation;
          const { newDocument } = applyPatch(clonedState, [operation]);

          // A patch value arrives in wire form, so re-validating decodes it the same way the
          // initial snapshot was decoded (union envelopes in particular). Without this the store
          // would hold a document that is part decoded, part wire.
          let nextState: unknown = newDocument;

          if (schema) {
            const parsed = schema.safeParse(newDocument);

            if (!parsed.success) {
              console.error(
                `[StateStore] Patched ${message.state_name} failed schema validation; keeping previous value:`,
                parsed.error,
              );
              return;
            }

            nextState = parsed.data;
          }

          set((state) => {
            state.states[message.state_name] = nextState;
            state.globalRevision = message.global_rev;
          });
        } catch (err) {
          console.error(
            `[StateStore] Failed to apply patch to ${message.state_name}:`,
            err,
          );
        }
      },

      replaceLatestPatches: (patches) => {
        set((state) => {
          state.latestPatches = patches.slice(-latestPatchesBufferSize);
        });
      },

      setLoading: (key, loading) => {
        set((state) => {
          state.loading[key] = loading;
        });
      },

      setError: (key, error) => {
        set((state) => {
          state.errors[key] = error;
        });
      },

      getState: <T = unknown>(key: string) => {
        return get().states[key] as T | undefined;
      },

      clearState: (key) => {
        set((state) => {
          delete state.states[key];
          delete state.loading[key];
          delete state.errors[key];
          delete state.stateRevisions[key];
        });
      },

      clearAll: () => {
        set((state) => {
          state.states = {};
          state.loading = {};
          state.errors = {};
          state.stateRevisions = {};
          state.latestPatches = [];
          state.globalRevision = null;
          state.segments = [];
          state.snapshots = [];
        });
      },
    })),
  );

  if (debug) {
    return createStore<GlobalStateStore>()(
      devtools(initializer, { name: devtoolsName }),
    );
  }

  return createStore<GlobalStateStore>()(initializer);
};

interface GlobalStateStoreRegistryOptions {
  debug?: boolean;
  latestPatchesBufferSize?: number;
}

export interface GlobalStateStoreRegistry {
  getStoreApi: (appKey: string) => StoreApi<GlobalStateStore>;
  getStoreEntries: () => Array<[string, StoreApi<GlobalStateStore>]>;
}

export const createGlobalStateStoreRegistry = ({
  debug = false,
  latestPatchesBufferSize = 100,
}: GlobalStateStoreRegistryOptions = {}): GlobalStateStoreRegistry => {
  const stores = new Map<string, StoreApi<GlobalStateStore>>();

  const getStoreApi = (appKey: string) => {
    const existingStore = stores.get(appKey);
    if (existingStore) {
      return existingStore;
    }

    const nextStore = createGlobalStateStore({
      debug,
      devtoolsName: `ArkitektStateStore/${appKey}`,
      latestPatchesBufferSize,
    });
    stores.set(appKey, nextStore);
    return nextStore;
  };

  return {
    getStoreApi,
    getStoreEntries: () => Array.from(stores.entries()),
  };
};

export const GlobalStateStoreContext =
  createContext<GlobalStateStoreRegistry | null>(null);

export const useGlobalStateStoreRegistry = (): GlobalStateStoreRegistry => {
  const registry = useContext(GlobalStateStoreContext);

  if (!registry) {
    throw new Error("Missing GlobalStateStoreProvider");
  }

  return registry;
};

export function useGlobalStateStoreApi(appKey: string) {
  return useGlobalStateStoreRegistry().getStoreApi(appKey);
}

export function useGlobalStateStore<TSelected>(
  appKey: string,
  selector: (state: GlobalStateStore) => TSelected,
): TSelected;
export function useGlobalStateStore<TSelected>(
  appKey: string,
  selector: (state: GlobalStateStore) => TSelected,
): TSelected {
  const registry = useGlobalStateStoreRegistry();

  if (!selector) {
    throw new Error("Missing state selector");
  }

  return useStore(registry.getStoreApi(appKey), selector);
}

export const selectState =
  <T = unknown>(key: string) =>
  (store: GlobalStateStore): T | undefined =>
    store.states[key] as T | undefined;

export const selectRevision =
  (key: string) =>
  (store: GlobalStateStore): number =>
    store.stateRevisions[key] ?? 0;

export const selectLoading = (key: string) => (store: GlobalStateStore) =>
  store.loading[key] ?? false;

export const selectError = (key: string) => (store: GlobalStateStore) =>
  store.errors[key] ?? null;

export const selectLatestPatches =
  (limit?: number) =>
  (store: GlobalStateStore): LatestPatchEntry[] =>
    limit == null ? store.latestPatches : store.latestPatches.slice(-limit);

export const selectPath = <T = unknown>(path: string) => {
  const parts = path.split(".");
  return (store: GlobalStateStore): T | undefined => {
    let current: unknown = store.states;
    for (const part of parts) {
      if (current === null || current === undefined) return undefined;
      current = (current as Record<string, unknown>)[part];
    }
    return current as T | undefined;
  };
};
