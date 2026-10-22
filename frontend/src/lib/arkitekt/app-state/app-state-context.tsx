import { createContext, useContext } from "react";
import type { AppKey } from "@/lib/arkitekt/types";

export interface AppStateContextValue {
  goLive: (appKey: AppKey) => Promise<void>;
  stopLive: (appKey: AppKey) => Promise<void>;
}

export const AppStateContext = createContext<AppStateContextValue | null>(null);

export function useAppStateContext(): AppStateContextValue {
  const context = useContext(AppStateContext);

  if (!context) {
    throw new Error("useAppStateContext must be used within a BundleProvider");
  }

  return context;
}
