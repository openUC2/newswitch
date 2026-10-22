// src/hooks/useStatePath.ts
import { selectPath, useGlobalStateStore } from "@/lib/arkitekt/state/store";

/**
 * Subscribe to a specific path within the global state store.
 * This allows components to only re-render when their specific data changes.
 *
 * @example
 * // Subscribe to just the exposure_time within CameraState
 * const exposureTime = useStatePath<number>('CameraState.exposure_time');
 *
 * // Subscribe to the full CameraState
 * const camera = useStatePath<CameraState>('CameraState');
 *
 * @param path Dot-separated path like "CameraState.exposure_time"
 * @returns The value at that path, or undefined if not found
 */
export const useStatePath = <T = unknown>(
  appKey: string,
  path: string,
): T | undefined => {
  // Use simple selector - Zustand handles reference equality internally
  return useGlobalStateStore(appKey, selectPath<T>(path));
};

/**
 * Subscribe to multiple paths at once, returning an object with each path's value.
 *
 * @example
 * const { exposure, gain } = useStatePaths({
 *   exposure: 'CameraState.exposure_time',
 *   gain: 'CameraState.gain',
 * });
 */
export const useStatePaths = <T extends Record<string, string>>(
  appKey: string,
  paths: T,
): { [K in keyof T]: unknown } => {
  // Select each path value - component will re-render when any value changes
  return useGlobalStateStore(appKey, (store) => {
    const result: Record<string, unknown> = {};
    for (const [key, path] of Object.entries(paths)) {
      result[key] = selectPath(path)(store);
    }
    return result as { [K in keyof T]: unknown };
  });
};
