import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const IoDefinition: LockDefinition<'io'> = {
  // No description provided
  appKey: 'default',
  key: 'io',
};

/**
 * Hook to sync io
 */
export const useIoLock = (options?: UseLockOptions) => {
  return useLock<'io'>(IoDefinition, options);
};
