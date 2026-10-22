import { createContext, useContext } from "react";
import type { StateDefinition } from "@/lib/arkitekt/state";
import type { RevisedStatesSnapshotMap } from "@/lib/arkitekt/transport/types";

export interface CheckoutStateOptions {
  appKey: string;
  stateKeys?: string[];
  /**
   * Maximum number of cached forward patch events that may be replayed locally
   * before checkout falls back to refetching a nearer snapshot.
   */
  maxLocalMaterializationEvents?: number;
  /**
   * When a nearer snapshot is required, fetch the snapshot at
   * `targetRevision - forwardEventWindow` and then replay the forward events.
   */
  forwardEventWindow?: number;
}

export interface StateContextValue {
  definitions: Record<
    string,
    StateDefinition<Record<string, unknown>, string> & { appKey: string }
  >;
  ensureState: <T extends Record<string, unknown>, TKey extends string>(
    definition: StateDefinition<T, TKey>,
  ) => Promise<void>;
  refetchState: <T extends Record<string, unknown>, TKey extends string>(
    definition: StateDefinition<T, TKey>,
  ) => Promise<T>;
  refetchAll: (
    appKey: string,
    options?: CheckoutStateOptions,
  ) => Promise<RevisedStatesSnapshotMap>;
  checkout: (
    appKey: string,
    globalRevisionId: string | number,
    options: CheckoutStateOptions,
  ) => Promise<RevisedStatesSnapshotMap>;
  /**
   * Show the app as it was at `at`: states and locks from the agent's journal, as
   * of its last entry at or before that time. Stops live sync, like `checkout`.
   * Resolves with the journal position shown.
   */
  checkoutAt: (appKey: string, at: Date) => Promise<number>;
}

export const StateContext = createContext<StateContextValue | null>(null);

export function useStateContext(): StateContextValue {
  const context = useContext(StateContext);

  if (!context) {
    throw new Error("useStateContext must be used within a BundleProvider");
  }

  return context;
}
