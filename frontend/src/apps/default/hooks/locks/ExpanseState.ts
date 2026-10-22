import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const ExpanseStateDefinition: LockDefinition<'expanse_state'> = {
  // No description provided
  appKey: 'default',
  key: 'expanse_state',
};

/**
 * Hook to sync expanse_state
 */
export const useExpanseStateLock = (options?: UseLockOptions) => {
  return useLock<'expanse_state'>(ExpanseStateDefinition, options);
};
