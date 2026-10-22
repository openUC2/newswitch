import { createContext, useContext } from "react";
import { useStore } from "zustand";
import { createStore, type StateCreator, type StoreApi } from "zustand/vanilla";
import { devtools, subscribeWithSelector } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import type { TransportSocketConnectionState } from "@/lib/arkitekt/transport/types";

export interface AppStateStore {
  isLive: boolean;
  isConnected: boolean;
  isReconnecting: boolean;
  isUnconnectable: boolean;
  reconnectAttempt: number;
  setIsLive: (isLive: boolean) => void;
  setConnectionState: (state: TransportSocketConnectionState) => void;
  reset: () => void;
}

interface AppStateStoreOptions {
  debug?: boolean;
  devtoolsName?: string;
}

const defaultConnectionState: TransportSocketConnectionState = {
  isConnected: false,
  isReconnecting: false,
  isUnconnectable: false,
  reconnectAttempt: 0,
};

export const createAppStateStore = ({
  debug = false,
  devtoolsName = "ArkitektAppStateStore",
}: AppStateStoreOptions = {}) => {
  const initializer: StateCreator<
    AppStateStore,
    [],
    [["zustand/subscribeWithSelector", never], ["zustand/immer", never]]
  > = subscribeWithSelector(
    immer((set) => ({
      isLive: false,
      ...defaultConnectionState,
      setIsLive: (isLive) => {
        set((state) => {
          state.isLive = isLive;
        });
      },
      setConnectionState: (connectionState) => {
        set((state) => {
          state.isConnected = connectionState.isConnected;
          state.isReconnecting = connectionState.isReconnecting;
          state.isUnconnectable = connectionState.isUnconnectable;
          state.reconnectAttempt = connectionState.reconnectAttempt;
        });
      },
      reset: () => {
        set((state) => {
          state.isLive = false;
          state.isConnected = false;
          state.isReconnecting = false;
          state.isUnconnectable = false;
          state.reconnectAttempt = 0;
        });
      },
    })),
  );

  if (debug) {
    return createStore<AppStateStore>()(
      devtools(initializer, { name: devtoolsName }),
    );
  }

  return createStore<AppStateStore>()(initializer);
};

interface AppStateStoreRegistryOptions {
  debug?: boolean;
}

export interface AppStateStoreRegistry {
  getStoreApi: (appKey: string) => StoreApi<AppStateStore>;
  getStoreEntries: () => Array<[string, StoreApi<AppStateStore>]>;
}

export const createAppStateStoreRegistry = ({
  debug = false,
}: AppStateStoreRegistryOptions = {}): AppStateStoreRegistry => {
  const stores = new Map<string, StoreApi<AppStateStore>>();

  const getStoreApi = (appKey: string) => {
    const existingStore = stores.get(appKey);
    if (existingStore) {
      return existingStore;
    }

    const nextStore = createAppStateStore({
      debug,
      devtoolsName: `ArkitektAppStateStore/${appKey}`,
    });
    stores.set(appKey, nextStore);
    return nextStore;
  };

  return {
    getStoreApi,
    getStoreEntries: () => Array.from(stores.entries()),
  };
};

export const AppStateStoreContext = createContext<AppStateStoreRegistry | null>(
  null,
);

export const useAppStateStoreRegistry = (): AppStateStoreRegistry => {
  const registry = useContext(AppStateStoreContext);

  if (!registry) {
    throw new Error("Missing AppStateStoreProvider");
  }

  return registry;
};

export function useAppStateStoreApi(appKey: string) {
  return useAppStateStoreRegistry().getStoreApi(appKey);
}

export function useAppStateStore<TSelected>(
  appKey: string,
  selector: (state: AppStateStore) => TSelected,
): TSelected {
  return useStore(useAppStateStoreApi(appKey), selector);
}

export const selectAppIsLive = (store: AppStateStore) => store.isLive;
export const selectAppIsReplayMode = (store: AppStateStore) => !store.isLive;
export const selectAppIsConnected = (store: AppStateStore) => store.isConnected;
export const selectAppIsReconnecting = (store: AppStateStore) =>
  store.isReconnecting;
export const selectAppIsUnconnectable = (store: AppStateStore) =>
  store.isUnconnectable;
export const selectAppReconnectAttempt = (store: AppStateStore) =>
  store.reconnectAttempt;
