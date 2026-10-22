import type { ReactNode } from "react";
import { useMemo } from "react";
import {
  AppStateStoreContext,
  createAppStateStoreRegistry,
} from "@/lib/arkitekt/app-state";
import {
  createLockStoreRegistry,
  LockStoreContext,
} from "@/lib/arkitekt/locks/store";
import {
  createGlobalStateStoreRegistry,
  GlobalStateStoreContext,
} from "@/lib/arkitekt/state/store";
import {
  createTaskStoreRegistry,
  TaskStoreContext,
} from "@/lib/arkitekt/task/store";
import {
  createTransportStore,
  TransportStoreContext,
} from "@/lib/arkitekt/transport/store";

export interface ArkitektStoreBundle {
  appStateStore: ReturnType<typeof createAppStateStoreRegistry>;
  globalStateStore: ReturnType<typeof createGlobalStateStoreRegistry>;
  taskStore: ReturnType<typeof createTaskStoreRegistry>;
  transportStore: ReturnType<typeof createTransportStore>;
  lockStore: ReturnType<typeof createLockStoreRegistry>;
}

export interface ArkitektStoreProviderProps {
  children: ReactNode;
  scope?: string;
  debug?: boolean;
  latestPatchesBufferSize?: number;
}

const scopedBundles = new Map<string, ArkitektStoreBundle>();

const createArkitektStoreBundle = (
  debug = false,
  latestPatchesBufferSize = 100,
): ArkitektStoreBundle => {
  const transportStore = createTransportStore();

  return {
    appStateStore: createAppStateStoreRegistry({ debug }),
    globalStateStore: createGlobalStateStoreRegistry({
      debug,
      latestPatchesBufferSize,
    }),
    taskStore: createTaskStoreRegistry(transportStore, { debug }),
    transportStore,
    lockStore: createLockStoreRegistry({ debug }),
  };
};

const getScopedBundle = (
  scope: string,
  debug = false,
  latestPatchesBufferSize = 100,
): ArkitektStoreBundle => {
  const bundleKey = `${scope}::debug-${debug ? "on" : "off"}::patches-${latestPatchesBufferSize}`;
  const existingBundle = scopedBundles.get(bundleKey);

  if (existingBundle) {
    return existingBundle;
  }

  const nextBundle = createArkitektStoreBundle(debug, latestPatchesBufferSize);
  scopedBundles.set(bundleKey, nextBundle);
  return nextBundle;
};

export function ArkitektStoreProvider({
  children,
  scope = "default",
  debug = false,
  latestPatchesBufferSize = 100,
}: ArkitektStoreProviderProps) {
  const stores = useMemo(
    () => getScopedBundle(scope, debug, latestPatchesBufferSize),
    [debug, latestPatchesBufferSize, scope],
  );

  return (
    <AppStateStoreContext.Provider value={stores.appStateStore}>
      <GlobalStateStoreContext.Provider value={stores.globalStateStore}>
        <TransportStoreContext.Provider value={stores.transportStore}>
          <TaskStoreContext.Provider value={stores.taskStore}>
            <LockStoreContext.Provider value={stores.lockStore}>
              {children}
            </LockStoreContext.Provider>
          </TaskStoreContext.Provider>
        </TransportStoreContext.Provider>
      </GlobalStateStoreContext.Provider>
    </AppStateStoreContext.Provider>
  );
}
