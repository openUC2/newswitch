/**
 * Whether a microscope panel is locked: a lock one of its actions takes is held.
 *
 * A panel's buttons are its own, not blok actions, so the renderer cannot see
 * which of them a held lock keeps from running. The panel as a whole is the
 * control: its blok wrapper is marked `data-locked` (the `locked:` variant) while
 * any of the actions it runs is locked.
 */
import { useMemo } from "react";
import { appDefinition } from "@/apps/default/app";
import { selectAppIsLive, useAppStateStore } from "@/lib/arkitekt/app-state";
import { getBlockingLock, useLockStore } from "@/lib/arkitekt/locks/store";

const APP_KEY = appDefinition.key;

/** Backend action name -> the locks it takes. */
const LOCKS_BY_ACTION = new Map<string, readonly string[]>(
  Object.values(appDefinition.actions).map(
    (definition) => [definition.name, definition.lockKeys ?? []] as const,
  ),
);

/** The locks any of `actions` takes. */
export const locksOf = (actions: readonly string[]): string[] => [
  ...new Set(actions.flatMap((action) => LOCKS_BY_ACTION.get(action) ?? [])),
];

/** Why the panel running `actions` is locked now, or `undefined` when it is not. */
export function usePanelLocked(actions: readonly string[]): string | undefined {
  const keys = useMemo(() => locksOf(actions), [actions]);
  return useLockStore(APP_KEY, (state) => {
    if (keys.length === 0) return undefined;
    const { lockKey, lockingTaskId } = getBlockingLock(state.locks, keys);
    return lockKey ? `${lockKey} is held by task ${lockingTaskId}` : undefined;
  });
}

/** Whether the app shows the live microscope (not the replay timeline's past). */
export const useIsLive = (): boolean =>
  useAppStateStore(APP_KEY, selectAppIsLive);

/** Why a control cannot be used in the past: what replay shows already happened. */
export const PAST_REASON =
  "Replay: this shows the past, nothing can be changed";
