import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const IlluminationDefinition: LockDefinition<'illumination'> = {
  // No description provided
  appKey: 'default',
  key: 'illumination',
};

/**
 * Hook to sync illumination
 */
export const useIlluminationLock = (options?: UseLockOptions) => {
  return useLock<'illumination'>(IlluminationDefinition, options);
};
