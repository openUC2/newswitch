import { createContext, useContext } from "react";
import { useStore } from "zustand";
import { createStore, type StoreApi } from "zustand/vanilla";
import { subscribeWithSelector } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";

export interface TransportStore {
  isConnected: boolean;
  isReconnecting: boolean;
  isUnconnectable: boolean;
  reconnectAttempt: number;
  registryVersion: number;
  setConnected: (connected: boolean) => void;
  setReconnecting: (reconnecting: boolean) => void;
  setUnconnectable: (unconnectable: boolean) => void;
  setReconnectAttempt: (attempt: number) => void;
  incrementReconnectAttempt: () => number;
  resetReconnect: () => void;
  bumpRegistryVersion: () => void;
}

export const createTransportStore = () =>
  createStore<TransportStore>()(
    subscribeWithSelector(
      immer((set) => ({
        isConnected: false,
        isReconnecting: false,
        isUnconnectable: false,
        reconnectAttempt: 0,
        registryVersion: 0,
        setConnected: (connected) => {
          set((state) => {
            state.isConnected = connected;
            if (connected) {
              state.isUnconnectable = false;
            }
          });
        },
        setReconnecting: (reconnecting) => {
          set((state) => {
            state.isReconnecting = reconnecting;
          });
        },
        setUnconnectable: (unconnectable) => {
          set((state) => {
            state.isUnconnectable = unconnectable;
            if (unconnectable) {
              state.isReconnecting = false;
            }
          });
        },
        setReconnectAttempt: (attempt) => {
          set((state) => {
            state.reconnectAttempt = attempt;
          });
        },
        incrementReconnectAttempt: () => {
          let nextAttempt = 0;
          set((state) => {
            nextAttempt = state.reconnectAttempt + 1;
            state.reconnectAttempt = nextAttempt;
          });
          return nextAttempt;
        },
        resetReconnect: () => {
          set((state) => {
            state.reconnectAttempt = 0;
            state.isReconnecting = false;
            state.isUnconnectable = false;
          });
        },
        bumpRegistryVersion: () => {
          set((state) => {
            state.registryVersion += 1;
          });
        },
      })),
    ),
  );

export const TransportStoreContext =
  createContext<StoreApi<TransportStore> | null>(null);

export function useTransportStoreApi() {
  const storeApi = useContext(TransportStoreContext);

  if (!storeApi) {
    throw new Error("Missing TransportStoreProvider");
  }

  return storeApi;
}

export function useTransportStore<TSelected>(
  selector: (state: TransportStore) => TSelected,
): TSelected {
  return useStore(useTransportStoreApi(), selector);
}

export const selectIsConnected = (store: TransportStore) => store.isConnected;
export const selectIsReconnecting = (store: TransportStore) =>
  store.isReconnecting;
export const selectIsUnconnectable = (store: TransportStore) =>
  store.isUnconnectable;
export const selectReconnectAttempt = (store: TransportStore) =>
  store.reconnectAttempt;
export const selectRegistryVersion = (store: TransportStore) =>
  store.registryVersion;
