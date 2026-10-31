import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const TuneDefinition: LockDefinition<'tune'> = {
  // No description provided
  appKey: 'default',
  key: 'tune',
};

/**
 * Hook to sync tune
 */
export const useTuneLock = (options?: UseLockOptions) => {
  return useLock<'tune'>(TuneDefinition, options);
};
