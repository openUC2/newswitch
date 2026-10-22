import { createContext, useContext, useMemo } from "react";
import { useStore } from "zustand";
import { devtools, subscribeWithSelector } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import { createStore, type StateCreator, type StoreApi } from "zustand/vanilla";

export interface LockStore {
  locks: Record<string, string | undefined | null>;
  setLock: (key: string, value: string | undefined) => void;
  replaceLocks: (locks: Record<string, string | undefined>) => void;
  clearLock: (key: string) => void;
  clearLocks: () => void;
}

export interface BlockingLockState {
  isLocked: boolean;
  lockKey: string | null;
  lockingTaskId: string | undefined;
}

interface LockStoreOptions {
  debug?: boolean;
  devtoolsName?: string;
}

const unlockedState: BlockingLockState = {
  isLocked: false,
  lockKey: null,
  lockingTaskId: undefined,
};

const resolveBlockingLock = (
  locks: Record<string, string | undefined | null> | undefined,
  lockKeys: string[],
): BlockingLockState | null => {
  if (!locks) {
    return null;
  }

  for (const key of lockKeys) {
    const lockingTaskId = locks[key];

    if (lockingTaskId !== undefined && lockingTaskId !== null) {
      return {
        isLocked: true,
        lockKey: key,
        lockingTaskId,
      };
    }
  }

  return null;
};

export const createLockStore = ({
  debug = false,
  devtoolsName = "ArkitektLockStore",
}: LockStoreOptions = {}) => {
  const initializer: StateCreator<
    LockStore,
    [],
    [["zustand/subscribeWithSelector", never], ["zustand/immer", never]]
  > = subscribeWithSelector(
    immer((set) => ({
      locks: {},

      setLock: (key, value) => {
        set((state) => {
          state.locks[key] = value;
        });
      },

      replaceLocks: (locks) => {
        set((state) => {
          state.locks = { ...locks };
        });
      },

      clearLock: (key) => {
        set((state) => {
          delete state.locks[key];
        });
      },

      clearLocks: () => {
        set((state) => {
          state.locks = {};
        });
      },
    })),
  );

  if (debug) {
    return createStore<LockStore>()(
      devtools(initializer, { name: devtoolsName }),
    );
  }

  return createStore<LockStore>()(initializer);
};

interface LockStoreRegistryOptions {
  debug?: boolean;
}

export interface LockStoreRegistry {
  getStoreApi: (appKey: string) => StoreApi<LockStore>;
  getStoreEntries: () => Array<[string, StoreApi<LockStore>]>;
}

export const createLockStoreRegistry = ({
  debug = false,
}: LockStoreRegistryOptions = {}): LockStoreRegistry => {
  const stores = new Map<string, StoreApi<LockStore>>();

  const getStoreApi = (appKey: string) => {
    const existingStore = stores.get(appKey);
    if (existingStore) {
      return existingStore;
    }

    const nextStore = createLockStore({
      debug,
      devtoolsName: `ArkitektLockStore/${appKey}`,
    });
    stores.set(appKey, nextStore);
    return nextStore;
  };

  return {
    getStoreApi,
    getStoreEntries: () => Array.from(stores.entries()),
  };
};

export const LockStoreContext = createContext<LockStoreRegistry | null>(null);

export const useLockStoreRegistry = (): LockStoreRegistry => {
  const registry = useContext(LockStoreContext);

  if (!registry) {
    throw new Error("Missing LockStoreProvider");
  }

  return registry;
};

export function useLockStoreApi(appKey: string) {
  return useLockStoreRegistry().getStoreApi(appKey);
}

export function useLockStore<TSelected>(
  appKey: string,
  selector: (state: LockStore) => TSelected,
): TSelected;
export function useLockStore<TSelected>(
  appKey: string,
  selector: (state: LockStore) => TSelected,
): TSelected {
  const registry = useLockStoreRegistry();

  if (!selector) {
    throw new Error("Missing lock selector");
  }

  return useStore(registry.getStoreApi(appKey), selector);
}

export const selectLock =
  (key: string) =>
  (store: LockStore): string | undefined | null =>
    store.locks[key];

export function getBlockingLock(
  locks: Record<string, string | undefined | null>,
  lockKeys: string[] = [],
): BlockingLockState {
  return resolveBlockingLock(locks, lockKeys) ?? unlockedState;
}

export function useBlockingLock(
  appKey: string,
  lockKeys: string[] = [],
): BlockingLockState {
  const locks = useLockStore(appKey, (state) => state.locks);

  return useMemo(() => {
    return resolveBlockingLock(locks, lockKeys) ?? unlockedState;
  }, [locks, lockKeys]);
}
