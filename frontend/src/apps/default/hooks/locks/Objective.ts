import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const ObjectiveDefinition: LockDefinition<'objective'> = {
  // No description provided
  appKey: 'default',
  key: 'objective',
};

/**
 * Hook to sync objective
 */
export const useObjectiveLock = (options?: UseLockOptions) => {
  return useLock<'objective'>(ObjectiveDefinition, options);
};
