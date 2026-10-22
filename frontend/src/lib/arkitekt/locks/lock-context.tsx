import { createContext, useContext } from "react";

// The lock context currently carries no members: locks are read through the lock store
// (see `locks/store`), and this context only marks "inside a BundleProvider".
export type LockContextValue = Record<string, never>;

export const LockContext = createContext<LockContextValue | null>(null);

export function useLockContext(): LockContextValue {
  const context = useContext(LockContext);

  if (!context) {
    throw new Error("useLockContext must be used within a BundleProvider");
  }

  return context;
}
