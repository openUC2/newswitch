import {
  useLock,
  type LockDefinition,
  type UseLockOptions,
} from '@/lib/arkitekt/locks';

// --- Definition ---
export const SwapDefinition: LockDefinition<'swap'> = {
  // No description provided
  appKey: 'default',
  key: 'swap',
};

/**
 * Hook to sync swap
 */
export const useSwapLock = (options?: UseLockOptions) => {
  return useLock<'swap'>(SwapDefinition, options);
};
